"""
LLM agent callers for 出題官 (question master) and 診断官 (diagnosis master).
All calls go to the Gemini API; JSON output is enforced via responseMimeType.
"""

import json
import os
import re
import ssl
import asyncio

import httpx
from dotenv import load_dotenv

load_dotenv()

GEMINI_PROVIDER = os.environ.get("GEMINI_PROVIDER", "google_ai").lower()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
GOOGLE_CLOUD_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "asia-northeast1")
_GOOGLE_AI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

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

# Override the legacy garbled prompts with short, explicit instructions.
QUESTION_MASTER_SYSTEM = """\
You generate Japanese reading-comprehension questions for JLPT-style adaptive testing.
Return strict JSON only. No markdown, no comments.

Input JSON:
{
  "target_jlpt": "N3",
  "target_level": 5,
  "focus_grammar": [],
  "question_type": "detail|inference",
  "avoid_topics": []
}

Output JSON schema:
{
  "passage": "Japanese passage, 140-240 Japanese characters",
  "passage_char_count": 180,
  "question": "Japanese question",
  "options": ["option A", "option B", "option C", "option D"],
  "answer_index": "integer 0-3",
  "question_type": "detail|inference",
  "self_assessed_jlpt": "N5|N4|N3|N2|N1",
  "self_assessed_level": 1,
  "tested_grammar": ["grammar point"]
}

Rules:
- Match target_level: 1-2=N5, 3-4=N4, 5-6=N3, 7-8=N2, 9-10=N1.
- detail questions test explicit facts. inference questions test implication, intent, or conclusion.
- Exactly one correct option. Distractors must be plausible but clearly wrong from the passage.
- Vary answer_index naturally across 0, 1, 2, and 3. Do not always make option A correct.
- The correct option must not copy a sentence or phrase directly from the passage.
- All options, especially the correct answer, must paraphrase the passage in different wording while preserving meaning.
- Avoid romaji. Keep all user-facing question content in Japanese.
- Use ordinary, non-sensitive topics such as school, work, travel, public notices, habits, technology, or culture.
"""

DIAGNOSIS_MASTER_SYSTEM = """\
You diagnose Japanese reading ability from adaptive test history.
Return strict JSON only. No markdown, no comments.

Input JSON:
{
  "history": [
    {
      "measured_jlpt": "N3",
      "measured_level": 5,
      "correct": true,
      "elapsed_ms": 30000,
      "char_count": 180,
      "question_type": "detail",
      "tested_grammar": []
    }
  ],
  "metrics": { "accuracy": 0.75, "avg_wpm": 360, "answered": 8 }
}

Output JSON schema:
{
  "ability_jlpt": "N5|N4|N3|N2|N1",
  "ability_level": 1,
  "confidence": "low|medium|high",
  "weak_areas": ["specific reading or grammar weakness"],
  "reader_type": "short label",
  "deep_comprehension": "one concise diagnosis sentence",
  "advice": "one concise actionable study recommendation",
  "next_target_jlpt": "N5|N4|N3|N2|N1",
  "next_target_level": 1,
  "converged": true
}

Rules:
- Trust measured_level, not the model's self assessment.
- Use accuracy, speed, question type, and tested grammar to estimate ability.
- Be concrete and useful. Keep Japanese-learning advice concise.
"""

# ── Internal helpers ──────────────────────────────────────────────────────────


def _strip_fence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n?\s*```\s*$", "", text)
    return text.strip()


def _build_payload(system: str, user_msg: str, *, vertex: bool) -> dict:
    system_key = "systemInstruction" if vertex else "system_instruction"
    return {
        system_key: {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user_msg}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.7,
            "maxOutputTokens": 4096,
        },
    }


async def _get_vertex_access_token() -> str:
    def load_token() -> str:
        import google.auth
        from google.auth.transport.requests import Request

        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(Request())
        return credentials.token

    token = await asyncio.to_thread(load_token)
    if not token:
        raise RuntimeError("Could not obtain Google Cloud access token")
    return token


async def _post_json(url: str, payload: dict, headers: dict) -> dict:
    async with httpx.AsyncClient(verify=_SSL_VERIFY, timeout=45.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = resp.text[:500].replace("\n", " ")
            raise RuntimeError(
                f"Gemini API returned HTTP {resp.status_code}: {detail}"
            ) from exc
        return resp.json()


async def _call_google_ai(system: str, user_msg: str) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set")

    url = f"{_GOOGLE_AI_BASE_URL}/{GEMINI_MODEL}:generateContent"
    payload = _build_payload(system, user_msg, vertex=False)
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": GEMINI_API_KEY,
    }
    data = await _post_json(url, payload, headers)
    return _extract_text(data)


async def _call_vertex_ai(system: str, user_msg: str) -> str:
    if not GOOGLE_CLOUD_PROJECT:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT environment variable is not set")

    if GOOGLE_CLOUD_LOCATION == "global":
        base_url = "https://aiplatform.googleapis.com/v1"
    else:
        base_url = f"https://{GOOGLE_CLOUD_LOCATION}-aiplatform.googleapis.com/v1"
    url = (
        f"{base_url}/projects/{GOOGLE_CLOUD_PROJECT}/"
        f"locations/{GOOGLE_CLOUD_LOCATION}/publishers/google/models/"
        f"{GEMINI_MODEL}:generateContent"
    )
    payload = _build_payload(system, user_msg, vertex=True)
    token = await _get_vertex_access_token()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    data = await _post_json(url, payload, headers)
    return _extract_text(data)


def _extract_text(data: dict) -> str:
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        brief = json.dumps(data, ensure_ascii=False)[:800]
        raise RuntimeError(f"Gemini API returned no text parts: {brief}") from exc


async def _call_gemini(system: str, user_msg: str) -> str:
    if GEMINI_PROVIDER in {"vertex", "vertex_ai", "google_cloud"}:
        return await _call_vertex_ai(system, user_msg)
    if GEMINI_PROVIDER in {"google_ai", "ai_studio", "api_key"}:
        return await _call_google_ai(system, user_msg)
    raise RuntimeError(
        "GEMINI_PROVIDER must be one of: google_ai, ai_studio, vertex, vertex_ai"
    )


async def _call_with_retry(system: str, user_msg: str) -> dict:
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            raw = await _call_gemini(system, user_msg)
            return json.loads(_strip_fence(raw))
        except Exception as e:
            last_err = e
            if attempt < 2:
                await asyncio.sleep(1.5 * (attempt + 1))
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
