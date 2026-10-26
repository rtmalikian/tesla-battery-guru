"""CLI: tbguru setup | auth | serve | ask | record | report | export | preview | simulate

Safety posture: recording a session only writes to a file on your own
computer — nothing is sent anywhere, and no car is ever commanded.
`record --dry-run` and `preview` show the estimate before anything is stored.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

from .config import ConfigError, load_settings, parse_12h_time

__version__ = "0.1.0"


def _setup_logging(verbose: bool) -> None:
    import logging
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")


def _client(settings):
    from .tesla_client import TeslaClient
    return TeslaClient(settings.client_id, settings.client_secret,
                       region=settings.region, redirect_uri=settings.redirect_uri,
                       token_file=settings.token_file)


def cmd_auth(args, settings) -> int:
    client = _client(settings)
    print("Open this URL in your browser and authorize:")
    print(client.authorize_url())
    print("Virtual-key pairing: https://developer.tesla.com/docs/fleet-api#pairing")
    return 0


def cmd_setup(args, settings) -> int:
    from .setup import run_setup
    run_setup()
    return 0


def _sessions_for_api(settings):
    """Real sessions if they exist, else the demo month (labelled as such)
    so the API is testable before the first real session."""
    from .battery import load_sessions
    from .simulator import run_demo_month
    real = load_sessions(settings.data_file)
    if real:
        return real, False
    return run_demo_month(settings), True


def cmd_serve(args, settings) -> int:
    from .server import serve
    from .service import BatteryGuruService
    sessions, is_demo = _sessions_for_api(settings)
    service = BatteryGuruService(settings, sessions_provider=lambda: sessions)
    print("Battery data goes ONLY to your configured LLM backend "
          f"(TBG_AI_BASE_URL={settings.ai_base_url or 'none'}); "
          "the rules engine answers health questions with no backend at all.")
    if is_demo:
        print("(Serving the demo month — record a real session and the")
        print(" API will answer from your sessions instead.)")
    print("This app only reads and scores charging — it never commands a car.")
    serve(service)
    return 0


def cmd_ask(args, settings) -> int:
    from .service import BatteryGuruService
    sessions, is_demo = _sessions_for_api(settings)
    service = BatteryGuruService(settings, sessions_provider=lambda: sessions)
    if is_demo:
        print("(Demo month — record a real session to ask about your battery.)")
    body = {"model": settings.model_id,
            "messages": [{"role": "user", "content": args.question}]}
    resp = service.chat_completions(body)
    print(resp["choices"][0]["message"]["content"])
    return 0


def _parse_session_args(args, settings):
    """Build a ChargeSession from CLI args, or ask interactively for
    anything missing. Returns a session or None on bad input."""
    from .battery import ChargeSession
    cars = [v.name for v in settings.vehicles]
    car = args.car
    if not car:
        if len(cars) == 1:
            car = cars[0]
            print(f"Car: {car} (your only car — run setup to add more)")
        elif cars:
            print("Which car charged?")
            for i, name in enumerate(cars, 1):
                print(f"  {i}) {name}")
            pick = input("> ").strip()
            try:
                car = cars[int(pick) - 1]
            except (ValueError, IndexError):
                print("That wasn't one of the numbered cars — try again.")
                return None
        else:
            car = input("Car nickname (e.g. Model Y): ").strip() or "Model Y"

    def ask(prompt, default=""):
        suffix = f" [{default}]" if default else ""
        answer = input(f"{prompt}{suffix}\n> ").strip()
        return answer or default

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    date_s = args.date or ask("Date of the session (like 2026-09-15)", today)
    start_s = args.start or ask("Charging started at (like 11:00 PM)", "11:00 PM")
    end_s = args.end or ask("Charging ended at (like 6:00 AM)", "6:00 AM")
    try:
        day = datetime.strptime(date_s, "%Y-%m-%d")
    except ValueError:
        print(f"Couldn't read that date: {date_s!r}. Write it like 2026-09-15.")
        return None
    try:
        start_min = parse_12h_time(start_s)
        end_min = parse_12h_time(end_s)
    except ConfigError as exc:
        print(f"Couldn't read that time: {exc}")
        return None
    start = day.replace(hour=start_min // 60, minute=start_min % 60,
                        tzinfo=timezone.utc)
    end = day.replace(hour=end_min // 60, minute=end_min % 60,
                      tzinfo=timezone.utc)
    if end <= start:  # overnight session: end is the next morning
        end += timedelta(days=1)
    try:
        start_soc = float(args.start_soc if args.start_soc is not None
                          else ask("Battery % when charging started:", "30"))
        end_soc = float(args.end_soc if args.end_soc is not None
                        else ask("Battery % when it finished:", "80"))
        kwh = float(args.kwh if args.kwh is not None
                    else ask("Energy added in kWh (from the car's screen):", "40"))
        dwell = float(args.dwell_hours if args.dwell_hours is not None
                      else ask("Hours the car then sat at that charge "
                               "(0 if you drove off right away):", "0"))
    except ValueError:
        print("Those need to be numbers — battery % like 30, kWh like 40.")
        return None
    loc = args.location_class
    if not loc:
        print("Where did you charge?")
        print("  1) Home")
        print("  2) Supercharger")
        print("  3) Other public charger")
        pick = ask("Pick 1, 2 or 3:", "1")
        loc = {"1": "home", "2": "supercharger", "3": "public"}.get(pick, "home")
    place = args.place if args.place is not None else ask(
        "Charger name or place (blank is fine):", "")
    session = ChargeSession(car, start, end, start_soc, end_soc, kwh, loc,
                            place, dwell)
    try:
        session.validate()
    except Exception as exc:
        print(f"That session doesn't add up: {exc}")
        return None
    return session


def cmd_record(args, settings) -> int:
    from .battery import append_session
    session = _parse_session_args(args, settings)
    if session is None:
        return 2
    implied = session.implied_pack_kwh()
    print("")
    print("Here's what I would record:")
    print(f"  {session.vehicle} at {session.location_name or session.location_class}, "
          f"{session.start.strftime('%b %d, %I:%M %p')} → "
          f"{session.end.strftime('%I:%M %p')}, {session.kwh_added:.1f} kWh, "
          f"{session.start_soc:.0f}% → {session.end_soc:.0f}%")
    if implied is not None:
        print(f"  This session alone implies a {implied:.1f} kWh pack.")
    else:
        print("  (Top-up — too small a swing to estimate the pack from.)")
    if args.dry_run or settings.dry_run:
        print("Dry run — nothing was saved. Re-run without --dry-run to save it.")
        return 0
    if not args.yes:
        answer = input("Save this session? (y/n) ").strip().lower()
        if answer not in ("y", "yes"):
            print("Not saved.")
            return 0
    append_session(settings.data_file, session)
    print(f"Saved to {settings.data_file}.")
    return 0


def cmd_report(args, settings) -> int:
    from .battery import health_report, load_sessions
    sessions = load_sessions(settings.data_file)
    if not sessions:
        print("No sessions recorded yet — nothing to report.")
        print("Record a session with `tbguru record`, or see a demo month")
        print("with `tbguru simulate`.")
        return 0
    if args.car:
        sessions = [s for s in sessions if s.vehicle.lower() == args.car.lower()]
    print(health_report(sessions, settings.nominal_pack_kwh,
                        settings.daily_limit_pct))
    return 0


def cmd_export(args, settings) -> int:
    from .battery import export_csv, load_sessions
    sessions = load_sessions(settings.data_file)
    if not sessions:
        print("No sessions recorded yet — nothing to export.")
        return 0
    out = args.out or "battery-sessions.csv"
    n = export_csv(sessions, out)
    print(f"Wrote {n} sessions to {out} (date, car, location, SoC swing, "
          "kWh, implied pack, dwell hours).")
    return 0


def cmd_preview(args, settings) -> int:
    """What one hypothetical session would imply — saves nothing."""
    from .battery import ChargeSession
    now = datetime.now(timezone.utc)
    session = ChargeSession("Preview car", now, now + timedelta(hours=5),
                            args.start_soc, args.end_soc, args.kwh,
                            args.location_class, args.place or "")
    implied = session.implied_pack_kwh()
    if implied is None:
        print(f"Preview: {args.start_soc:.0f}% → {args.end_soc:.0f}% is too "
              f"small a swing to estimate from — use a swing of 20 points "
              f"or more. Nothing was saved.")
    else:
        print(f"Preview: {args.kwh:.1f} kWh over {args.start_soc:.0f}% → "
              f"{args.end_soc:.0f}% implies a {implied:.1f} kWh pack "
              f"({(1 - implied / settings.nominal_pack_kwh) * 100:.1f}% "
              f"below your {settings.nominal_pack_kwh:.0f} kWh nominal pack).")
    print("Nothing was saved — this was a preview only.")
    return 0


def cmd_simulate(_args, settings) -> int:
    from .simulator import timeline_lines
    for line in timeline_lines(settings):
        print(line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tbguru",
        description="A free battery-health estimator for your Teslas: "
                    "degradation from charge sessions, a habit care score, "
                    "and 3-day streak alerts.")
    p.add_argument("--version", action="version", version=f"tbguru {__version__}")
    p.add_argument("--env-file", default=None)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="Guided first-run setup (plain-language questions)")
    sub.add_parser("auth", help="Authorize with your Tesla account (one-time)")
    sub.add_parser("serve", help="Run the OpenAI-compatible battery-coach API server")
    ask_p = sub.add_parser("ask", help="One-shot health question (your sessions, or demo month)")
    ask_p.add_argument("question", help="e.g. 'how degraded is my battery?'")
    rec_p = sub.add_parser("record", help="Log a charging session (asks what it needs)")
    rec_p.add_argument("--car", default=None)
    rec_p.add_argument("--date", default=None, help="YYYY-MM-DD")
    rec_p.add_argument("--start", default=None, help="e.g. 11:00 PM")
    rec_p.add_argument("--end", default=None, help="e.g. 6:00 AM")
    rec_p.add_argument("--start-soc", type=float, default=None)
    rec_p.add_argument("--end-soc", type=float, default=None)
    rec_p.add_argument("--kwh", type=float, default=None)
    rec_p.add_argument("--dwell-hours", type=float, default=None,
                       help="Hours the car sat at the final charge")
    rec_p.add_argument("--location-class", default=None,
                       choices=["home", "supercharger", "public"])
    rec_p.add_argument("--place", default=None)
    rec_p.add_argument("--dry-run", action="store_true",
                       help="Show what would be recorded, save nothing")
    rec_p.add_argument("--yes", action="store_true",
                       help="Save without asking for confirmation")
    rep_p = sub.add_parser("report", help="Battery health report")
    rep_p.add_argument("--car", default=None)
    exp_p = sub.add_parser("export", help="Export sessions to CSV")
    exp_p.add_argument("--out", default=None)
    pre_p = sub.add_parser("preview", help="What one session implies (saves nothing)")
    pre_p.add_argument("--kwh", type=float, required=True)
    pre_p.add_argument("--start-soc", type=float, required=True)
    pre_p.add_argument("--end-soc", type=float, required=True)
    pre_p.add_argument("--location-class", default="home",
                       choices=["home", "supercharger", "public"])
    pre_p.add_argument("--place", default=None)
    sub.add_parser("simulate", help="Demo month timeline (no API calls)")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    env = dict(os.environ)
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=True)
        env = dict(os.environ)
    else:
        from dotenv import load_dotenv
        load_dotenv(override=False)
        env = dict(os.environ)
    try:
        settings = load_settings(env)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    handlers = {"setup": cmd_setup, "auth": cmd_auth, "serve": cmd_serve,
                "ask": cmd_ask, "record": cmd_record, "report": cmd_report,
                "export": cmd_export, "preview": cmd_preview,
                "simulate": cmd_simulate}
    return handlers[args.command](args, settings)


if __name__ == "__main__":
    raise SystemExit(main())
