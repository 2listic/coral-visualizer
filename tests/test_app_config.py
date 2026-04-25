import sys

from app_config import configure_app


def test_configure_app_prefers_paraview_when_auto_and_available(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["app.py", "--data-directory", "test_data"])

    config = configure_app(paraview_available=True)

    assert config.backend == "paraview"
    assert config.requested_backend == "auto"
    assert config.backend_message == ""
    assert config.devtools_enabled is True
    assert "--hot-reload" in sys.argv


def test_configure_app_falls_back_when_paraview_requested_but_missing(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["app.py", "--backend", "paraview", "--no-devtools"],
    )

    config = configure_app(paraview_available=False)

    assert config.backend == "vtk"
    assert config.requested_backend == "paraview"
    assert "Falling back to the VTK backend" in config.backend_message
    assert config.devtools_enabled is False
    assert "--hot-reload" not in sys.argv


def test_configure_app_keeps_vtk_backend_explicit(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["app.py", "--backend", "vtk"])

    config = configure_app(paraview_available=True)

    assert config.backend == "vtk"
    assert config.requested_backend == "vtk"
    assert config.backend_message == ""
