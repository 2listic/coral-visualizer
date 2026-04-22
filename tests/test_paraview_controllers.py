from types import SimpleNamespace

from paraview_controllers import register_paraview_controllers
from paraview_runtime import ParaViewRuntime


class FakeCtrl:
    def __init__(self):
        self.handlers = {}

    def add(self, name):
        def decorator(fn):
            self.handlers[name] = fn
            return fn

        return decorator


def test_pv_update_property_updates_pending_value_and_dirty_flag():
    ctrl = FakeCtrl()
    state = SimpleNamespace(
        source_properties=[{"name": "Opacity", "pending_value": 1.0}],
        display_properties=[{"name": "LineWidth", "pending_value": 1.0}],
        pv_properties_dirty=False,
    )

    register_paraview_controllers(
        ctrl,
        state,
        is_paraview_backend=lambda: True,
        pv_backend=SimpleNamespace(),
        edit_session=SimpleNamespace(),
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        render_and_push=lambda: None,
        save_paraview_output=lambda: None,
        debug_view=lambda *args, **kwargs: None,
        call_view_update_geometry=lambda **kwargs: None,
        call_view_set_remote_rendering=lambda enabled: None,
        call_view_update=lambda **kwargs: None,
        sync_edit_session_state=lambda: None,
        sync_paraview_edit_selection_overlay=lambda: None,
        summarize_edit_event=lambda event: "",
        normalize_edit_selection_ids=lambda ids: ids,
    )

    ctrl.handlers["pv_update_property"]("source", "Opacity", 0.5)
    ctrl.handlers["pv_update_property"]("display", "LineWidth", 3.0)

    assert state.source_properties == [{"name": "Opacity", "pending_value": 0.5}]
    assert state.display_properties == [{"name": "LineWidth", "pending_value": 3.0}]
    assert state.pv_properties_dirty is True


def test_pv_apply_and_reset_properties_refresh_ui_and_render():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        source_properties=[{"name": "ScaleFactor"}],
        display_properties=[{"name": "Opacity"}],
    )
    pv_backend = SimpleNamespace(
        apply_property_changes=lambda source, display: calls.append(
            ("apply_property_changes", source, display)
        )
    )

    register_paraview_controllers(
        ctrl,
        state,
        is_paraview_backend=lambda: True,
        pv_backend=pv_backend,
        edit_session=SimpleNamespace(),
        refresh_runtime_message=lambda **kwargs: calls.append(("runtime", kwargs)),
        update_paraview_ui_state=lambda: calls.append("update_ui"),
        render_and_push=lambda: calls.append("render"),
        save_paraview_output=lambda: None,
        debug_view=lambda *args, **kwargs: None,
        call_view_update_geometry=lambda **kwargs: None,
        call_view_set_remote_rendering=lambda enabled: None,
        call_view_update=lambda **kwargs: None,
        sync_edit_session_state=lambda: None,
        sync_paraview_edit_selection_overlay=lambda: None,
        summarize_edit_event=lambda event: "",
        normalize_edit_selection_ids=lambda ids: ids,
    )

    ctrl.handlers["pv_apply_properties"]()
    ctrl.handlers["pv_reset_properties"]()

    assert calls[0] == ("runtime", {"clear": True})
    assert calls[1][0] == "apply_property_changes"
    assert calls[2] == ("runtime", {})
    assert "update_ui" in calls
    assert "render" in calls


def test_pv_toggle_visibility_for_and_save_errors_update_state():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        active_pipeline_item="node-1",
        active_visibility=True,
        save_status="",
        save_status_type="info",
    )
    pv_backend = SimpleNamespace(
        get_visibility=lambda node_id: True if node_id == "node-1" else None,
        set_visibility=lambda node_id, visible: calls.append((node_id, visible)),
    )

    register_paraview_controllers(
        ctrl,
        state,
        is_paraview_backend=lambda: True,
        pv_backend=pv_backend,
        edit_session=SimpleNamespace(),
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: calls.append("update_ui"),
        render_and_push=lambda: calls.append("render"),
        save_paraview_output=lambda: (_ for _ in ()).throw(RuntimeError("cannot save")),
        debug_view=lambda *args, **kwargs: None,
        call_view_update_geometry=lambda **kwargs: None,
        call_view_set_remote_rendering=lambda enabled: None,
        call_view_update=lambda **kwargs: None,
        sync_edit_session_state=lambda: None,
        sync_paraview_edit_selection_overlay=lambda: None,
        summarize_edit_event=lambda event: "",
        normalize_edit_selection_ids=lambda ids: ids,
    )

    ctrl.handlers["pv_toggle_visibility_for"]("node-1")
    ctrl.handlers["pv_save_active_data"]()

    assert calls[:3] == [("node-1", False), "update_ui", "render"]
    assert state.save_status == "Error: cannot save"
    assert state.save_status_type == "error"


