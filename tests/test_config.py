from pathlib import Path

import pytest

from cvforge.config import Config, ConfigError, load_config


def test_env_overrides(tmp_path):
    c = load_config(env={"CVFORGE_DATA_DIR": str(tmp_path), "CVFORGE_LUALATEX": "/x/lualatex"}, file=None)
    assert c.data_dir == tmp_path and c.lualatex == "/x/lualatex"


def test_file_used_when_no_env(tmp_path):
    f = tmp_path / "cvforge.toml"
    f.write_text('[cvforge]\nbuild_dir = "/mnt/d/b"\n')
    assert load_config(env={}, file=f).build_dir == Path("/mnt/d/b")


def test_env_beats_file(tmp_path):
    f = tmp_path / "cvforge.toml"
    f.write_text('[cvforge]\nxelatex = "/from/file"\n')
    c = load_config(env={"CVFORGE_XELATEX": "/from/env"}, file=f)
    assert c.xelatex == "/from/env"


def test_defaults_are_typed(tmp_path):
    c = load_config(env={}, file=tmp_path / "missing.toml")
    assert isinstance(c, Config)
    assert c.data_dir.name == "data"
    assert isinstance(c.lualatex, str) and isinstance(c.xelatex, str)
    assert c.build_dir.name in {"cv-forge-build", "build"}


def test_daily_cap_default_and_override(tmp_path):
    assert load_config(env={}, file=tmp_path / "missing.toml").daily_cap == 10
    assert load_config(env={"CVFORGE_DAILY_CAP": "3"}, file=None).daily_cap == 3


def test_bad_config_values_are_clean_cli_errors(tmp_path, monkeypatch, capsys):
    from cvforge.cli import main

    monkeypatch.setenv("CVFORGE_DATA_DIR", str(tmp_path))
    for key, value in (("CVFORGE_DAILY_CAP", "ten"), ("CVFORGE_CLT_FACTOR", "abc")):
        monkeypatch.setenv(key, value)
        assert main(["due"]) == 1
        err = capsys.readouterr().err
        assert key.removeprefix("CVFORGE_").lower() in err and value in err
        monkeypatch.delenv(key)


def test_bad_toml_is_a_config_error(tmp_path):
    import pytest

    from cvforge.config import ConfigError
    f = tmp_path / "cvforge.toml"
    f.write_text("[cvforge\n")
    with pytest.raises(ConfigError, match="cvforge.toml"):
        load_config(env={}, file=f)


def test_config_serve_port(tmp_path):
    assert load_config(env={}, file=tmp_path / "missing.toml").serve_port == 47321
    assert load_config(env={"CVFORGE_SERVE_PORT": "5000"}, file=None).serve_port == 5000
    for bad in ("abc", "70000", "-1"):
        with pytest.raises(ConfigError):
            load_config(env={"CVFORGE_SERVE_PORT": bad}, file=None)


def test_gupy_keywords_config(tmp_path):
    assert load_config(env={"CVFORGE_GUPY_KEYWORDS": "react, vue,, "}, file=None).gupy_keywords == ("react", "vue")
    assert load_config(env={}, file=tmp_path / "none.toml").gupy_keywords == (
        "react", "node", "full stack", "typescript")
    f = tmp_path / "cvforge.toml"
    f.write_text('[cvforge]\ngupy_keywords = ["go", "rust"]\n')
    assert load_config(env={}, file=f).gupy_keywords == ("go", "rust")
    f.write_text('[cvforge]\ngupy_keywords = "go"\n')
    with pytest.raises(ConfigError):
        load_config(env={}, file=f)


def test_gupy_keywords_empty_env_falls_back():
    default = ("react", "node", "full stack", "typescript")
    assert load_config(env={"CVFORGE_GUPY_KEYWORDS": " , ,"}, file=None).gupy_keywords == default


def test_gupy_keywords_non_string_toml(tmp_path):
    f = tmp_path / "cvforge.toml"
    f.write_text('[cvforge]\ngupy_keywords = ["go", 3]\n')
    with pytest.raises(ConfigError):
        load_config(env={}, file=f)
