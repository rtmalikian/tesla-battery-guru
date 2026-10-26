"""OpenAI response shapes + battery Q&A rules. The rules engine must
answer health questions with computed stats, never invented numbers."""
from tesla_battery_guru.config import load_settings
from tesla_battery_guru.service import BatteryGuruService
from tesla_battery_guru.simulator import run_demo_month


def _service(sessions=None):
    settings = load_settings({"TBG_VEHICLES": "Model Y=VINY",
                              "TBG_AI_MODE": "never"})
    if sessions is None:
        sessions = run_demo_month(settings)
    return BatteryGuruService(settings, sessions_provider=lambda: sessions)


def _ask(service, question):
    resp = service.chat_completions(
        {"model": "tesla-battery-guru",
         "messages": [{"role": "user", "content": question}]})
    assert resp["object"] == "chat.completion"
    assert resp["model"] == "tesla-battery-guru"
    assert resp["choices"][0]["message"]["role"] == "assistant"
    assert resp["choices"][0]["finish_reason"] == "stop"
    return resp["choices"][0]["message"]["content"]


def test_models_shape():
    models = _service().models_list()
    assert models["object"] == "list"
    assert models["data"][0]["id"] == "tesla-battery-guru"


def test_degradation_answer_matches_session_math():
    service = _service()
    answer = _ask(service, "how degraded is my battery?")
    assert "70.0 kWh" in answer
    assert "6.7%" in answer


def test_care_score_and_alerts_answers():
    service = _service()
    score = _ask(service, "what's my care score?")
    assert "care score" in score
    alerts = _ask(service, "any alerts?")
    assert "charged to 100%" in alerts
    assert "3 days running" in alerts


def test_per_car_filter():
    service = _service()
    answer = _ask(service, "how degraded is the Model Y battery?")
    assert "Model Y" in answer


def test_report_answer():
    service = _service()
    answer = _ask(service, "give me my battery report")
    assert "70.0 kWh" in answer and "care score" in answer


def test_unknown_question_falls_back_to_capability_blurb():
    answer = _ask(_service(), "tell me a joke about Mars")
    assert "battery health" in answer


def test_embeddings_shape():
    service = _service()
    resp = service.embeddings({"model": "tesla-battery-guru",
                               "input": ["charge session", "supercharger"]})
    assert resp["object"] == "list"
    assert len(resp["data"]) == 2
    assert len(resp["data"][0]["embedding"]) == 384
    assert resp["data"][0]["object"] == "embedding"
    # Deterministic: same text -> same vector.
    again = service.embeddings({"model": "tesla-battery-guru",
                                "input": "charge session"})
    assert again["data"][0]["embedding"] == resp["data"][0]["embedding"]


def test_empty_sessions_falls_back_gracefully():
    service = _service(sessions=[])
    answer = _ask(service, "how degraded is my battery?")
    assert "battery health" in answer