def test_pv_delete_active_clears_selected_file_when_pipeline_becomes_empty():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        active_pipeline_item="node-1",
        selected_file="/tmp/data/mesh.vtk",
        save_status="old",
    )
    pv_backend = SimpleNamespace(
        delete_node=lambda node_id: calls.append(("delete", node_id))
    )

    def update_ui_state():
        state.active_pipeline_item = None
        calls.append("update_ui")

    register_paraview_controllers(
        ctrl,
        state,
        is_paraview_backend=lambda: True,
        pv_backend=pv_backend,
        edit_session=SimpleNamespace(),
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=update_ui_state,
        render_and_push=lambda: calls.append("render"),
        save_paraview_output=lambda: None,
        debug_view=lambda *args, **kwargs: None,
        call_view_update_geometry=lambda **kwargs: None,
        call_view_set_remote_rendering=lambda enabled: None,
        call_view_update=lambda **kwargs: None,
        sync_edit_session_state=lambda: None,
        sync_paraview_edit_selection_overlay=lambda: None,
        summarize_edit_event=lambda event: "",
        normalize_edit_selection_ids=lambda ids: ids,
    )

    ctrl.handlers["pv_delete_active"]()

    assert calls == [("delete", "node-1"), "update_ui", "render"]
    assert state.selected_file == ""
    assert state.save_status == ""


def test_pv_add_filter_success_and_failure_paths():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        active_pipeline_item="node-1",
        filter_menu=True,
        error_message="",
    )

    backend_success = SimpleNamespace(add_filter=lambda key: calls.append(("add_filter", key)))

    register_paraview_controllers(
        ctrl,
        state,
        is_paraview_backend=lambda: True,
        pv_backend=backend_success,
        edit_session=SimpleNamespace(),
        refresh_runtime_message=lambda **kwargs: calls.append(("runtime", kwargs)),
        update_paraview_ui_state=lambda: calls.append("update_ui"),
        render_and_push=lambda: calls.append("render"),
        save_paraview_output=lambda: None,
        debug_view=lambda *args, **kwargs: None,
        call_view_update_geometry=lambda **kwargs: None,
        call_view_set_remote_rendering=lambda enabled: None,
        call_view_update=lambda **kwargs: None,
        sync_edit_session_state=lambda: None,
        sync_paraview_edit_selection_overlay=lambda: None,
        summarize_edit_event=lambda event: "",
        normalize_edit_selection_ids=lambda ids: ids,
    )

    ctrl.handlers["pv_add_filter"]("clip")

    assert state.filter_menu is False
    assert calls[:4] == [
        ("runtime", {"clear": True}),
        ("add_filter", "clip"),
        ("runtime", {}),
        "update_ui",
    ]
    assert "render" in calls

    state.filter_menu = True
    failing_backend = SimpleNamespace(
        add_filter=lambda key: (_ for _ in ()).throw(RuntimeError("bad filter"))
    )

    register_paraview_controllers(
        ctrl,
        state,
        is_paraview_backend=lambda: True,
        pv_backend=failing_backend,
        edit_session=SimpleNamespace(),
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        render_and_push=lambda: None,
        save_paraview_output=lambda: None,
        debug_view=lambda *args, **kwargs: None,
        call_view_update_geometry=lambda **kwargs: None,
        call_view_set_remote_rendering=lambda enabled: None,
        call_view_update=lambda **kwargs: None,
        sync_edit_session_state=lambda: None,
        sync_paraview_edit_selection_overlay=lambda: None,
        summarize_edit_event=lambda event: "",
        normalize_edit_selection_ids=lambda ids: ids,
    )

    ctrl.handlers["pv_add_filter"]("clip")

    assert state.error_message == "Error adding filter: bad filter"


