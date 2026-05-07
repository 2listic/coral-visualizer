from types import SimpleNamespace

import handler_registration


def _make_paraview_runtime():
    calls = []

    class ParaViewRuntime:
        def render_and_push(self):
            calls.append("render_and_push")

        def refresh_runtime_message(self, *, clear=False):
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

        def apply_coloring(self, value):
            calls.append(("apply_coloring", value))

        def load_file(self, value):
            calls.append(("load_file", value))

        def apply_representation(self, value):
            calls.append(("apply_representation", value))

    return ParaViewRuntime(), calls


def test_register_app_handlers_wires_paraview_runtime(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        handler_registration,
        "register_paraview_controllers",
        lambda *args, **kwargs: captured.setdefault("paraview", kwargs),
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

    paraview_runtime, paraview_calls = _make_paraview_runtime()

    handler_registration.register_app_handlers(
        ctrl=SimpleNamespace(),
        state=SimpleNamespace(),
        runtime=SimpleNamespace(
            pv_backend=SimpleNamespace(),
            edit_session=SimpleNamespace(),
            paraview_runtime=paraview_runtime,
        ),
        file_operations=SimpleNamespace(
            refresh_available_files=lambda: None,
            persist_uploaded_file=lambda client_file: None,
            save_paraview_output=lambda: None,
            save_paraview_state=lambda: None,
            load_paraview_state=lambda: None,
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

    assert set(captured) == {"paraview", "state", "common"}

    captured["state"]["apply_active_representation"]("Wireframe")

    assert ("apply_representation", "Wireframe") in paraview_calls
