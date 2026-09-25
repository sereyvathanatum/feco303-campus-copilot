import os

import pytest

from campus_copilot import config


def test_placeholder_keys_count_as_missing(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-replace-with-a-real-key")
    monkeypatch.setenv("LAYA_MODE", "sideways")
    settings = config.get_settings("baseline")
    assert settings.run_mode == "offline"
    assert len(settings.notes) == 2  # the NVIDIA placeholder and the unknown LAYA_MODE


def test_run_modes(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-" + "x" * 30)
    assert config.get_settings("baseline").run_mode == "nim"
    monkeypatch.setenv("LAYA_MODE", "http")
    assert config.get_settings("baseline").run_mode == "full"
    assert config.get_settings("offline").run_mode == "offline"


def test_unedited_env_copy_reports_offline(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text((config.REPO_ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("COPILOT_ENV_FILE", str(env))
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("LAYA_API_KEY", raising=False)
    settings = config.get_settings("baseline")
    assert settings.env_file == env
    assert settings.run_mode == "offline"
    os.environ.pop("NVIDIA_API_KEY", None)
    os.environ.pop("LAYA_API_KEY", None)


def test_environment_wins_over_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("NIM_CHAT_MODEL=from-file\n", encoding="utf-8")
    monkeypatch.setenv("COPILOT_ENV_FILE", str(env))
    monkeypatch.setenv("NIM_CHAT_MODEL", "from-environment")
    assert config.get_settings("baseline").chat_model == "from-environment"


def test_fallback_parser(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# comment\nexport A=1\nB="two words"\nC=3 # trailing\n\nD\n', encoding="utf-8")
    assert config._parse_env_file(env) == {"A": "1", "B": "two words", "C": "3"}


def test_init_env_never_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    (tmp_path / ".env.example").write_text("A=1\n", encoding="utf-8")
    path, created = config.init_env_file()
    assert created and path.read_text(encoding="utf-8") == "A=1\n"
    path.write_text("A=edited\n", encoding="utf-8")
    _, created_again = config.init_env_file()
    assert not created_again and path.read_text(encoding="utf-8") == "A=edited\n"


def test_profiles_inherit_from_baseline():
    step = config.load_profile("steps/step-06")
    assert step.capabilities == ("kb", "rag", "memory")
    assert step.get("rag.condense_query") == "always"
    assert step.get("rag.top_k") == config.load_profile("baseline").get("rag.top_k")


def test_every_step_profile_is_cumulative():
    previous: set[str] = set()
    for n in range(1, 13):
        caps = set(config.load_profile(config.step_profile_name(n)).capabilities)
        assert previous <= caps
        previous = caps
    assert previous == set(config.ALL_CAPABILITIES)


def test_unknown_capability_is_rejected():
    profile = config.Profile("x", {"capabilities": ["kb", "teleport"]})
    with pytest.raises(ValueError):
        _ = profile.capabilities


def test_pinned_clock():
    assert config.today().isoformat() == "2026-10-06"
