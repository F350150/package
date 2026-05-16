from package_manager.errors import ConfigError
from package_manager.main import main


def test_main_calls_service(monkeypatch):
    captured = {}

    def fake_run_with_builtin_config(name=None, dry_run=False):
        captured["name"] = name
        captured["dry_run"] = dry_run
        return 0

    monkeypatch.setattr("package_manager.service.run_with_builtin_config", fake_run_with_builtin_config)
    code = main(["--name", "DevKit-Porting-Advisor"])
    assert code == 0
    assert captured == {"name": "DevKit-Porting-Advisor", "dry_run": False}


def test_main_passes_dry_run(monkeypatch):
    captured = {}

    def fake_run_with_builtin_config(name=None, dry_run=False):
        captured["name"] = name
        captured["dry_run"] = dry_run
        return 0

    monkeypatch.setattr("package_manager.service.run_with_builtin_config", fake_run_with_builtin_config)
    code = main(["--name", "DevKit-Porting-Advisor", "--dry-run"])
    assert code == 0
    assert captured == {"name": "DevKit-Porting-Advisor", "dry_run": True}


def test_main_config_error_returns_stable_code(monkeypatch):
    def fail_run_with_builtin_config(**kwargs):
        raise ConfigError("bad config")

    monkeypatch.setattr("package_manager.service.run_with_builtin_config", fail_run_with_builtin_config)
    code = main(["--name", "DevKit-Porting-Advisor"])
    assert code == 10
