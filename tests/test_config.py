"""Config parsing: vehicles, 12-hour times, pack size, limits, AI mode."""
import pytest

from tesla_battery_guru.config import (ConfigError, format_12h_time,
                                       load_settings, parse_12h_time)


def test_defaults_load():
    s = load_settings({})
    assert s.server_port == 8649
    assert s.nominal_pack_kwh == 75.0
    assert s.daily_limit_pct == 80.0
    assert s.ai_mode == "auto"
    assert s.model_id == "tesla-battery-guru"


def test_vehicles_parsed():
    s = load_settings({"TBG_VEHICLES": "Model Y=VINY,Model 3=VIN3"})
    assert [(v.name, v.vin) for v in s.vehicles] == [("Model Y", "VINY"),
                                                     ("Model 3", "VIN3")]


def test_bad_pack_size_rejected():
    with pytest.raises(ConfigError):
        load_settings({"TBG_NOMINAL_PACK_KWH": "5"})
    with pytest.raises(ConfigError):
        load_settings({"TBG_NOMINAL_PACK_KWH": "abc"})


def test_bad_daily_limit_rejected():
    with pytest.raises(ConfigError):
        load_settings({"TBG_DAILY_LIMIT_PCT": "120"})
    with pytest.raises(ConfigError):
        load_settings({"TBG_DAILY_LIMIT_PCT": "40"})


def test_bad_region_and_ai_mode_rejected():
    with pytest.raises(ConfigError):
        load_settings({"TESLA_REGION": "xx"})
    with pytest.raises(ConfigError):
        load_settings({"TBG_AI_MODE": "sometimes"})


def test_bad_embedding_dim_rejected():
    with pytest.raises(ConfigError):
        load_settings({"TBG_EMBEDDING_DIM": "2"})


def test_12h_times():
    assert parse_12h_time("4:00 PM") == 16 * 60
    assert parse_12h_time("12:00 AM") == 0
    assert parse_12h_time("12:30 PM") == 12 * 60 + 30
    assert format_12h_time(16 * 60) == "4:00 PM"
    assert format_12h_time(0) == "12:00 AM"
    with pytest.raises(ConfigError):
        parse_12h_time("16:00")
    with pytest.raises(ConfigError):
        parse_12h_time("13:00 PM")
