"""Transport-independent service: takes OpenAI-shaped request dicts,
returns OpenAI-shaped response dicts. The HTTP server (server.py) is a
thin wrapper; tests drive this class directly.

Flow for a user message:
  1. Rules engine answers battery-health questions from the computed
     stats (no AI needed — "how degraded is my battery?").
  2. If rules don't match and ai_mode is auto|always → LLM backend with
     the health brief as context. The model explains; it never invents
     a degradation number — stats come from the session math.
  3. ai_mode=never (or LLM failure) → capability-list answer.
"""
from __future__ import annotations

import itertools
import time

from .battery import (battery_brief, detect_streak_alerts, estimate_health,
                      health_report, score_care)
from .embeddings import embed_text
from .llm import LlmBackend

CAPABILITY_BLURB = (
    "I track your Tesla's battery health: usable-pack estimate and "
    "degradation from your charge sessions, a habit-based care score, "
    "and alerts when a harmful pattern repeats 3 days running. "
    "Try: \"how degraded is my battery?\", \"what's my care score?\" or "
    "\"any alerts?\" "
    "Connect an LLM backend (TBG_AI_BASE_URL) and I can coach you in "
    "free-form words too. I never control a car — I only read and "
    "score charging."
)


class BatteryGuruService:
    def __init__(self, settings, sessions_provider=None, llm_factory=None):
        self.settings = settings
        self.sessions_provider = sessions_provider or (lambda: [])
        self.llm_factory = llm_factory
        self._ids = itertools.count(1)

    # -- plumbing ------------------------------------------------------
    def _llm(self):
        if self.llm_factory is not None:
            return self.llm_factory()
        if self.settings.ai_mode == "never":
            return None
        if not self.settings.ai_base_url:
            return None
        return LlmBackend(self.settings.ai_base_url, self.settings.ai_api_key,
                          self.settings.ai_model, self.settings.ai_timeout_seconds)

    def _next_id(self, prefix: str) -> str:
        return f"{prefix}-{int(time.time())}-{next(self._ids)}"

    # -- OpenAI surface ------------------------------------------------
    def models_list(self) -> dict:
        return {"object": "list", "data": [{
            "id": self.settings.model_id,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "tesla-battery-guru",
        }]}

    def chat_completions(self, body: dict) -> dict:
        messages = body.get("messages") or []
        user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_text = str(m.get("content") or "")
                break
        sessions = self.sessions_provider()
        text = self._rules_answer(user_text, sessions)
        if text is None:
            text = self._llm_answer(user_text, sessions)
        return {
            "id": self._next_id("chatcmpl"),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.settings.model_id,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    def embeddings(self, body: dict) -> dict:
        raw = body.get("input", "")
        texts = raw if isinstance(raw, list) else [raw]
        data = []
        for i, t in enumerate(texts):
            data.append({
                "object": "embedding",
                "index": i,
                "embedding": embed_text(str(t), self.settings.embedding_dim),
            })
        return {
            "object": "list",
            "data": data,
            "model": self.settings.model_id,
            "usage": {"prompt_tokens": 0, "total_tokens": 0},
        }

    # -- internals -----------------------------------------------------
    def _rules_answer(self, user_text: str, sessions: list) -> str | None:
        q = user_text.lower()
        if not sessions:
            return None
        car_sessions = sessions
        for name in {s.vehicle for s in sessions}:
            if name.lower() in q:
                car_sessions = [s for s in sessions if s.vehicle == name]
                break
        nominal = self.settings.nominal_pack_kwh
        limit = self.settings.daily_limit_pct
        if "degrad" in q or "capacity" in q or "pack" in q or "health" in q:
            ests = estimate_health(car_sessions, nominal)
            return "\n".join(e.summary_line() for e in ests)
        if "care score" in q or "score" in q or "habit" in q:
            scores = score_care(car_sessions, limit)
            return "\n".join(s.summary_line() for s in scores)
        if "alert" in q or "streak" in q or "warning" in q:
            alerts = detect_streak_alerts(car_sessions)
            if not alerts:
                return "No alerts — no harmful pattern repeated 3 days running."
            return "\n".join(alerts)
        if "report" in q or "summary" in q or "how is" in q or "how's" in q:
            return health_report(car_sessions, nominal, limit)
        if "supercharger" in q and "share" in q:
            sc = sum(1 for s in car_sessions if s.location_class == "supercharger")
            return (f"{sc} of {len(car_sessions)} sessions at Superchargers "
                    f"({sc / len(car_sessions) * 100:.0f}%).")
        return None

    def _llm_answer(self, user_text: str, sessions: list) -> str:
        llm = self._llm()
        if llm is None:
            return CAPABILITY_BLURB
        try:
            return llm.chat(battery_brief(sessions,
                                         self.settings.nominal_pack_kwh,
                                         self.settings.daily_limit_pct),
                            user_text)
        except Exception:
            return CAPABILITY_BLURB + " (The AI backend didn't respond just now.)"
