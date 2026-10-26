# Tesla Battery Guru — Free Battery Degradation Estimator & Care Score for Tesla Model 3, Model Y, Model S, Model X & Cybertruck

> **▶ Try the live demo: https://rtmalikian.github.io/tesla-battery-guru/** (interactive, runs on pretend data)

**Free & open source Tesla battery health tracking via the Tesla Fleet API: estimate your usable pack size and degradation from charge sessions, get a habit-based care score, and catch harmful charging patterns before they become habits — no paid app, no OBD dongle, no subscription.**

## Why?

Tesla owners ask the same questions, constantly, with no free answer:

- "How much has my battery actually degraded?" — the Tesla app never shows degradation.
- "Is charging to 100% every night hurting my pack?" — nobody scores your habits.
- "Am I treating my battery well?" — paid apps (Tessie, TezLab) charge a subscription for what your charge sessions already reveal.

Tesla already knows every charge session exactly — battery % before and after, kWh added. Battery Guru turns that into the number owners actually want, using the same math owners do by hand: a session from 30% to 80% adding 35 kWh implies a 70 kWh usable pack. Take the median over your big sessions, compare it to the pack size when new, and you have degradation — no dongle, no guesswork.

## How it works

```
Sep 03  30% → 80%, 35.0 kWh  → implies 70.0 kWh pack
Sep 07  20% → 80%, 42.0 kWh  → implies 70.0 kWh pack
Sep 10  45% → 100%, sat 8h   → implies 70.0 kWh pack (and a bad habit)
Sep 11  50% → 100%, sat 8h   → same
Sep 12  40% → 100%, sat 8h   → same — 3 days running = ALERT
...
Median of 8 big sessions: 70.0 kWh vs 75 kWh when new → degradation 6.7%
Care score: 53/100 (sitting at 100% −30, Supercharger share −2,
  deep discharges −5, days above daily limit −10)
```

**The estimate.** Sessions with a swing of 20 points or more each imply a pack size; the median of those is the estimate, so one odd session (a cold morning, a BMS recalibration) can't move it. Small top-ups are ignored — dividing by a 7-point swing would magnify a 1 kWh rounding error into a 14 kWh pack error.

**The care score (0–100).** Start at 100, subtract explainable penalties, each capped and always shown next to the score: sitting at 100% after charging (−2/hour, max −30), Supercharger share (−20 × share), deep discharges starting at/below 10% (−5 each, max −25), days ending above your daily limit (−2/day, max −15). No black-box number.

**Streak alerts.** One bad day is a shrug; the same harmful pattern on 3 consecutive calendar days is a habit. Battery Guru alerts on: charged to 100% (and left sitting 2+ hours), deep discharges, and Supercharger-only days.

**Expected API cost:** this app only reads charge state while the car is already awake and charging — no wake-ups, no commands, so the real bill stays near zero. The health record lives on your computer, not in Tesla's cloud.

## Quickstart (for owners, not developers)

No AI needed: everything below works with no LLM backend at all. The AI coach is an optional extra.

```bash
git clone https://github.com/rtmalikian/tesla-battery-guru.git
cd tesla-battery-guru
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
tbguru setup        # plain-language questions — writes .env for you
tbguru simulate     # see a demo month with pretend sessions (no car needed)
tbguru record       # log your first real session (it asks what it needs)
tbguru report       # your battery health report
tbguru serve        # start the battery-coach API on http://127.0.0.1:8649
```

What you'll see when it works: `tbguru simulate` prints the demo month's sessions, the 70.0 kWh estimate, the 6.7% degradation, the care score, and the 100% streak alert. `tbguru record` asks for the car (numbered list), date, times in "11:00 PM" words, battery %, kWh, and hours sat at the final charge — then shows a preview and asks "Save this session?" before writing anything.

### Commands

| Command | What it does |
|---|---|
| `tbguru setup` | Guided setup wizard (writes `.env` itself) |
| `tbguru auth` | One-time Tesla authorization (opens a link) |
| `tbguru serve` | Run the OpenAI-compatible coach API server |
| `tbguru ask "…"` | One-shot health question (your sessions, or the demo month) |
| `tbguru record` | Log a charging session (asks what it needs; `--dry-run` previews) |
| `tbguru report` | Battery health report (`--car "Model Y"` filters) |
| `tbguru export` | Export sessions to CSV |
| `tbguru preview --kwh 42 --start-soc 20 --end-soc 80` | What one session implies (saves nothing) |
| `tbguru simulate` | Demo month timeline (no API calls) |

### Preview before action

`record` always shows what it would save and asks for confirmation (or use `--dry-run` to preview without saving). `preview` computes a single session's implied pack without storing anything. The app never commands a car — it only reads and scores charging.

## AI endpoints

Battery Guru embeds OpenAI-compatible endpoints so any AI client (ChatGPT-style apps, Ollama clients, LangChain, Open WebUI) can ask about your battery:

