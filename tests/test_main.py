from package_manager.main import main


def test_main_calls_service(monkeypatch):
    captured = {}

    def fake_run_with_builtin_config(name=None, package_id=None, list_packages=False):
        captured["name"] = name
        captured["package_id"] = package_id
        captured["list_packages"] = list_packages
        return 0

    monkeypatch.setattr("package_manager.main.run_with_builtin_config", fake_run_with_builtin_config)
    code = main(["--name", "tiancheng"])
    assert code == 0
    assert captured == {"name": "tiancheng", "package_id": None, "list_packages": False}
