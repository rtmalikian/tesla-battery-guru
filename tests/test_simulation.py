"""End-to-end: the demo month's median implied pack is 70.0 kWh,
degradation is 6.7%, the 100% streak alert fires, and the HTTP server
answers a health question live."""
import threading
from http.server import ThreadingHTTPServer

import requests

from tesla_battery_guru.battery import estimate_health
from tesla_battery_guru.config import load_settings
from tesla_battery_guru.server import make_handler
from tesla_battery_guru.service import BatteryGuruService
from tesla_battery_guru.simulator import run_demo_month, timeline_lines


def _settings():
    return load_settings({"TBG_VEHICLES": "Model Y=VINY",
                          "TBG_AI_MODE": "never"})


def test_demo_month_estimate_is_70kwh_and_degradation_6_7():
    sessions = run_demo_month(_settings())
    assert len(sessions) == 9
    est = estimate_health(sessions, 75.0)[0]
    assert est.estimated_pack_kwh == 70.0
    assert abs(est.degradation_pct - 6.666) < 0.01
    assert est.sessions_used == 8  # the Sep 30 top-up is ignored


def test_demo_month_streak_alert_fires_in_timeline():
    lines = timeline_lines(_settings())
    text = "\n".join(lines)
    assert "70.0 kWh" in text
    assert "6.7%" in text
    assert "charged to 100%" in text
    assert "3 days running" in text
    assert "Sep 30" in text
    assert "too small to estimate" in text


def test_http_server_answers_health_question():
    settings = _settings()
    sessions = run_demo_month(settings)
    service = BatteryGuruService(settings, sessions_provider=lambda: sessions)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        models = requests.get(f"http://127.0.0.1:{port}/v1/models", timeout=5)
        assert models.status_code == 200
        assert models.json()["data"][0]["id"] == "tesla-battery-guru"
        resp = requests.post(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            json={"model": "tesla-battery-guru",
                  "messages": [{"role": "user",
                                "content": "how degraded is my battery?"}]},
            timeout=5)
        assert resp.status_code == 200
        content = resp.json()["choices"][0]["message"]["content"]
        assert "70.0 kWh" in content
        assert "6.7%" in content
        emb = requests.post(
            f"http://127.0.0.1:{port}/v1/embeddings",
            json={"model": "tesla-battery-guru", "input": "charge session"},
            timeout=5)
        assert emb.status_code == 200
        assert len(emb.json()["data"][0]["embedding"]) == 384
    finally:
        httpd.shutdown()
        httpd.server_close()
