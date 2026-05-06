from types import SimpleNamespace

from constants import INTERACTION_QUALITY_PRESETS
from state_handlers import register_state_handlers


class FakeState(SimpleNamespace):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._handlers = {}

    def change(self, *names):
        def decorator(fn):
            for name in names:
                self._handlers[name] = fn
            return fn

        return decorator


def test_selected_file_change_loads_paraview_file_and_disables_edit_mode(tmp_path):
    loaded = []
    state = FakeState(edit_mode=True, error_message="")
    dataset = tmp_path / "mesh.vtu"
    dataset.write_text("dummy")

    register_state_handlers(
        state,
        is_paraview_backend=lambda: True,
        load_file_with_paraview_backend=lambda path: loaded.append(("pv", path)),
        load_file_with_vtk_backend=lambda path: loaded.append(("vtk", path)),
        apply_paraview_coloring=lambda value: None,
        apply_vtk_coloring=lambda value: None,
        apply_active_representation=lambda value: None,
        pv_backend=SimpleNamespace(),
        update_paraview_ui_state=lambda: None,
        render_and_push=lambda: None,
        sync_edit_session_state=lambda: None,
        interaction_quality_presets=INTERACTION_QUALITY_PRESETS,
    )

    state._handlers["selected_file"](str(dataset))

    assert state.edit_mode is False
    assert loaded == [("pv", str(dataset))]


def test_selected_file_change_captures_loading_errors(tmp_path):
    state = FakeState(edit_mode=False, error_message="")
    dataset = tmp_path / "mesh.vtu"
    dataset.write_text("dummy")

    register_state_handlers(
        state,
        is_paraview_backend=lambda: False,
        load_file_with_paraview_backend=lambda path: None,
        load_file_with_vtk_backend=lambda path: (_ for _ in ()).throw(
            RuntimeError("boom")
        ),
        apply_paraview_coloring=lambda value: None,
        apply_vtk_coloring=lambda value: None,
        apply_active_representation=lambda value: None,
        pv_backend=SimpleNamespace(),
        update_paraview_ui_state=lambda: None,
        render_and_push=lambda: None,
        sync_edit_session_state=lambda: None,
        interaction_quality_presets=INTERACTION_QUALITY_PRESETS,
    )

    state._handlers["selected_file"](str(dataset))

    assert state.error_message == "Error loading file: boom"


def test_array_representation_and_pipeline_callbacks_dispatch_to_expected_runtime():
    calls = []
    pv_backend = SimpleNamespace(
        set_active_node=lambda node_id: node_id == "node-1",
        set_interactor_rotation=lambda enabled: calls.append(("rotate", enabled)),
    )
    state = FakeState(
        edit_mode=False,
        edit_session_active=False,
        error_message="",
        interactive_quality=0,
        interactive_ratio=0,
    )

    register_state_handlers(
        state,
        is_paraview_backend=lambda: True,
        load_file_with_paraview_backend=lambda path: None,
        load_file_with_vtk_backend=lambda path: None,
        apply_paraview_coloring=lambda value: calls.append(("pv_color", value)),
        apply_vtk_coloring=lambda value: calls.append(("vtk_color", value)),
        apply_active_representation=lambda value: calls.append(("repr", value)),
        pv_backend=pv_backend,
        update_paraview_ui_state=lambda: calls.append("update_ui"),
        render_and_push=lambda: calls.append("render"),
        sync_edit_session_state=lambda: calls.append("sync_edit"),
        interaction_quality_presets=INTERACTION_QUALITY_PRESETS,
    )

    state._handlers["selected_array"]("point:U")
    state._handlers["representation"]("Wireframe")
    state._handlers["active_pipeline_item"]("node-1")
    state._handlers["interaction_quality"]("fast")
    # In non-edit mode, even if pick_mode=True, rotation should be ENABLED (True)
    state._handlers["pick_mode"](True, False)

    assert ("pv_color", "point:U") in calls
    assert ("repr", "Wireframe") in calls
    assert ("rotate", True) in calls
    assert "update_ui" in calls
    assert "render" in calls
    assert "sync_edit" in calls
    assert (
        state.interactive_quality
        == INTERACTION_QUALITY_PRESETS["fast"]["interactive_quality"]
    )
    assert (
        state.interactive_ratio
        == INTERACTION_QUALITY_PRESETS["fast"]["interactive_ratio"]
    )


def test_pick_mode_ignored_outside_paraview():
    calls = []
    pv_backend = SimpleNamespace(
        set_interactor_rotation=lambda enabled: calls.append(enabled)
    )
    state = FakeState(edit_mode=False, error_message="")

    register_state_handlers(
        state,
        is_paraview_backend=lambda: False,
        load_file_with_paraview_backend=lambda path: None,
        load_file_with_vtk_backend=lambda path: None,
        apply_paraview_coloring=lambda value: None,
        apply_vtk_coloring=lambda value: None,
        apply_active_representation=lambda value: None,
        pv_backend=pv_backend,
        update_paraview_ui_state=lambda: None,
        render_and_push=lambda: None,
        sync_edit_session_state=lambda: calls.append("sync"),
        interaction_quality_presets=INTERACTION_QUALITY_PRESETS,
    )

    state._handlers["pick_mode"](False, False)

    assert calls == ["sync"]
