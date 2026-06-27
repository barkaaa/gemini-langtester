"""
FastAPI orchestration layer for the Japanese reading adaptive assessment tool.

Endpoints:
  POST /start   { user_input }  → { session_id, question, difficulty }
  POST /answer  { session_id, answer_index, elapsed_ms }
                                → { correct, diagnosis, done, [next_question, difficulty] }

Highest-priority invariant: every difficulty value written to history comes
from the local Pipeline (measured), NEVER from the LLM self-assessment.
"""

import uuid
import os
import random
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from agents import ask_diagnosis_master, ask_question_master, parse_user_level
from scoring.pipeline import Pipeline
from scoring.schemas import AnalyzeRequest

# ── Init ──────────────────────────────────────────────────────────────────────

_pipeline = Pipeline()
_sessions: dict[str, dict] = {}

MAX_QUESTIONS = 8
MIN_TO_CONVERGE = 5
CALIBRATION_ATTEMPTS = max(1, int(os.environ.get("CALIBRATION_ATTEMPTS", "1")))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm up the pipeline (no-op but documents intent)
    _pipeline.analyze(AnalyzeRequest(text="テスト"))
    yield


app = FastAPI(title="Japanese Reading Assessor", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Difficulty engine wrapper ─────────────────────────────────────────────────


def measure_difficulty(text: str) -> dict:
    """
    Call the local Pipeline.  On any error, degrade gracefully.
    Returns: { level, jlpt, confidence, degraded }
    """
    try:
        resp = _pipeline.analyze(AnalyzeRequest(text=text))
        return {
            "level": resp.level,
            "jlpt": resp.band,
            "confidence": resp.confidence,
            "degraded": False,
        }
    except Exception as exc:
        return {
            "level": 5,
            "jlpt": "N3",
            "confidence": "low",
            "degraded": True,
            "error": str(exc),
        }


# ── Question generation with calibration loop ─────────────────────────────────

_TYPE_CYCLE = ["detail", "inference"]


async def _generate_calibrated(
    target_level: int,
    question_type: str,
    avoid_topics: list[str] | None = None,
) -> dict:
    """
    Generate a question and verify its measured difficulty is within tolerance
    of target_level. Retries are intentionally low for local responsiveness.
    Always returns a question (marked approx=True if calibration never converged).
    """
    tolerance = 1
    best: dict | None = None
    last_error: Exception | None = None

    for attempt in range(CALIBRATION_ATTEMPTS):
        try:
            q = await ask_question_master(
                target_level, question_type, avoid_topics=avoid_topics
            )
            passage = q.get("passage", "")
            m = measure_difficulty(passage)

            q["measured_level"] = m["level"]
            q["measured_jlpt"] = m["jlpt"]
            q["measured_confidence"] = m["confidence"]
            q["degraded"] = m.get("degraded", False)

            # Actual char count from passage (override self-reported if wrong)
            q["passage_char_count"] = len(passage)

            if abs(m["level"] - target_level) <= tolerance:
                q["approx"] = False
                return _shuffle_options(q)

            best = q
            tolerance += 1

        except Exception as exc:
            last_error = exc

    if best:
        best["approx"] = True
        return _shuffle_options(best)

    detail = f"Failed to generate question after {CALIBRATION_ATTEMPTS} attempts"
    if last_error:
        detail = f"{detail}: {last_error}"
    raise HTTPException(status_code=503, detail=detail)


# ── Session helpers ───────────────────────────────────────────────────────────


def _compute_metrics(history: list) -> dict:
    total = len(history)
    if total == 0:
        return {"accuracy": 0.0, "avg_wpm": 0.0, "answered": 0}
    correct_n = sum(1 for h in history if h["correct"])
    total_chars = sum(h["char_count"] for h in history)
    total_ms = sum(h["elapsed_ms"] for h in history)
    avg_wpm = (total_chars / (total_ms / 60_000)) if total_ms > 0 else 0.0
    return {
        "accuracy": round(correct_n / total, 3),
        "avg_wpm": round(avg_wpm, 1),
        "answered": total,
    }


def _level_to_jlpt(level: int) -> str:
    if level <= 2:
        return "N5"
    if level <= 4:
        return "N4"
    if level <= 6:
        return "N3"
    if level <= 8:
        return "N2"
    return "N1"


def _interim_diagnosis(history: list, metrics: dict, current_level: int) -> dict:
    recent = history[-3:]
    recent_accuracy = (
        sum(1 for h in recent if h["correct"]) / len(recent)
        if recent else metrics["accuracy"]
    )
    next_level = current_level
    if recent_accuracy >= 0.8:
        next_level += 1
    elif recent_accuracy <= 0.35:
        next_level -= 1
    next_level = max(1, min(10, next_level))

    converged = False
    if len(history) >= MIN_TO_CONVERGE:
        levels = [h["measured_level"] for h in history[-3:]]
        converged = max(levels) - min(levels) <= 1 and 0.45 <= recent_accuracy <= 0.85

    return {
        "ability_jlpt": _level_to_jlpt(current_level),
        "ability_level": current_level,
        "confidence": "medium" if len(history) >= 3 else "low",
        "weak_areas": [],
        "reader_type": "calibrating",
        "deep_comprehension": "",
        "advice": "",
        "next_target_jlpt": _level_to_jlpt(next_level),
        "next_target_level": next_level,
        "converged": converged,
    }


def _shuffle_options(q: dict) -> dict:
    options = q.get("options", [])
    answer_index = q.get("answer_index", 0)
    if not isinstance(options, list) or len(options) != 4:
        raise ValueError("Question must contain exactly 4 options")
    if not isinstance(answer_index, int) or not 0 <= answer_index < len(options):
        raise ValueError("Question answer_index is out of range")

    indexed = list(enumerate(options))
    random.shuffle(indexed)
    q["options"] = [option for _, option in indexed]
    q["answer_index"] = next(
        new_index for new_index, (old_index, _) in enumerate(indexed)
        if old_index == answer_index
    )
    return q


def _pending_from_question(q: dict) -> dict:
    answer_index = q["answer_index"]
    options = q.get("options", [])
    return {
        "answer_index": answer_index,
        "correct_answer": options[answer_index] if 0 <= answer_index < len(options) else "",
        "measured_level": q.get("measured_level", 5),
        "measured_jlpt": q.get("measured_jlpt", "N3"),
        "char_count": q.get("passage_char_count", len(q.get("passage", ""))),
        "question_type": q.get("question_type", "detail"),
        "tested_grammar": q.get("tested_grammar", []),
        "approx": q.get("approx", False),
    }


def _difficulty_envelope(q: dict, target_level: int) -> dict:
    return {
        "self_jlpt": q.get("self_assessed_jlpt", "N3"),
        "self_level": q.get("self_assessed_level", target_level),
        "measured_jlpt": q.get("measured_jlpt", "N3"),
        "measured_level": q.get("measured_level", target_level),
        "approx": q.get("approx", False),
        "degraded": q.get("degraded", False),
    }


def _public_question(q: dict) -> dict:
    return {
        "passage": q["passage"],
        "question": q["question"],
        "options": q["options"],
    }


# ── Routes ────────────────────────────────────────────────────────────────────


class StartBody:
    pass  # FastAPI parses raw dicts; using dict typing below


from pydantic import BaseModel


class StartRequest(BaseModel):
    user_input: str


class AnswerRequest(BaseModel):
    session_id: str
    answer_index: int
    elapsed_ms: int = 0


@app.post("/start")
async def start(body: StartRequest):
    start_level, language = await parse_user_level(body.user_input)

    q = await _generate_calibrated(start_level, "detail")

    session_id = str(uuid.uuid4())
    _sessions[session_id] = {
        "id": session_id,
        "language": language,
        "current_target_level": start_level,
        "history": [],
        "next_type_idx": 1,  # next question will be "inference"
        "pending": _pending_from_question(q),
    }

    return {
        "session_id": session_id,
        "question": _public_question(q),
        "difficulty": _difficulty_envelope(q, start_level),
    }


@app.post("/answer")
async def answer(body: AnswerRequest):
    session = _sessions.get(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    pending = session["pending"]

    # ── 1. Deterministic judgement — NO LLM ──────────────────────────────────
    correct = body.answer_index == pending["answer_index"]
    answer_feedback = {
        "correct": correct,
        "correct_answer_index": pending["answer_index"],
        "correct_answer": pending.get("correct_answer", ""),
        "elapsed_ms": body.elapsed_ms,
    }

    # ── 2. Record history with MEASURED difficulty ────────────────────────────
    entry = {
        "measured_level": pending["measured_level"],    # ← always engine value
        "measured_jlpt": pending["measured_jlpt"],
        "correct": correct,
        "elapsed_ms": body.elapsed_ms,
        "char_count": pending["char_count"],
        "question_type": pending["question_type"],
        "tested_grammar": pending["tested_grammar"],
    }
    session["history"].append(entry)

    # ── 3. Deterministic metrics ──────────────────────────────────────────────
    metrics = _compute_metrics(session["history"])

    # ── 4. Fast local diagnosis for responsiveness ────────────────────────────
    answered = metrics["answered"]
    diagnosis = _interim_diagnosis(
        session["history"], metrics, session["current_target_level"]
    )
    converged = bool(diagnosis.get("converged", False))
    done = answered >= MIN_TO_CONVERGE and (converged or answered >= MAX_QUESTIONS)

    if done:
        diagnosis = await ask_diagnosis_master(session["history"], metrics)
        return {**answer_feedback, "diagnosis": diagnosis, "done": True}

    # ── 5. Next question ──────────────────────────────────────────────────────
    next_level = int(diagnosis.get("next_target_level", session["current_target_level"]))
    next_level = max(1, min(10, next_level))
    session["current_target_level"] = next_level

    next_type = _TYPE_CYCLE[session["next_type_idx"] % 2]
    session["next_type_idx"] += 1

    nq = await _generate_calibrated(next_level, next_type)
    session["pending"] = _pending_from_question(nq)

    return {
        **answer_feedback,
        "diagnosis": diagnosis,
        "done": False,
        "next_question": _public_question(nq),
        "difficulty": _difficulty_envelope(nq, next_level),
    }


# ── Frontend static files (must come last) ────────────────────────────────────

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
