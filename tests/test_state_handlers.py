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
        update_color_state=lambda: None,
        call_view_update=lambda: None,
        render_and_push=lambda: None,
        sync_edit_session_state=lambda: None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_edit_session(active=False):
    return SimpleNamespace(active=active)


def _register(
    state,
    *,
    interaction_quality_presets=INTERACTION_QUALITY_PRESETS,
    edit_session=None,
    **runtime_kwargs,
):
    register_state_handlers(
        state,
        paraview_runtime=_make_runtime(**runtime_kwargs),
        edit_session=edit_session or _make_edit_session(),
        interaction_quality_presets=interaction_quality_presets,
    )


def test_selected_file_change_loads_file(tmp_path):
    loaded = []
    state = FakeState(
        notification_message="", notification_type="info", notification_show=False
    )
    dataset = tmp_path / "mesh.vtu"
    dataset.write_text("dummy")

    _register(state, load_file=lambda path: loaded.append(path))

    state._handlers["selected_file"](str(dataset))

    assert loaded == [str(dataset)]


def test_selected_file_change_captures_loading_errors(tmp_path):
    state = FakeState(
        notification_message="", notification_type="info", notification_show=False
    )
    dataset = tmp_path / "mesh.vtu"
    dataset.write_text("dummy")

    def _fail(path):
        raise RuntimeError("boom")

    _register(state, load_file=_fail)

    state._handlers["selected_file"](str(dataset))

    assert state.notification_message == "Error loading file: boom"
    assert state.notification_type == "error"


def test_array_change_uses_targeted_color_flush():
    calls = []
    pv_backend = SimpleNamespace(
        source=object(),
        display=object(),
        apply_coloring=lambda value: calls.append(("color", value)),
        apply_representation=lambda value: None,
        set_active_node=lambda node_id: True,
        set_interactor_rotation=lambda enabled: None,
    )
    state = FakeState(
        notification_message="", notification_type="info", notification_show=False
    )

    _register(
        state,
        pv_backend=pv_backend,
        update_color_state=lambda: calls.append("update_color"),
        update_ui_state=lambda: calls.append("update_ui"),
        call_view_update=lambda: calls.append("view_update"),
    )

    state._handlers["selected_array"]("point:U")

    assert ("color", "point:U") in calls
    assert "update_color" in calls
    assert "view_update" in calls
    # array change must NOT trigger the heavy full-state flush
    assert "update_ui" not in calls


def test_representation_change_uses_full_ui_flush():
    calls = []
    pv_backend = SimpleNamespace(
        source=object(),
        display=object(),
        apply_coloring=lambda value: None,
        apply_representation=lambda value: calls.append(("repr", value)),
        set_active_node=lambda node_id: True,
        set_interactor_rotation=lambda enabled: None,
    )
    state = FakeState(
        notification_message="", notification_type="info", notification_show=False
    )

    _register(
        state,
        pv_backend=pv_backend,
        update_color_state=lambda: calls.append("update_color"),
        update_ui_state=lambda: calls.append("update_ui"),
        call_view_update=lambda: calls.append("view_update"),
    )

    state._handlers["representation"]("Wireframe")

    assert ("repr", "Wireframe") in calls
    assert "update_ui" in calls
    assert "view_update" in calls
    # representation changes display_properties — must NOT use the color-only flush
    assert "update_color" not in calls


def test_pipeline_and_interaction_callbacks_dispatch():
    calls = []
    pv_backend = SimpleNamespace(
        source=object(),
        display=object(),
        apply_coloring=lambda value: None,
        apply_representation=lambda value: None,
        set_active_node=lambda node_id: node_id == "node-1",
        set_interactor_rotation=lambda enabled: calls.append(("rotate", enabled)),
    )
    state = FakeState(
        notification_message="",
        notification_type="info",
        notification_show=False,
        edit_session_active=False,
        interactive_quality=0,
        interactive_ratio=0,
    )

    _register(
        state,
        pv_backend=pv_backend,
        render_and_push=lambda: calls.append("render"),
        sync_edit_session_state=lambda: calls.append("sync_edit"),
    )

    state._handlers["active_pipeline_item"]("node-1")
    state._handlers["interaction_quality"]("fast")
    # In non-edit mode, even if pick_mode=True, rotation should be ENABLED (True)
    state._handlers["pick_mode"](True, False)

    assert ("rotate", True) in calls
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


def test_pipeline_node_switch_blocked_during_edit_session():
    switched = []
    pv_backend = SimpleNamespace(
        source=object(),
        display=object(),
        apply_coloring=lambda v: None,
        apply_representation=lambda v: None,
        set_active_node=lambda node_id: switched.append(node_id) or True,
        set_interactor_rotation=lambda enabled: None,
        active_node_id="node-1",
    )
    state = FakeState(
        notification_message="",
        notification_type="info",
        notification_show=False,
        active_pipeline_item="node-1",
        edit_session_active=True,
        interactive_quality=0,
        interactive_ratio=0,
    )

    _register(
        state,
        pv_backend=pv_backend,
        edit_session=_make_edit_session(active=True),
        render_and_push=lambda: None,
    )

    state._handlers["active_pipeline_item"]("node-2")

    assert switched == [], "set_active_node must not be called during an edit session"
    assert state.notification_show, "a warning notification must be shown"
    assert (
        state.active_pipeline_item == "node-1"
    ), "UI selection must snap back to current node"


def test_pick_mode_in_edit_session_disables_rotation():
    calls = []
    pv_backend = SimpleNamespace(
        set_active_node=lambda node_id: True,
        set_interactor_rotation=lambda enabled: calls.append(("rotate", enabled)),
    )
    state = FakeState(
        notification_message="", notification_type="info", notification_show=False
    )

    _register(
        state,
        pv_backend=pv_backend,
        sync_edit_session_state=lambda: calls.append("sync"),
    )

    # edit_session_active=True and pick_mode=True → rotation disabled
    state._handlers["pick_mode"](True, True)

    assert ("rotate", False) in calls
    assert "sync" in calls