def test_pv_apply_edit_field_existing_name_opens_overwrite_dialog():
    ctrl = FakeCtrl()
    state = SimpleNamespace(
        edit_geometry_mode="volume",
        edit_field_name="A field",
        edit_expression="",
        edit_default_value="1.5",
        edit_apply_status="",
        edit_apply_status_type="info",
        edit_overwrite_dialog=False,
        edit_overwrite_field_name="",
    )
    edit_session = SimpleNamespace(
        active=True,
        geometry_mode="",
        field_name="",
        expression="",
        default_value="",
        has_cell_field=lambda name: name == "A field",
        apply_volume_field=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("apply_volume_field should not run before overwrite confirm")
        ),
        selected_count=lambda: 0,
    )
    sync_calls = []

    register_paraview_controllers(
        ctrl,
        state,
        is_paraview_backend=lambda: True,
        pv_backend=SimpleNamespace(),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        render_and_push=lambda: None,
        save_paraview_output=lambda: None,
        debug_view=lambda *args, **kwargs: None,
        call_view_update_geometry=lambda **kwargs: None,
        call_view_set_remote_rendering=lambda enabled: None,
        call_view_update=lambda **kwargs: None,
        sync_edit_session_state=lambda: sync_calls.append("sync"),
        sync_paraview_edit_selection_overlay=lambda: None,
        summarize_edit_event=lambda event: "",
        normalize_edit_selection_ids=lambda ids: ids,
    )

    ctrl.handlers["pv_apply_edit_field"]()

    assert state.edit_overwrite_dialog is True
    assert state.edit_overwrite_field_name == "A field"
    assert state.edit_apply_status_type == "warning"
    assert "already exists" in state.edit_apply_status
    assert sync_calls == ["sync"]


def test_pv_confirm_overwrite_edit_field_applies_with_overwrite_true():
    ctrl = FakeCtrl()
    state = SimpleNamespace(
        edit_geometry_mode="volume",
        edit_field_name="A field",
        edit_expression="",
        edit_default_value="2.5",
        edit_apply_status="",
        edit_apply_status_type="info",
        edit_overwrite_dialog=True,
        edit_overwrite_field_name="A field",
    )
    calls = []

    def apply_volume_field(field_name, expression, default_value, overwrite=False):
        calls.append((field_name, expression, default_value, overwrite))
        return field_name

    edit_session = SimpleNamespace(
        active=True,
        geometry_mode="",
        field_name="",
        expression="",
        default_value="",
        has_cell_field=lambda name: True,
        apply_volume_field=apply_volume_field,
        selected_count=lambda: 3,
    )

    register_paraview_controllers(
        ctrl,
        state,
        is_paraview_backend=lambda: True,
        pv_backend=SimpleNamespace(),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        render_and_push=lambda: None,
        save_paraview_output=lambda: None,
        debug_view=lambda *args, **kwargs: None,
        call_view_update_geometry=lambda **kwargs: None,
        call_view_set_remote_rendering=lambda enabled: None,
        call_view_update=lambda **kwargs: None,
        sync_edit_session_state=lambda: None,
        sync_paraview_edit_selection_overlay=lambda: None,
        summarize_edit_event=lambda event: "",
        normalize_edit_selection_ids=lambda ids: ids,
    )

    ctrl.handlers["pv_confirm_overwrite_edit_field"]()

    assert calls == [("A field", "", "2.5", True)]
    assert state.edit_overwrite_dialog is False
    assert state.edit_overwrite_field_name == ""
    assert state.edit_apply_status_type == "success"
    assert "Updated cell field 'A field'" in state.edit_apply_status


def test_pv_apply_edit_field_surface_mode_materializes_selection():
    ctrl = FakeCtrl()
    state = SimpleNamespace(
        edit_geometry_mode="surface",
        edit_field_name="ignored",
        edit_expression="",
        edit_default_value="0",
        edit_apply_status="",
        edit_apply_status_type="info",
        edit_overwrite_dialog=False,
        edit_overwrite_field_name="",
    )
    edit_session = SimpleNamespace(
        active=True,
        geometry_mode="",
        field_name="",
        expression="",
        default_value="",
        materialize_surface_selection=lambda: 2,
    )

    register_paraview_controllers(
        ctrl,
        state,
        is_paraview_backend=lambda: True,
        pv_backend=SimpleNamespace(),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        render_and_push=lambda: None,
        save_paraview_output=lambda: None,
        debug_view=lambda *args, **kwargs: None,
        call_view_update_geometry=lambda **kwargs: None,
        call_view_set_remote_rendering=lambda enabled: None,
        call_view_update=lambda **kwargs: None,
        sync_edit_session_state=lambda: None,
        sync_paraview_edit_selection_overlay=lambda: None,
        summarize_edit_event=lambda event: "",
        normalize_edit_selection_ids=lambda ids: ids,
    )

    ctrl.handlers["pv_apply_edit_field"]()

    assert edit_session.geometry_mode == "surface"
    assert state.edit_apply_status_type == "success"
    assert "Added 2 missing surface cell(s)" in state.edit_apply_status


