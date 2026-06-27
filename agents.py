"""
LLM agent callers for 出題官 (question master) and 診断官 (diagnosis master).
All calls go to the Gemini API; JSON output is enforced via responseMimeType.
"""

import json
import os
import re
import ssl

import httpx

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Use project CA bundle when running locally behind the proxy; fall back to
# system trust store for Cloud Run.
_CA_BUNDLE = "/root/.ccr/ca-bundle.crt"
_SSL_VERIFY: bool | str = _CA_BUNDLE if os.path.exists(_CA_BUNDLE) else True

# ── System prompts ────────────────────────────────────────────────────────────

QUESTION_MASTER_SYSTEM = """\
你是日语阅读测评系统的「出题官」。每次根据给定目标难度,生成一道阅读理解选择题。

【输入】(JSON)
{
  "target_jlpt": "N3",
  "target_level": 6,
  "focus_grammar": ["条件句"],
  "question_type": "inference",
  "avoid_topics": []
}

【输出】(严格 JSON,无多余文字、无 markdown 代码块)
{
  "passage": "一段日语短文,约150-250字,长度与难度贴合 target",
  "passage_char_count": 187,
  "question": "针对短文的理解类问题(日语)",
  "options": ["A","B","C","D"],
  "answer_index": 0,
  "question_type": "inference",
  "self_assessed_jlpt": "N3",
  "self_assessed_level": 6,
  "tested_grammar": ["条件句","受身"]
}

【要求】
- 4 选 1,干扰项有迷惑性,不送分。
- detail 考定位/理解明示信息;inference 考推断主旨、意图、言外之意。
- 答案不能照抄原文某句,须经理解才能选。
- self_assessed_* 必须诚实——后端会用难度引擎独立复核。
- passage_char_count 要准确。
- 只输出 JSON。
"""

DIAGNOSIS_MASTER_SYSTEM = """\
你是日语阅读测评系统的「诊断官」。根据作答历史,估计用户阅读能力的多个维度,给出下一题难度和学习建议。

【关键原则】history 里每题的难度都是「难度引擎实测值」,不是 AI 自评。用户能力一律相对这个实测难度校准。

【输入】(JSON)
{
  "history": [
    { "measured_jlpt":"N2", "measured_level":7, "correct":true,
      "elapsed_ms":42000, "char_count":187,
      "question_type":"inference", "tested_grammar":["条件句"] }
  ],
  "metrics": { "accuracy": 0.78, "avg_wpm": 420, "answered": 6 }
}

【输出】(严格 JSON)
{
  "ability_jlpt": "N2",
  "ability_level": 7,
  "confidence": "low|medium|high",
  "weak_areas": ["条件句","长定语修饰"],
  "reader_type": "准但慢",
  "deep_comprehension": "推断题失分多于细节题",
  "advice": "一句具体可执行的建议,必须同时挂在 weak_areas 和 reader_type 上。",
  "next_target_jlpt": "N2",
  "next_target_level": 8,
  "converged": false
}

【规则】
- 相对 measured_level 校准:答对→上调,答错→下调,向真实天花板收敛。
- confidence 随作答数上升;同档连续稳定且已答≥5题时可置 converged=true。
- reader_type 必须综合 accuracy 与 avg_wpm,不能只看一个。
  参考基准:avg_wpm≥500 为快,≤300 为慢;accuracy≥0.75 为准,<0.5 为不稳。
- advice 禁止套话(「多读多练」「加强练习」判为不合格),须落到具体语法点+阅读行为。
- 只输出 JSON。
"""

# ── Internal helpers ──────────────────────────────────────────────────────────


def _strip_fence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n?\s*```\s*$", "", text)
    return text.strip()


async def _call_gemini(system: str, user_msg: str) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set")

    url = f"{_BASE_URL}/{GEMINI_MODEL}:generateContent"
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_msg}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.7,
        },
    }
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": GEMINI_API_KEY,
    }
    async with httpx.AsyncClient(verify=_SSL_VERIFY, timeout=45.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


async def _call_with_retry(system: str, user_msg: str) -> dict:
    last_err: Exception | None = None
    for _ in range(3):
        try:
            raw = await _call_gemini(system, user_msg)
            return json.loads(_strip_fence(raw))
        except Exception as e:
            last_err = e
    raise last_err  # type: ignore[misc]


# ── Public agent functions ────────────────────────────────────────────────────

_LEVEL_TO_JLPT = {
    1: "N5", 2: "N5", 3: "N4", 4: "N4",
    5: "N3", 6: "N3", 7: "N2", 8: "N2",
    9: "N1", 10: "N1",
}


async def ask_question_master(
    target_level: int,
    question_type: str,
    focus_grammar: list[str] | None = None,
    avoid_topics: list[str] | None = None,
) -> dict:
    req = {
        "target_jlpt": _LEVEL_TO_JLPT.get(target_level, "N3"),
        "target_level": target_level,
        "focus_grammar": focus_grammar or [],
        "question_type": question_type,
        "avoid_topics": avoid_topics or [],
    }
    return await _call_with_retry(
        QUESTION_MASTER_SYSTEM, json.dumps(req, ensure_ascii=False)
    )


async def ask_diagnosis_master(history: list, metrics: dict) -> dict:
    req = {"history": history, "metrics": metrics}
    return await _call_with_retry(
        DIAGNOSIS_MASTER_SYSTEM, json.dumps(req, ensure_ascii=False)
    )


async def parse_user_level(user_input: str) -> tuple[int, str]:
    """
    Parse start level and language from natural language.
    Uses simple heuristics first; falls back to level 5 / ja.
    """
    text = user_input.upper()
    for tag, level in [("N1", 9), ("N2", 7), ("N3", 5), ("N4", 3), ("N5", 1)]:
        if tag in text:
            return level, "ja"
    lower = user_input.lower()
    if any(w in lower for w in ["初级", "初めて", "初心者", "beginner", "零基础"]):
        return 2, "ja"
    if any(w in lower for w in ["上级", "上級", "advanced", "高级"]):
        return 8, "ja"
    if any(w in lower for w in ["中级", "中級", "intermediate"]):
        return 5, "ja"
    return 5, "ja"
