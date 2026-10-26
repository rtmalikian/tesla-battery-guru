"""Battery estimation, care score, streak alerts, validation, and CSV export."""
from datetime import datetime, timedelta, timezone

import pytest

from tesla_battery_guru.battery import (BatteryError, ChargeSession,
                                        detect_streak_alerts, estimate_health,
                                        export_csv, health_report, score_care)


def _s(day, start_soc, end_soc, kwh, loc="home", dwell=0.0, car="Model Y"):
    start = datetime(2026, 9, day, 22, 0, tzinfo=timezone.utc)
    return ChargeSession(car, start, start + timedelta(hours=6),
                         start_soc, end_soc, kwh, loc, "", dwell)


def test_implied_pack_math():
    s = _s(3, 30, 80, 35.0)
    assert s.implied_pack_kwh() == pytest.approx(70.0)


def test_small_swing_ignored():
    assert _s(3, 65, 72, 5.0).implied_pack_kwh() is None
    assert _s(3, 30, 49, 13.0).implied_pack_kwh() is None  # 19-point swing
    assert _s(3, 30, 50, 14.0).implied_pack_kwh() == pytest.approx(70.0)


def test_median_estimate_beats_outlier():
    sessions = [_s(3, 20, 80, 42.0), _s(4, 30, 80, 35.0),
                _s(5, 10, 70, 90.0)]  # implies 150 — a bad read
    est = estimate_health(sessions, 75.0)[0]
    assert est.estimated_pack_kwh == pytest.approx(70.0)
    assert est.degradation_pct == pytest.approx(6.666, abs=0.01)
    assert est.sessions_used == 3


def test_no_usable_sessions_reports_plainly():
    est = estimate_health([_s(3, 65, 72, 5.0)], 75.0)[0]
    assert est.estimated_pack_kwh is None
    assert est.degradation_pct is None
    assert "not enough" in est.summary_line()


def test_per_car_estimates_stay_separate():
    sessions = [_s(3, 20, 80, 42.0, car="Model Y"),
                _s(4, 20, 80, 48.0, car="Model 3")]
    ests = {e.vehicle: e for e in estimate_health(sessions, 75.0)}
    assert ests["Model Y"].estimated_pack_kwh == pytest.approx(70.0)
    assert ests["Model 3"].estimated_pack_kwh == pytest.approx(80.0)


def test_care_score_penalties_and_caps():
    sessions = [_s(3, 45, 100, 38.5, dwell=8.0), _s(4, 50, 100, 35.0, dwell=8.0),
                _s(5, 8, 70, 43.4), _s(6, 40, 90, 35.0, loc="supercharger")]
    score = score_care(sessions)[0]
    # dwell 16h -> -30 (capped from 32); SC share 1/4 -> -5; deep 1 -> -5;
    # days over 80%: Sep 3,4,6 -> -6
    assert score.score == 100 - 30 - 5 - 5 - 6
    assert score.penalties["sitting at 100%"] == 30


def test_perfect_habits_score_100():
    score = score_care([_s(3, 30, 80, 35.0)])[0]
    assert score.score == 100


def test_streak_alert_needs_three_consecutive_days():
    two_days = [_s(10, 45, 100, 38.5, dwell=8.0), _s(11, 50, 100, 35.0, dwell=8.0)]
    assert detect_streak_alerts(two_days) == []
    three_days = two_days + [_s(12, 40, 100, 42.0, dwell=8.0)]
    alerts = detect_streak_alerts(three_days)
    assert len(alerts) == 1
    assert "charged to 100%" in alerts[0] and "3 days running" in alerts[0]


def test_streak_broken_by_gap_day():
    sessions = [_s(10, 45, 100, 38.5, dwell=8.0), _s(12, 50, 100, 35.0, dwell=8.0),
                _s(13, 40, 100, 42.0, dwell=8.0)]
    assert detect_streak_alerts(sessions) == []


def test_deep_discharge_and_supercharger_streaks():
    deep = [_s(1, 8, 70, 43.4), _s(2, 9, 70, 42.7), _s(3, 10, 70, 42.0)]
    alerts = detect_streak_alerts(deep)
    assert any("deep discharge" in a for a in alerts)
    sc_only = [_s(1, 20, 80, 42.0, loc="supercharger"),
               _s(2, 30, 80, 35.0, loc="supercharger"),
               _s(3, 25, 80, 38.5, loc="supercharger")]
    alerts = detect_streak_alerts(sc_only)
    assert any("Supercharger-only day" in a for a in alerts)


def test_validation_rejects_bad_sessions():
    with pytest.raises(BatteryError):
        _s(3, 80, 30, 10.0).validate()  # battery fell while "charging"
    with pytest.raises(BatteryError):
        _s(3, 30, 101, 10.0).validate()
    with pytest.raises(BatteryError):
        _s(3, 30, 80, -5.0).validate()
    with pytest.raises(BatteryError):
        _s(3, 30, 80, 35.0, dwell=-1.0).validate()
    with pytest.raises(BatteryError):
        _s(3, 30, 80, 35.0, loc="driveway").validate()


def test_health_report_contains_all_sections(tmp_path):
    sessions = [_s(3, 30, 80, 35.0), _s(4, 20, 80, 42.0)]
    report = health_report(sessions, 75.0)
    assert "70.0 kWh" in report and "care score" in report and "Alerts:" in report


def test_csv_export_round_trip(tmp_path):
    sessions = [_s(3, 30, 80, 35.0), _s(4, 65, 72, 5.0)]
    out = tmp_path / "sessions.csv"
    assert export_csv(sessions, str(out)) == 2
    lines = out.read_text().splitlines()
    assert lines[0].startswith("date,car,location")
    assert "70.0" in lines[1]
    assert lines[2].split(",")[6] == ""  # top-up: no implied pack
