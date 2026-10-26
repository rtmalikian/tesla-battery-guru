"""Battery-health estimation: pure decision logic, no network, no clock
except the one callers pass in. Every function here is unit-testable.

Method (the one owners use by hand, automated)
----------------------------------------------
A charge session that moves the battery from A% to B% while adding
K kWh implies a usable pack of K / ((B - A) / 100) kWh. One session is
noisy (BMS rounding, temperature, taper), so the estimate is the
MEDIAN of all sessions with a swing of at least 20 points — small
top-ups are ignored, because dividing by a tiny delta magnifies error.
Degradation = 1 - (estimated pack / nominal pack when new).

Habit score (0–100, higher is kinder to the pack)
--------------------------------------------------
Start at 100 and subtract explainable penalties, each capped:
* sitting at 100% after charging (dwell hours): -2 per hour, max -30
* Supercharger share of sessions: -20 × share, max -20
* deep discharges (a session starting at or below 10%): -5 each, max -25
* days ending above the owner's daily limit: -2 per day, max -15
The breakdown is always shown next to the score, so the number is
never a black box.

Streak alerts
--------------
A harmful pattern that repeats on 3 consecutive calendar days raises
an alert: "charged to 100%", "deep discharge (at/below 10%)", and
"Supercharger-only day". One bad day is a shrug; three in a row is a
habit worth a nudge.

Location classes: "home" | "supercharger" | "public".
This app never commands a car — it only reads charge sessions you
record (or that the Fleet API reports while the car is already awake).
"""
from __future__ import annotations

import csv
import json
import statistics
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

LOCATION_CLASSES = ("home", "supercharger", "public")
MIN_SWING_POINTS = 20.0     # ignore top-ups smaller than this
DEEP_DISCHARGE_PCT = 10.0   # a session starting at/below this is deep
STREAK_DAYS = 3             # consecutive days that raise an alert


class BatteryError(Exception):
    """Human-readable battery problem (bad session, bad file)."""


@dataclass
class ChargeSession:
    vehicle: str
    start: datetime
    end: datetime
    start_soc: float       # percent, 0-100
    end_soc: float         # percent, 0-100
    kwh_added: float
    location_class: str    # home | supercharger | public
    location_name: str = ""
    dwell_hours: float = 0.0   # hours the car sat at end_soc after charging

    def validate(self) -> None:
        if not self.vehicle.strip():
            raise BatteryError("A charge session needs a car name.")
        if self.location_class not in LOCATION_CLASSES:
            raise BatteryError(
                f"Charging location must be home, supercharger, or public — "
                f"got {self.location_class!r}. Pick one of the three.")
        if self.end <= self.start:
            raise BatteryError(
                "The charging end time must be after the start time — "
                "check the session's times.")
        if self.kwh_added < 0:
            raise BatteryError("Energy added can't be negative.")
        if self.dwell_hours < 0:
            raise BatteryError("Hours sitting at the final charge can't be negative.")
        for label, soc in (("start", self.start_soc), ("end", self.end_soc)):
            if not (0 <= soc <= 100):
                raise BatteryError(
                    f"The {label} battery percentage must be between 0 and 100, "
                    f"got {soc}.")
        if self.end_soc < self.start_soc and self.kwh_added > 0:
            raise BatteryError(
                "The battery went down while charging added energy — "
                "check the start/end percentages.")

    def implied_pack_kwh(self) -> float | None:
        """Pack size this session implies, or None if the swing is too small."""
        swing = self.end_soc - self.start_soc
        if swing < MIN_SWING_POINTS or self.kwh_added <= 0:
            return None
        return self.kwh_added / (swing / 100.0)

    # -- JSONL store ---------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "vehicle": self.vehicle,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "start_soc": self.start_soc,
            "end_soc": self.end_soc,
            "kwh_added": self.kwh_added,
            "location_class": self.location_class,
            "location_name": self.location_name,
            "dwell_hours": self.dwell_hours,
        }

    @classmethod
    def from_dict(cls, row: dict) -> "ChargeSession":
        return cls(
            vehicle=row["vehicle"],
            start=datetime.fromisoformat(row["start"]),
            end=datetime.fromisoformat(row["end"]),
            start_soc=float(row["start_soc"]),
            end_soc=float(row["end_soc"]),
            kwh_added=float(row["kwh_added"]),
            location_class=row["location_class"],
            location_name=row.get("location_name", ""),
            dwell_hours=float(row.get("dwell_hours", 0.0)),
        )


def load_sessions(path: str) -> list[ChargeSession]:
    p = Path(path).expanduser()
    if not p.exists():
        return []
    sessions = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            sessions.append(ChargeSession.from_dict(json.loads(line)))
    return sessions


def append_session(path: str, session: ChargeSession) -> None:
    session.validate()
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as fh:
        fh.write(json.dumps(session.to_dict()) + "\n")


def export_csv(sessions: list[ChargeSession], out_path: str) -> int:
    with open(out_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "car", "location", "start_soc_pct", "end_soc_pct",
                    "kwh_added", "implied_pack_kwh", "dwell_hours_at_end"])
        for s in sessions:
            implied = s.implied_pack_kwh()
            w.writerow([s.start.strftime("%Y-%m-%d"), s.vehicle,
                        s.location_name or s.location_class,
                        s.start_soc, s.end_soc, s.kwh_added,
                        f"{implied:.1f}" if implied is not None else "",
                        s.dwell_hours])
    return len(sessions)


# -- estimation ---------------------------------------------------------

