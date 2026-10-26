"""Simulated charging month for tests, demos, and the GitHub Pages POC.
No API calls, no real cars. One pretend Model Y, nominal pack 75 kWh,
September 2026. Every big session implies a 70.0 kWh usable pack, so
the month's estimate is 70.0 kWh and degradation is 6.7%:

- Sep 3:  home, 30% → 80%, 35.0 kWh (implies 70.0)
- Sep 7:  home, 20% → 80%, 42.0 kWh (implies 70.0)
- Sep 10–12: home, charged to 100% and left sitting 8 hours each day
  (the 3-day streak the alert rule catches)
- Sep 18: home, deep discharge start at 8% → 70%, 43.4 kWh (implies 70.0)
- Sep 22: Supercharger, 40% → 90%, 35.0 kWh (implies 70.0)
- Sep 27: home, 40% → 90%, 35.0 kWh (implies 70.0)
- Sep 30: tiny top-up, 65% → 72% — ignored by the estimator (swing < 20)

Core invariant the e2e test asserts: the median implied pack is
70.0 kWh, degradation is 6.7%, and the 100% streak alert fires.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .battery import ChargeSession, health_report

DEMO_MONTH = "2026-09"
DEMO_NOMINAL_PACK_KWH = 75.0


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=timezone.utc)


def demo_sessions_raw() -> list[ChargeSession]:
    car = "Model Y"
    return [
        ChargeSession(car, _at(3, 23), _at(4, 6), 30, 80, 35.0,
                      "home", "Home"),
        ChargeSession(car, _at(7, 15), _at(7, 19), 20, 80, 42.0,
                      "home", "Home"),
        ChargeSession(car, _at(10, 21), _at(11, 5), 45, 100, 38.5,
                      "home", "Home", dwell_hours=8.0),
        ChargeSession(car, _at(11, 21), _at(12, 5), 50, 100, 35.0,
                      "home", "Home", dwell_hours=8.0),
        ChargeSession(car, _at(12, 21), _at(13, 5), 40, 100, 42.0,
                      "home", "Home", dwell_hours=8.0),
        ChargeSession(car, _at(18, 1), _at(18, 5), 8, 70, 43.4,
                      "home", "Home"),
        ChargeSession(car, _at(22, 10), _at(22, 11), 40, 90, 35.0,
                      "supercharger", "Tejon Ranch Supercharger"),
        ChargeSession(car, _at(27, 17), _at(27, 20), 40, 90, 35.0,
                      "home", "Home"),
        ChargeSession(car, _at(30, 22),
                      datetime(2026, 10, 1, 2, 0, tzinfo=timezone.utc),
                      65, 72, 5.0, "home", "Home"),
    ]


def run_demo_month(settings) -> list[ChargeSession]:
    """Demo sessions need no pricing — returns them as-is."""
    return demo_sessions_raw()


def timeline_lines(settings) -> list[str]:
    """Human-readable demo timeline for `tbguru simulate`."""
    sessions = run_demo_month(settings)
    lines = ["Tesla Battery Guru — demo month (pretend car, pretend sessions)"]
    for s in sessions:
        implied = s.implied_pack_kwh()
        implied_s = f", implies {implied:.1f} kWh pack" if implied else \
            " (top-up — too small to estimate from)"
        dwell_s = f", sat at {s.end_soc:.0f}% for {s.dwell_hours:g}h" \
            if s.dwell_hours else ""
        lines.append(
            f"{s.start.strftime('%a %b %d, %I:%M %p')} — {s.vehicle} at "
            f"{s.location_name or s.location_class}: {s.kwh_added:.1f} kWh, "
            f"{s.start_soc:.0f}% → {s.end_soc:.0f}%{implied_s}{dwell_s}")
    lines.append("")
    lines.append(health_report(sessions, DEMO_NOMINAL_PACK_KWH,
                               settings.daily_limit_pct))
    lines.append("")
    lines.append("Why the estimate is trustworthy: eight sessions with swings")
    lines.append("of 50–62 points all imply the same 70.0 kWh pack, and the")
    lines.append("median throws out any single odd session. The Sep 30 top-up")
    lines.append("(65% → 72%) is ignored — dividing by a 7-point swing would")
    lines.append("magnify a 1 kWh rounding error into a 14 kWh pack error.")
    lines.append("")
    lines.append("Expected Fleet API cost: this app only reads charge state")
    lines.append("while the car is already awake and charging — no wake-ups,")
    lines.append("no commands, so the real bill stays near zero. The health")
    lines.append("record lives on your computer, not in Tesla's cloud.")
    return lines
