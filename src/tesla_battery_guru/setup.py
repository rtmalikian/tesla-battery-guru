"""Guided first-run setup: plain-language questions, writes .env itself.

Built for Tesla owners, not developers — defaults everywhere, numbered
choices, pack sizes in plain words ("Model 3/Y Long Range, about
75 kWh"). Testable: input and output are injectable.
"""
from __future__ import annotations

import os
from pathlib import Path


def _ask(input_fn, out, prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    out(f"{prompt}{suffix}")
    answer = input_fn("> ").strip()
    return answer or default


def _ask_required(input_fn, out, prompt: str, help_text: str) -> str:
    while True:
        out(help_text)
        answer = input_fn(f"{prompt} ").strip()
        if answer:
            return answer
        out("That one's required — without it the app can't do its job.")


def run_setup(input_fn=input, out=print, env_path: str = ".env") -> Path:
    out("")
    out("Welcome to Tesla Battery Guru setup — I'll ask a few questions and")
    out("write the settings file for you. Press Enter to accept a [default].")
    out("")

    path = Path(env_path)
    if path.exists():
        again = _ask(input_fn, out,
                     "A settings file (.env) already exists. Replace it? (y/n)", "n")
        if again.lower() not in ("y", "yes"):
            out("Keeping your existing settings. Nothing changed.")
            return path

    out("STEP 1 of 5 — Connect to Tesla")
    out("Create a free developer app at developer.tesla.com (sign in, then")
    out("'Create App'). Tesla will show you a Client ID and Client Secret.")
    client_id = _ask_required(input_fn, out, "Paste your Client ID:",
                              "First, the Client ID:")
    client_secret = _ask_required(
        input_fn, out, "Paste your Client Secret:",
        "Now the Client Secret (it stays on this computer):")

    out("")
    out("STEP 2 of 5 — Your cars")
    out("For each car: a nickname and its VIN. Find the VIN in your Tesla")
    out("app under Controls → Software (or on the car's touchscreen).")
    vehicles: list[tuple[str, str]] = []
    while True:
        n = len(vehicles) + 1
        name = _ask(input_fn, out,
                    f"Car {n} nickname (e.g. Model Y) — or press Enter if done:",
                    "")
        if not name:
            if vehicles:
                break
            out("Add at least one car to continue.")
            continue
        vin = _ask_required(input_fn, out, f"VIN for {name}:",
                            f"Now the VIN for {name}:")
        vehicles.append((name, vin))

    out("")
    out("STEP 3 of 5 — Your battery's size when new")
    out("Degradation is measured against this number, so pick the closest:")
    out("  1) Model 3/Y Long Range — about 75 kWh (default)")
    out("  2) Model 3/Y Standard Range — about 60 kWh")
    out("  3) Model S/X — about 100 kWh")
    out("  4) Another size — you type the kWh")
    choice = _ask(input_fn, out, "Pick 1, 2, 3 or 4:", "1")
    if choice == "2":
        pack = "60"
    elif choice == "3":
        pack = "100"
    elif choice == "4":
        pack = _ask(input_fn, out,
                    "Battery size when new, in kWh (like 82):", "75")
    else:
        pack = "75"

    out("")
    out("STEP 4 of 5 — Your everyday charge limit")
    out("Tesla's own daily guidance is 80% — sessions ending above your")
    out("limit count toward the care score, and sitting at 100% counts more.")
    limit = _ask(input_fn, out,
                 "Everyday charge limit in percent (like 80):", "80")

    out("")
    out("STEP 5 of 5 — The AI coach (optional) and the report server")
    out("  1) Built-in answers only — no AI, nothing leaves this computer")
    out("  2) Ollama on this computer — free local AI (default)")
    out("  3) Another AI service (OpenAI, Groq, LM Studio…) — you'll paste its details")
    choice = _ask(input_fn, out, "Pick 1, 2 or 3:", "2")
    ai_mode, ai_url, ai_key, ai_model = "auto", "http://localhost:11434/v1", "", "llama3.1"
    if choice == "1":
        ai_mode = "never"
    elif choice == "3":
        ai_url = _ask_required(input_fn, out, "Service address (base URL):",
                               "Paste the service's API address:")
        ai_key = _ask(input_fn, out, "API key for that service (stored only here):")
        ai_model = _ask(input_fn, out, "Model name:", "gpt-4o-mini")
    port = _ask(input_fn, out, "Port for the report address:", "8649")
    server_key = _ask(input_fn, out,
                      "Optional password for the report address (blank = none):")

    lines = [
        "# Written by `tbguru setup` — edit by re-running setup any time.",
        f"TESLA_CLIENT_ID={client_id}",
        f"TESLA_CLIENT_SECRET={client_secret}",
        "TESLA_REGION=na",
        "TESLA_REDIRECT_URI=http://localhost:8080/callback",
        "TBG_VEHICLES=" + ",".join(f"{name}={vin}" for name, vin in vehicles),
        "TBG_SERVER_HOST=127.0.0.1",
        f"TBG_SERVER_PORT={port}",
        f"TBG_SERVER_API_KEY={server_key}",
        "TBG_MODEL_ID=tesla-battery-guru",
        f"TBG_AI_BASE_URL={ai_url}",
        f"TBG_AI_API_KEY={ai_key}",
        f"TBG_AI_MODEL={ai_model}",
        f"TBG_AI_MODE={ai_mode}",
        "TBG_AI_TIMEOUT_SECONDS=20",
        "TBG_EMBEDDING_DIM=384",
        "TBG_TOKEN_FILE=~/.tbg/tokens.json",
        f"TBG_NOMINAL_PACK_KWH={pack}",
        f"TBG_DAILY_LIMIT_PCT={limit}",
        "TBG_DATA_FILE=~/.tbg/battery.jsonl",
        "TBG_DRY_RUN=0",
    ]
    path.write_text("\n".join(lines) + "\n")
    os.chmod(path, 0o600)

    out("")
    out("All set — settings saved to .env (only readable by you).")
    out("Next steps:")
    out("  1) tbguru auth       — sign in to Tesla once (opens a link)")
    out("  2) tbguru simulate   — see a demo month with pretend sessions")
    out("  3) tbguru record     — log your first real charging session")
    out("  4) tbguru report     — your battery health report")
    out("  5) tbguru serve      — start the battery-coach Q&A API")
    return path