```bash
# What models are available?
curl http://127.0.0.1:8649/v1/models

# Ask about your battery (rules engine answers — no LLM needed)
curl http://127.0.0.1:8649/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "model": "tesla-battery-guru",
  "messages": [{"role": "user", "content": "how degraded is my battery?"}]
}'

# Embeddings over session text (local deterministic 384-dim vectors by default)
curl http://127.0.0.1:8649/v1/embeddings -H 'Content-Type: application/json' -d '{
  "model": "tesla-battery-guru", "input": "home charge 30% to 80%"
}'
```

Streaming is not supported (`stream: true` is ignored). The rules engine answers health questions from computed stats with no backend at all; with a backend configured (`TBG_AI_MODE=auto`, default Ollama at `http://localhost:11434/v1`), the LLM explains the stats in free-form words — it never invents a degradation number, and it never commands a car. Vehicle data is sent only to the backend you configure, nowhere else. Optional bearer auth: set `TBG_SERVER_API_KEY` and clients must send `Authorization: Bearer <key>`.

## Tesla developer setup

1. Create a free app at [developer.tesla.com](https://developer.tesla.com) and note the Client ID and Secret.
2. Run `tbguru setup` and paste them when asked (they stay in `.env` on your computer).
3. Run `tbguru auth` and follow the link to authorize; pair the virtual key per [Tesla's pairing docs](https://developer.tesla.com/docs/fleet-api#pairing).
4. Record sessions with `tbguru record` — or let the Fleet API feed them in as the integration grows.

## `.env` reference

| Variable | Default | Meaning |
|---|---|---|
| `TESLA_CLIENT_ID` / `TESLA_CLIENT_SECRET` | — | Your Tesla developer app credentials |
| `TESLA_REGION` | `na` | `na`, `eu`, or `cn` |
| `TBG_VEHICLES` | — | `Model Y=VIN,Model 3=VIN2` (picked by number in setup) |
| `TBG_SERVER_HOST` / `TBG_SERVER_PORT` | `127.0.0.1` / `8649` | The coach API address |
| `TBG_SERVER_API_KEY` | (blank) | Optional bearer token for `/v1/*` |
| `TBG_AI_BASE_URL` | `http://localhost:11434/v1` | Pluggable LLM backend (Ollama default) |
| `TBG_AI_API_KEY` / `TBG_AI_MODEL` | — / `llama3.1` | Backend credentials and model |
| `TBG_AI_MODE` | `auto` | `auto` (rules first) / `always` / `never` |
| `TBG_NOMINAL_PACK_KWH` | `75` | Pack size when new (Model 3/Y LR ≈ 75, SR ≈ 60, S/X ≈ 100) |
| `TBG_DAILY_LIMIT_PCT` | `80` | Everyday charge limit you aim for |
| `TBG_DATA_FILE` | `~/.tbg/battery.jsonl` | Your session record (local JSONL) |
| `TBG_DRY_RUN` | `0` | `1` = preview instead of saving |

## FAQ

**How accurate is the degradation estimate?**
It's the median of your big sessions' implied pack sizes, which cancels out single-session noise (temperature, BMS rounding). It's an estimate from the data Tesla reports — the same method owners use by hand — not a lab measurement. More big sessions (20+ points of swing) = a steadier number.

**Why are small top-ups ignored?**
A 65% → 72% top-up divides by 7 points, so a 1 kWh rounding error becomes a 14 kWh pack error. The estimator only trusts swings of 20 points or more.

**Do I need an AI backend?**
No. The rules engine answers "how degraded is my battery?", "what's my care score?", and "any alerts?" with no backend at all. The LLM only adds free-form coaching on top of the same computed stats.

**Does it wake my car or change any settings?**
No. It never commands a car and never wakes one to measure anything. It reads charge sessions and scores them.

**What if my car is a Standard Range or Model S?**
Pick your pack size in `tbguru setup` (60 kWh, 75 kWh, 100 kWh, or your own number) — degradation is measured against whatever you set.

**Why did my care score drop after a road trip?**
Supercharger-heavy days and 100% charges for trip range cost points, and that's honest: road trips are harder on the pack than home charging to 80%. The score recovers as gentle home sessions accumulate — it's a habit mirror, not a grade.

**Is my data private?**
Yes. Sessions live in a JSONL file on your computer. Nothing is uploaded except to the AI backend you explicitly configure (local Ollama by default, which never leaves your machine).

## Keywords

Tesla Fleet API, free open source, Model 3, Model Y, Model S, Model X, Cybertruck, battery health, battery degradation, usable capacity, charge sessions, care score, Supercharger, phantom drain, battery longevity, EV battery health, Tesla battery degradation calculator.

## License

MIT — Raphael Malikian. Built as part of the Tesla AI app series: one free, open-source Tesla tool per day, each with OpenAI-compatible endpoints and a deterministic offline engine.