def test_surface_mode_selection_keeps_surface_mode_after_sync():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        pick_mode=True,
        group_select=False,
        selection_count=0,
        edit_selection_event="",
        edit_selection_status="",
        edit_selection_status_type="info",
        selection_behavior="touch",
        edit_selection_mode="replace",
        edit_geometry_mode="surface",
        edit_view_style="width: 100%; height: 100%; cursor: crosshair; outline: none;",
    )
    edit_session = SimpleNamespace(active=True, geometry_mode="volume")
    edit_session.replace_selection = lambda ids, grow=False: 2
    edit_session.add_selection = lambda ids, grow=False: 2
    edit_session.subtract_selection = lambda ids, grow=False: 0
    edit_session.flip_selection = lambda ids, grow=False: 2

    def sync_from_session():
        state.edit_geometry_mode = edit_session.geometry_mode
        calls.append("sync")

    register_paraview_controllers(
        ctrl,
        state,
        is_paraview_backend=lambda: True,
        pv_backend=SimpleNamespace(
            pick_visible_cell_ids_in_rect=lambda *args, **kwargs: [11, 12]
        ),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        render_and_push=lambda: calls.append("render"),
        save_paraview_output=lambda: None,
        debug_view=lambda *args, **kwargs: None,
        call_view_update_geometry=lambda **kwargs: None,
        call_view_set_remote_rendering=lambda enabled: None,
        call_view_update=lambda **kwargs: None,
        sync_edit_session_state=sync_from_session,
        sync_paraview_edit_selection_overlay=lambda: calls.append("overlay"),
        summarize_edit_event=lambda event: "summary",
        normalize_edit_selection_ids=lambda event: [],
    )

    ctrl.handlers["pv_edit_box_selection"]({"selection": [1, 2, 3, 4]})

    assert edit_session.geometry_mode == "surface"
    assert state.edit_geometry_mode == "surface"
    assert calls == ["sync", "overlay", "render"]


def test_pv_edit_box_selection_uses_explicit_selection_mode_from_state():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        pick_mode=True,
        group_select=False,
        selection_count=0,
        edit_selection_event="",
        edit_selection_status="",
        edit_selection_status_type="info",
        selection_behavior="touch",
        edit_selection_mode="add",
        edit_view_style="width: 100%; height: 100%; cursor: crosshair; outline: none;",
    )
    actions = []
    edit_session = SimpleNamespace(active=True)
    edit_session.replace_selection = (
        lambda ids, grow=False: actions.append(("replace", list(ids), grow)) or 2
    )
    edit_session.add_selection = (
        lambda ids, grow=False: actions.append(("add", list(ids), grow)) or 5
    )
    edit_session.subtract_selection = (
        lambda ids, grow=False: actions.append(("subtract", list(ids), grow)) or 3
    )

    register_paraview_controllers(
        ctrl,
        state,
        is_paraview_backend=lambda: True,
        pv_backend=SimpleNamespace(
            pick_visible_cell_ids_in_rect=lambda *args, **kwargs: [11, 12]
        ),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        render_and_push=lambda: calls.append("render"),
        save_paraview_output=lambda: None,
        debug_view=lambda *args, **kwargs: None,
        call_view_update_geometry=lambda **kwargs: None,
        call_view_set_remote_rendering=lambda enabled: None,
        call_view_update=lambda **kwargs: None,
        sync_edit_session_state=lambda: calls.append("sync"),
        sync_paraview_edit_selection_overlay=lambda: calls.append("overlay"),
        summarize_edit_event=lambda event: "summary",
        normalize_edit_selection_ids=lambda event: [],
    )

    ctrl.handlers["pv_edit_box_selection"]({"selection": [1, 2, 3, 4]})

    assert actions == [("add", [11, 12], False)]
    assert calls == ["sync", "overlay", "render"]
    assert state.selection_count == 5
    assert state.edit_selection_mode == "add"
    assert state.edit_selection_status == "Added 2 cell(s) with box selection. 5 selected total."


