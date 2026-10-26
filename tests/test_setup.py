"""The setup wizard must produce a config the app can load — no developer
knowledge required from the (scripted) user."""
import os

from tesla_battery_guru.config import load_settings
from tesla_battery_guru.setup import run_setup


def _scripted(answers):
    it = iter(answers)

    def input_fn(prompt=""):
        return next(it)
    return input_fn


def test_wizard_defaults_write_loadable_config(tmp_path):
    env_path = tmp_path / ".env"
    answers = ["CID123", "SECRET456", "Model Y", "VINY", "",
               "1", "", "1", "", ""]
    run_setup(input_fn=_scripted(answers), out=lambda *_: None,
              env_path=str(env_path))
    text = env_path.read_text()
    assert "TBG_VEHICLES=Model Y=VINY" in text
    assert "TBG_NOMINAL_PACK_KWH=75" in text
    assert "TBG_DAILY_LIMIT_PCT=80" in text
    assert "TBG_AI_MODE=never" in text
    # The written file must load through the real config parser.
    env = {}
    for line in text.splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v
    settings = load_settings(env)
    assert settings.nominal_pack_kwh == 75.0
    assert settings.daily_limit_pct == 80.0
    assert settings.vehicles[0].name == "Model Y"
    assert oct(os.stat(env_path).st_mode & 0o777) == "0o600"


def test_wizard_custom_pack_and_limit(tmp_path):
    env_path = tmp_path / ".env"
    answers = ["CID123", "SECRET456", "Model 3", "VIN3", "",
               "4", "82", "90", "2", "", ""]
    run_setup(input_fn=_scripted(answers), out=lambda *_: None,
              env_path=str(env_path))
    text = env_path.read_text()
    assert "TBG_NOMINAL_PACK_KWH=82" in text
    assert "TBG_DAILY_LIMIT_PCT=90" in text
    assert "TBG_AI_MODE=auto" in text


def test_wizard_keeps_existing_config_when_declined(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("TBG_VEHICLES=Keep=VINKEEP\n")
    run_setup(input_fn=_scripted(["n"]), out=lambda *_: None,
              env_path=str(env_path))
    assert env_path.read_text() == "TBG_VEHICLES=Keep=VINKEEP\n"
