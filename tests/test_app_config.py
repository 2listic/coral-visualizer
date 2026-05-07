import sys

from app_config import configure_app


def test_configure_app_defaults(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["app.py", "--data-directory", "test_data"])

    config = configure_app()

    assert config.devtools_enabled is True
    assert "--hot-reload" in sys.argv


def test_configure_app_no_devtools(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["app.py", "--no-devtools"],
    )

    config = configure_app()

    assert config.devtools_enabled is False
    assert "--hot-reload" not in sys.argv


def test_configure_app_hide_experimental_filters(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["app.py", "--hide-experimental-filters", "--no-devtools"],
    )

    config = configure_app()

    assert config.show_experimental_filters is False
