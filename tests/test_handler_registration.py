from types import SimpleNamespace

import handler_registration


def _make_runtime():
    calls = []

    class Runtime:
        viz = "vtk-viz"
        active_lut = "vtk-lut"

        def render_and_push(self):
            calls.append("render_and_push")

        def refresh_runtime_message(self):
            calls.append("refresh_runtime_message")

        def update_ui_state(self):
            calls.append("update_ui_state")

        def sync_edit_session_state(self):
            calls.append("sync_edit_session_state")

        def normalize_edit_selection_ids(self, ids):
            calls.append(("normalize_edit_selection_ids", ids))
            return ids

        def sync_edit_selection_overlay(self):
            calls.append("sync_edit_selection_overlay")

        def summarize_edit_event(self, event):
            calls.append(("summarize_edit_event", event))
            return "summary"

        def apply_edit_coloring(self):
            calls.append("apply_edit_coloring")

        def update_scalar_bars(self):
            calls.append("update_scalar_bars")

        def apply_coloring(self, value):
            calls.append(("apply_coloring", value))

        def load_file(self, value):
            calls.append(("load_file", value))

        def reset_camera(self):
            calls.append("reset_camera")

        def reset_view(self):
            calls.append("reset_view")

        def apply_representation(self, value):
            calls.append(("apply_representation", value))

    return Runtime(), calls


def test_register_app_handlers_wires_paraview_runtime(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        handler_registration,
        "register_paraview_controllers",
        lambda *args, **kwargs: captured.setdefault("paraview", kwargs),
    )
    monkeypatch.setattr(
        handler_registration,
        "register_vtk_handlers",
        lambda *args, **kwargs: captured.setdefault("vtk", kwargs),
    )
    monkeypatch.setattr(
        handler_registration,
        "register_state_handlers",
        lambda *args, **kwargs: captured.setdefault("state", kwargs),
    )
    monkeypatch.setattr(
        handler_registration,
        "register_common_controllers",
        lambda *args, **kwargs: captured.setdefault("common", kwargs),
    )

    vtk_runtime, vtk_calls = _make_runtime()
    paraview_runtime, paraview_calls = _make_runtime()

    handler_registration.register_app_handlers(
        ctrl=SimpleNamespace(),
        state=SimpleNamespace(),
        runtime=SimpleNamespace(
            backend="paraview",
            data_directory="/tmp/data",
            pv_backend=SimpleNamespace(),
            edit_session=SimpleNamespace(),
            edit_state=SimpleNamespace(),
            pick_interactor=SimpleNamespace(),
            vtk_runtime=vtk_runtime,
            paraview_runtime=paraview_runtime,
        ),
        edit_operations=handler_registration.EditOperations(
            update_selection_actor=lambda: None,
            assign_id_to_selection=lambda *_: None,
            save_as_vtu=lambda *_: None,
        ),
        file_operations=SimpleNamespace(
            refresh_available_files=lambda: None,
            persist_uploaded_file=lambda client_file: None,
            save_paraview_output=lambda: None,
            persist_uploaded_state_file=lambda client_file: None,
            refresh_available_state_files=lambda: None,
        ),
        interaction_quality_presets={"high": {"interactive_quality": 95}},
        view_controls=SimpleNamespace(
            debug=lambda *args, **kwargs: None,
            update=lambda *args, **kwargs: None,
            update_geometry=lambda *args, **kwargs: None,
            set_remote_rendering=lambda enabled: None,
        ),
    )

    assert set(captured) == {"paraview", "vtk", "state", "common"}
    assert captured["paraview"]["is_paraview_backend"]() is True
    assert captured["vtk"]["is_vtk_backend"]() is False
    assert captured["vtk"]["viz_getter"]() == "vtk-viz"
    assert captured["vtk"]["active_lut_getter"]() == "vtk-lut"

    captured["state"]["apply_active_representation"]("Wireframe")

    assert ("apply_representation", "Wireframe") in paraview_calls
    assert "render_and_push" not in vtk_calls
    assert "render_and_push" not in paraview_calls


def test_register_app_handlers_falls_back_to_vtk_runtime(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        handler_registration,
        "register_paraview_controllers",
        lambda *args, **kwargs: captured.setdefault("paraview", kwargs),
    )
    monkeypatch.setattr(
        handler_registration,
        "register_vtk_handlers",
        lambda *args, **kwargs: captured.setdefault("vtk", kwargs),
    )
    monkeypatch.setattr(
        handler_registration,
        "register_state_handlers",
        lambda *args, **kwargs: captured.setdefault("state", kwargs),
    )
    monkeypatch.setattr(
        handler_registration,
        "register_common_controllers",
        lambda *args, **kwargs: captured.setdefault("common", kwargs),
    )

    vtk_runtime, vtk_calls = _make_runtime()

    handler_registration.register_app_handlers(
        ctrl=SimpleNamespace(),
        state=SimpleNamespace(),
        runtime=SimpleNamespace(
            backend="vtk",
            data_directory="/tmp/data",
            pv_backend=None,
            edit_session=SimpleNamespace(),
            edit_state=SimpleNamespace(),
            pick_interactor=SimpleNamespace(),
            vtk_runtime=vtk_runtime,
            paraview_runtime=None,
        ),
        edit_operations=handler_registration.EditOperations(
            update_selection_actor=lambda: None,
            assign_id_to_selection=lambda *_: None,
            save_as_vtu=lambda *_: None,
        ),
        file_operations=SimpleNamespace(
            refresh_available_files=lambda: None,
            persist_uploaded_file=lambda client_file: None,
            save_paraview_output=lambda: None,
            persist_uploaded_state_file=lambda client_file: None,
            refresh_available_state_files=lambda: None,
        ),
        interaction_quality_presets={"high": {"interactive_quality": 95}},
        view_controls=SimpleNamespace(
            debug=lambda *args, **kwargs: None,
            update=lambda *args, **kwargs: None,
            update_geometry=lambda *args, **kwargs: None,
            set_remote_rendering=lambda enabled: None,
        ),
    )

    assert captured["paraview"]["refresh_runtime_message"] is handler_registration._noop
    assert captured["state"]["is_paraview_backend"]() is False
    assert captured["common"]["is_paraview_backend"]() is False

    captured["state"]["apply_active_representation"]("Points")

    assert ("apply_representation", "Points") in vtk_calls
    assert "render_and_push" in vtk_calls