def test_pv_edit_click_selection_uses_coordinates_and_updates_overlay():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        pick_mode=True,
        group_select=False,
        selection_count=0,
        edit_selection_event="",
        edit_selection_status="",
        edit_selection_status_type="info",
        selection_behavior="touch",
        edit_selection_mode="replace",
        edit_view_style="width: 100%; height: 100%; cursor: crosshair; outline: none;",
    )
    actions = []
    edit_session = SimpleNamespace(active=True)
    edit_session.replace_selection = (
        lambda ids, grow=False: actions.append(("replace", list(ids), grow)) or 1
    )
    edit_session.add_selection = (
        lambda ids, grow=False: actions.append(("add", list(ids), grow)) or 1
    )
    edit_session.subtract_selection = (
        lambda ids, grow=False: actions.append(("subtract", list(ids), grow)) or 0
    )
    edit_session.flip_selection = (
        lambda ids, grow=False: actions.append(("flip", list(ids), grow)) or 1
    )

    register_paraview_controllers(
        ctrl,
        state,
        is_paraview_backend=lambda: True,
        pv_backend=SimpleNamespace(
            pick_visible_cell_ids=lambda x, y: [41] if (x, y) == (12, 34) else []
        ),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        render_and_push=lambda: calls.append("render"),
        save_paraview_output=lambda: None,
        debug_view=lambda *args, **kwargs: None,
        call_view_update_geometry=lambda **kwargs: None,
        call_view_set_remote_rendering=lambda enabled: None,
        call_view_update=lambda **kwargs: None,
        sync_edit_session_state=lambda: calls.append("sync"),
        sync_paraview_edit_selection_overlay=lambda: calls.append("overlay"),
        summarize_edit_event=lambda event: "summary",
        normalize_edit_selection_ids=lambda event: [("coords", 12, 34)],
    )

    ctrl.handlers["pv_edit_click_selection"]({"position": {"x": 12, "y": 34}})

    assert actions == [("replace", [41], False)]
    assert calls == ["sync", "overlay", "render"]
    assert state.selection_count == 1
    assert state.edit_selection_status == "Selected 1 cell(s) with click selection. 1 selected total."


def test_pv_edit_box_selection_applies_replace_add_and_subtract_modes():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        pick_mode=True,
        group_select=False,
        selection_count=0,
        edit_selection_event="",
        edit_selection_status="",
        edit_selection_status_type="info",
        selection_behavior="touch",
        edit_selection_mode="replace",
        edit_view_style="width: 100%; height: 100%; cursor: crosshair; outline: none;",
    )
    actions = []
    edit_session = SimpleNamespace(active=True)
    edit_session.replace_selection = (
        lambda ids, grow=False: actions.append(("replace", list(ids), grow)) or 2
    )
    edit_session.add_selection = (
        lambda ids, grow=False: actions.append(("add", list(ids), grow)) or 5
    )
    edit_session.subtract_selection = (
        lambda ids, grow=False: actions.append(("subtract", list(ids), grow)) or 3
    )
    edit_session.flip_selection = (
        lambda ids, grow=False: actions.append(("flip", list(ids), grow)) or 4
    )

    register_paraview_controllers(
        ctrl,
        state,
        is_paraview_backend=lambda: True,
        pv_backend=SimpleNamespace(
            pick_visible_cell_ids_in_rect=lambda *args, **kwargs: [11, 12]
        ),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        render_and_push=lambda: calls.append("render"),
        save_paraview_output=lambda: None,
        debug_view=lambda *args, **kwargs: None,
        call_view_update_geometry=lambda **kwargs: None,
        call_view_set_remote_rendering=lambda enabled: None,
        call_view_update=lambda **kwargs: None,
        sync_edit_session_state=lambda: calls.append("sync"),
        sync_paraview_edit_selection_overlay=lambda: calls.append("overlay"),
        summarize_edit_event=lambda event: "summary",
        normalize_edit_selection_ids=lambda event: [],
    )

    ctrl.handlers["pv_edit_box_selection"]({"selection": [1, 2, 3, 4]})
    state.edit_selection_mode = "add"
    ctrl.handlers["pv_edit_box_selection"]({"selection": [1, 2, 3, 4]})
    state.edit_selection_mode = "subtract"
    ctrl.handlers["pv_edit_box_selection"]({"selection": [1, 2, 3, 4]})
    state.edit_selection_mode = "flip"
    ctrl.handlers["pv_edit_box_selection"]({"selection": [1, 2, 3, 4]})

    assert actions == [
        ("replace", [11, 12], False),
        ("add", [11, 12], False),
        ("subtract", [11, 12], False),
        ("flip", [11, 12], False),
    ]
    assert calls == ["sync", "overlay", "render"] * 4
    assert state.selection_count == 4
    assert state.edit_selection_mode == "flip"
    assert state.edit_selection_status == "Flipped 2 cell(s) with box selection. 4 selected total."