@dataclass
class HealthEstimate:
    vehicle: str
    sessions_used: int
    sessions_total: int
    estimated_pack_kwh: float | None
    nominal_pack_kwh: float
    degradation_pct: float | None   # None when no usable sessions

    def summary_line(self) -> str:
        if self.estimated_pack_kwh is None:
            return (f"{self.vehicle}: not enough big charge sessions yet — "
                    f"record sessions with a swing of {MIN_SWING_POINTS:.0f} "
                    f"points or more and I'll estimate the pack.")
        return (f"{self.vehicle}: estimated usable pack "
                f"{self.estimated_pack_kwh:.1f} kWh vs "
                f"{self.nominal_pack_kwh:.0f} kWh when new — "
                f"degradation {self.degradation_pct:.1f}% "
                f"({self.sessions_used} of {self.sessions_total} sessions used).")


def estimate_health(sessions: list[ChargeSession],
                    nominal_pack_kwh: float) -> list[HealthEstimate]:
    """One estimate per car, from that car's own sessions only."""
    out = []
    for car in sorted({s.vehicle for s in sessions}):
        car_sessions = [s for s in sessions if s.vehicle == car]
        implied = [s.implied_pack_kwh() for s in car_sessions]
        implied = [v for v in implied if v is not None]
        if implied:
            pack = statistics.median(implied)
            degradation = (1.0 - pack / nominal_pack_kwh) * 100.0
        else:
            pack, degradation = None, None
        out.append(HealthEstimate(car, len(implied), len(car_sessions),
                                  pack, nominal_pack_kwh, degradation))
    return out


# -- habit score --------------------------------------------------------

@dataclass
class CareScore:
    vehicle: str
    score: int
    penalties: dict  # label -> points lost

    def summary_line(self) -> str:
        bits = ", ".join(f"{label} −{pts}" for label, pts in self.penalties.items()
                         if pts > 0) or "no bad habits spotted"
        return f"{self.vehicle}: care score {self.score}/100 ({bits})."


def score_care(sessions: list[ChargeSession],
               daily_limit_pct: float = 80.0) -> list[CareScore]:
    out = []
    for car in sorted({s.vehicle for s in sessions}):
        car_sessions = [s for s in sessions if s.vehicle == car]
        dwell100 = sum(s.dwell_hours for s in car_sessions if s.end_soc >= 100)
        sc_share = (sum(1 for s in car_sessions
                        if s.location_class == "supercharger")
                    / len(car_sessions)) if car_sessions else 0.0
        deep = sum(1 for s in car_sessions if s.start_soc <= DEEP_DISCHARGE_PCT)
        over_days = len({s.start.date() for s in car_sessions
                         if s.end_soc > daily_limit_pct})
        penalties = {
            "sitting at 100%": min(30, int(dwell100 * 2)),
            "Supercharger share": min(20, int(sc_share * 20)),
            "deep discharges": min(25, deep * 5),
            "days charged above daily limit": min(15, over_days * 2),
        }
        score = max(0, 100 - sum(penalties.values()))
        out.append(CareScore(car, score, penalties))
    return out


# -- streak alerts ------------------------------------------------------

def _pattern_days(sessions: list[ChargeSession], pattern: str) -> set[date]:
    days: set[date] = set()
    for s in sessions:
        day = s.start.date()
        if pattern == "charged to 100%" and s.end_soc >= 100 and s.dwell_hours >= 2:
            days.add(day)
        elif pattern == "deep discharge" and s.start_soc <= DEEP_DISCHARGE_PCT:
            days.add(day)
    if pattern == "Supercharger-only day":
        by_day: dict[date, list[ChargeSession]] = {}
        for s in sessions:
            by_day.setdefault(s.start.date(), []).append(s)
        for day, day_sessions in by_day.items():
            if all(s.location_class == "supercharger" for s in day_sessions):
                days.add(day)
    return days


PATTERNS = ("charged to 100%", "deep discharge", "Supercharger-only day")


def detect_streak_alerts(sessions: list[ChargeSession]) -> list[str]:
    """One alert per car+pattern with a run of STREAK_DAYS consecutive days."""
    alerts = []
    for car in sorted({s.vehicle for s in sessions}):
        car_sessions = [s for s in sessions if s.vehicle == car]
        for pattern in PATTERNS:
            days = sorted(_pattern_days(car_sessions, pattern))
            run_start = None
            prev = None
            run = 0
            for day in days:
                if prev is not None and (day - prev).days == 1:
                    run += 1
                else:
                    run, run_start = 1, day
                if run >= STREAK_DAYS:
                    alerts.append(
                        f"{car}: {pattern} on {STREAK_DAYS} days running "
                        f"(from {run_start.strftime('%b %d')}) — a habit, "
                        f"not a one-off. Worth a look at your charging routine.")
                    break
                prev = day
    return alerts


# -- reports / AI brief -------------------------------------------------

def health_report(sessions: list[ChargeSession], nominal_pack_kwh: float,
                  daily_limit_pct: float = 80.0) -> str:
    if not sessions:
        return "No charge sessions recorded yet."
    lines = []
    for est in estimate_health(sessions, nominal_pack_kwh):
        lines.append(est.summary_line())
    for score in score_care(sessions, daily_limit_pct):
        lines.append(score.summary_line())
    alerts = detect_streak_alerts(sessions)
    if alerts:
        lines.append("Alerts:")
        lines.extend(f"  • {a}" for a in alerts)
    else:
        lines.append("Alerts: none — no harmful pattern repeated 3 days running.")
    return "\n".join(lines)


def battery_brief(sessions: list[ChargeSession], nominal_pack_kwh: float,
                  daily_limit_pct: float = 80.0) -> str:
    """Grounding context for the LLM: computed stats only, never guesses."""
    if not sessions:
        return "No charge sessions recorded yet."
    return health_report(sessions, nominal_pack_kwh, daily_limit_pct)
