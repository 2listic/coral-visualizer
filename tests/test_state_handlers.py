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


def _make_runtime(**kwargs):
    defaults = dict(
        pv_backend=SimpleNamespace(
            source=object(),
            display=object(),
            apply_coloring=lambda value: None,
            apply_representation=lambda value: None,
            set_active_node=lambda node_id: True,
            set_interactor_rotation=lambda enabled: None,
        ),
        load_file=lambda path: None,
        update_ui_state=lambda: None,
        call_view_update=lambda: None,
        render_and_push=lambda: None,
        sync_edit_session_state=lambda: None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _register(
    state, *, interaction_quality_presets=INTERACTION_QUALITY_PRESETS, **runtime_kwargs
):
    register_state_handlers(
        state,
        paraview_runtime=_make_runtime(**runtime_kwargs),
        interaction_quality_presets=interaction_quality_presets,
    )


def test_selected_file_change_loads_file(tmp_path):
    loaded = []
    state = FakeState(error_message="")
    dataset = tmp_path / "mesh.vtu"
    dataset.write_text("dummy")

    _register(state, load_file=lambda path: loaded.append(path))

    state._handlers["selected_file"](str(dataset))

    assert loaded == [str(dataset)]


def test_selected_file_change_captures_loading_errors(tmp_path):
    state = FakeState(error_message="")
    dataset = tmp_path / "mesh.vtu"
    dataset.write_text("dummy")

    def _fail(path):
        raise RuntimeError("boom")

    _register(state, load_file=_fail)

    state._handlers["selected_file"](str(dataset))

    assert state.error_message == "Error loading file: boom"


def test_array_representation_and_pipeline_callbacks_dispatch():
    calls = []
    pv_backend = SimpleNamespace(
        source=object(),
        display=object(),
        apply_coloring=lambda value: calls.append(("color", value)),
        apply_representation=lambda value: calls.append(("repr", value)),
        set_active_node=lambda node_id: node_id == "node-1",
        set_interactor_rotation=lambda enabled: calls.append(("rotate", enabled)),
    )
    state = FakeState(
        error_message="",
        edit_session_active=False,
        interactive_quality=0,
        interactive_ratio=0,
    )

    _register(
        state,
        pv_backend=pv_backend,
        update_ui_state=lambda: calls.append("update_ui"),
        call_view_update=lambda: calls.append("view_update"),
        render_and_push=lambda: calls.append("render"),
        sync_edit_session_state=lambda: calls.append("sync_edit"),
    )

    state._handlers["selected_array"]("point:U")
    state._handlers["representation"]("Wireframe")
    state._handlers["active_pipeline_item"]("node-1")
    state._handlers["interaction_quality"]("fast")
    # In non-edit mode, even if pick_mode=True, rotation should be ENABLED (True)
    state._handlers["pick_mode"](True, False)

    assert ("color", "point:U") in calls
    assert ("repr", "Wireframe") in calls
    assert ("rotate", True) in calls
    assert "update_ui" in calls
    assert "view_update" in calls
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


def test_pick_mode_in_edit_session_disables_rotation():
    calls = []
    pv_backend = SimpleNamespace(
        set_active_node=lambda node_id: True,
        set_interactor_rotation=lambda enabled: calls.append(("rotate", enabled)),
    )
    state = FakeState(error_message="")

    _register(
        state,
        pv_backend=pv_backend,
        sync_edit_session_state=lambda: calls.append("sync"),
    )

    # edit_session_active=True and pick_mode=True → rotation disabled
    state._handlers["pick_mode"](True, True)

    assert ("rotate", False) in calls
    assert "sync" in calls
