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


def test_pv_apply_edit_field_requires_field_choice():
    ctrl = FakeCtrl()
    state = SimpleNamespace(
        edit_geometry_mode="volume",
        edit_field_choice="",
        edit_expression="",
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
        assign_to_selected=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("assign_to_selected should not run without field choice")
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

    assert state.edit_apply_status_type == "error"
    assert "Select a field" in state.edit_apply_status
    assert sync_calls == ["sync"]


def test_pv_color_control_handlers_apply_backend_updates():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        color_map_preset="Cool to Warm",
        color_range_min="1",
        color_range_max="9",
        color_bar_visible=True,
        orientation_axes_visible=True,
        categorical_coloring=True,
        color_controls_status="",
        color_controls_status_type="info",
    )
    pv_backend = SimpleNamespace(
        display=object(),
        apply_color_map_preset=lambda preset: calls.append(("preset", preset)),
        apply_color_range=lambda low, high: calls.append(("range", low, high)),
        rescale_color_range_to_data=lambda: calls.append("rescale"),
        set_scalar_bar_visible=lambda visible: calls.append(("bar", visible)),
        set_orientation_axes_visible=lambda visible: calls.append(("axes", visible)),
        set_categorical_coloring=lambda enabled: calls.append(("categorical", enabled)),
    )

    register_paraview_controllers(
        ctrl,
        state,
        is_paraview_backend=lambda: True,
        pv_backend=pv_backend,
        edit_session=SimpleNamespace(active=False),
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: calls.append("sync-ui") or setattr(
            state, "color_bar_visible", True
        ),
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

    ctrl.handlers["pv_apply_color_map_preset"]("Viridis (matplotlib)")
    ctrl.handlers["pv_apply_color_range"]()
    ctrl.handlers["pv_rescale_color_range_to_data"]()
    ctrl.handlers["pv_set_scalar_bar_visible"](False)
    ctrl.handlers["pv_set_orientation_axes_visible"](False)
    ctrl.handlers["pv_set_categorical_coloring"](False)

    assert ("preset", "Viridis (matplotlib)") in calls
    assert ("range", "1", "9") in calls
    assert "rescale" in calls
    assert ("bar", False) in calls
    assert ("axes", False) in calls
    assert ("categorical", False) in calls
    assert state.color_bar_visible is False
    assert state.color_controls_status_type == "success"


def test_pv_on_edit_field_choice_create_new_opens_dialog_from_event_value():
    ctrl = FakeCtrl()
    state = SimpleNamespace(
        edit_field_choice="cell:BoundaryID",
        edit_create_field_dialog=False,
    )
    edit_session = SimpleNamespace(active=True)

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

    ctrl.handlers["pv_on_edit_field_choice"]("__create_new__")

    assert state.edit_create_field_dialog is True
    assert state.edit_field_choice == "__create_new__"


def test_pv_create_edit_field_existing_name_opens_overwrite_dialog():
    ctrl = FakeCtrl()
    state = SimpleNamespace(
        edit_geometry_mode="volume",
        edit_field_options=[],
        edit_field_choice="__create_new__",
        edit_create_field_dialog=True,
        edit_new_field_association="cell",
        edit_new_field_name="A field",
        edit_new_field_default_value="2.5",
        edit_apply_status="",
        edit_apply_status_type="info",
        edit_overwrite_dialog=False,
        edit_overwrite_field_name="",
    )

    edit_session = SimpleNamespace(
        active=True,
        geometry_mode="",
        has_field=lambda name, association: True,
        create_field=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("create_field should not run before overwrite confirm")
        ),
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

    ctrl.handlers["pv_create_edit_field"]()

    assert state.edit_overwrite_dialog is True
    assert state.edit_overwrite_field_name == "A field"
    assert state.edit_apply_status_type == "warning"
    assert "already exists" in state.edit_apply_status


def test_pv_confirm_overwrite_edit_field_creates_with_overwrite_true():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        edit_geometry_mode="volume",
        edit_geometry_mode_options=[],
        edit_field_choice="__create_new__",
        edit_create_field_dialog=True,
        edit_new_field_association="cell",
        edit_new_field_name="A field",
        edit_new_field_default_value="2.5",
        edit_apply_status="",
        edit_apply_status_type="info",
        edit_overwrite_dialog=True,
        edit_overwrite_field_name="A field",
        edit_cell_geometry_mode_options=[{"text": "Volume", "value": "volume"}],
        edit_point_geometry_mode_options=[{"text": "Point", "value": "point"}],
    )
    edit_session = SimpleNamespace(
        active=True,
        geometry_mode="",
        create_field=lambda field, association, default, overwrite=False: calls.append(
            (field, association, default, overwrite)
        ) or field,
        selected_count=lambda: 4,
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

    assert calls == [("A field", "cell", "2.5", True)]
    assert state.edit_apply_status_type == "success"
    assert "Created cell field 'A field'" in state.edit_apply_status


def test_pv_apply_edit_field_surface_mode_assigns_to_selected():
    ctrl = FakeCtrl()
    state = SimpleNamespace(
        edit_geometry_mode="surface",
        edit_geometry_mode_options=[],
        edit_field_choice="cell:BoundaryID",
        edit_field_association="cell",
        edit_expression="1",
        edit_apply_status="",
        edit_apply_status_type="info",
        edit_overwrite_dialog=False,
        edit_overwrite_field_name="",
        edit_cell_geometry_mode_options=[{"text": "Surface", "value": "surface"}],
        edit_point_geometry_mode_options=[{"text": "Point", "value": "point"}],
    )
    edit_session = SimpleNamespace(
        active=True,
        geometry_mode="",
        assign_to_selected=lambda field, association, expression: field,
        selected_count=lambda: 4,
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

    assert edit_session.geometry_mode == "surface"
    assert state.edit_apply_status_type == "success"
    assert "Assigned 'BoundaryID'" in state.edit_apply_status
    assert sync_calls == ["sync"]


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
    edit_session.replace_selection = lambda ids, grow=False, angle_threshold=None: 2
    edit_session.add_selection = lambda ids, grow=False, angle_threshold=None: 2
    edit_session.subtract_selection = lambda ids, grow=False, angle_threshold=None: 0
    edit_session.flip_selection = lambda ids, grow=False, angle_threshold=None: 2

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


def test_degenerate_box_selection_uses_click_picker():
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
        edit_geometry_mode="volume",
        edit_view_style="width: 100%; height: 100%; cursor: crosshair; outline: none;",
    )
    edit_session = SimpleNamespace(active=True, geometry_mode="volume")
    edit_session.replace_selection = (
        lambda ids, grow=False, angle_threshold=None: calls.append(
            ("replace", ids, grow, angle_threshold)
        )
        or len(ids)
    )
    edit_session.add_selection = lambda ids, grow=False, angle_threshold=None: 0
    edit_session.subtract_selection = lambda ids, grow=False, angle_threshold=None: 0
    edit_session.flip_selection = lambda ids, grow=False, angle_threshold=None: 0

    register_paraview_controllers(
        ctrl,
        state,
        is_paraview_backend=lambda: True,
        pv_backend=SimpleNamespace(
            pick_visible_cell_ids=lambda x, y: calls.append(("click", x, y)) or [7],
            pick_visible_cell_ids_in_rect=lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("degenerate box should not use rectangle picker")
            ),
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

    ctrl.handlers["pv_edit_box_selection"]({"selection": [5, 5, 7, 7]})

    assert calls == [
        ("click", 5.0, 7.0),
        ("replace", [7], False, None),
        "sync",
        "overlay",
        "render",
    ]
    assert state.selection_count == 1
    assert "click selection" in state.edit_selection_status


def test_box_selection_scales_event_coordinates_to_paraview_view():
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
        edit_geometry_mode="volume",
        edit_view_style="width: 100%; height: 100%; cursor: crosshair; outline: none;",
    )
    edit_session = SimpleNamespace(active=True, geometry_mode="volume")
    edit_session.replace_selection = (
        lambda ids, grow=False, angle_threshold=None: calls.append(
            ("replace", ids, grow, angle_threshold)
        )
        or len(ids)
    )
    edit_session.add_selection = lambda ids, grow=False, angle_threshold=None: 0
    edit_session.subtract_selection = lambda ids, grow=False, angle_threshold=None: 0
    edit_session.flip_selection = lambda ids, grow=False, angle_threshold=None: 0

    def pick_rect(x0, y0, x1, y1, behavior="touch"):
        calls.append(("rect", x0, y0, x1, y1, behavior))
        return [3, 4]

    register_paraview_controllers(
        ctrl,
        state,
        is_paraview_backend=lambda: True,
        pv_backend=SimpleNamespace(
            view=SimpleNamespace(ViewSize=(200, 400)),
            pick_visible_cell_ids_in_rect=pick_rect,
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

    ctrl.handlers["pv_edit_box_selection"](
        {"selection": [10, 20, 30, 40], "size": [100, 200]}
    )

    assert calls == [
        ("rect", 20.0, 60.0, 40.0, 80.0, "touch"),
        ("replace", [3, 4], False, None),
        "sync",
        "overlay",
        "render",
    ]
    assert state.selection_count == 2


def test_pick_rotate_handlers_update_mode_and_push_view():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        pick_mode=True,
    )
    edit_session = SimpleNamespace(active=True)

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
        call_view_update=lambda **kwargs: calls.append("view_update"),
        sync_edit_session_state=lambda: calls.append("sync"),
        sync_paraview_edit_selection_overlay=lambda: None,
        summarize_edit_event=lambda event: "",
        normalize_edit_selection_ids=lambda event: [],
    )

    ctrl.handlers["pv_set_rotate_mode"]()
    assert state.pick_mode is False
    ctrl.handlers["pv_set_pick_mode"]()
    assert state.pick_mode is True
    assert calls == ["sync", "view_update", "sync", "view_update"]


def test_surface_mode_click_selection_uses_surface_picker_keys():
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
    actions = []
    edit_session = SimpleNamespace(active=True, geometry_mode="surface")
    edit_session.replace_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(("replace", list(ids), grow)) or 1
    )
    edit_session.add_selection = lambda ids, grow=False, angle_threshold=None: 1
    edit_session.subtract_selection = lambda ids, grow=False, angle_threshold=None: 0
    edit_session.flip_selection = lambda ids, grow=False, angle_threshold=None: 1

    register_paraview_controllers(
        ctrl,
        state,
        is_paraview_backend=lambda: True,
        pv_backend=SimpleNamespace(
            pick_visible_surface_keys=lambda x, y: [(1, 2, 3)],
            pick_visible_cell_ids=lambda x, y: [99],
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

    assert actions == [("replace", [(1, 2, 3)], False)]
    assert calls == ["sync", "overlay", "render"]


def test_surface_mode_box_selection_uses_surface_picker_keys():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        pick_mode=True,
        group_select=False,
        selection_count=0,
        edit_selection_event="",
        edit_selection_status="",
        edit_selection_status_type="info",
        selection_behavior="inside",
        edit_selection_mode="replace",
        edit_geometry_mode="surface",
        edit_view_style="width: 100%; height: 100%; cursor: crosshair; outline: none;",
    )
    actions = []
    edit_session = SimpleNamespace(active=True, geometry_mode="surface")
    edit_session.replace_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(("replace", list(ids), grow)) or 2
    )
    edit_session.add_selection = lambda ids, grow=False, angle_threshold=None: 2
    edit_session.subtract_selection = lambda ids, grow=False, angle_threshold=None: 0
    edit_session.flip_selection = lambda ids, grow=False, angle_threshold=None: 2

    register_paraview_controllers(
        ctrl,
        state,
        is_paraview_backend=lambda: True,
        pv_backend=SimpleNamespace(
            pick_visible_surface_keys_in_rect=lambda *args, **kwargs: [(4, 5, 6), (7, 8, 9)],
            pick_visible_cell_ids_in_rect=lambda *args, **kwargs: [11, 12],
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

    assert actions == [("replace", [(4, 5, 6), (7, 8, 9)], False)]
    assert calls == ["sync", "overlay", "render"]
    assert (
        state.edit_selection_status
        == "Selected 2 surface element(s) with box selection. 2 selected total."
    )


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
        lambda ids, grow=False, angle_threshold=None: actions.append(("replace", list(ids), grow)) or 2
    )
    edit_session.add_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(("add", list(ids), grow)) or 5
    )
    edit_session.subtract_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(("subtract", list(ids), grow)) or 3
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
        lambda ids, grow=False, angle_threshold=None: actions.append(("replace", list(ids), grow)) or 1
    )
    edit_session.add_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(("add", list(ids), grow)) or 1
    )
    edit_session.subtract_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(("subtract", list(ids), grow)) or 0
    )
    edit_session.flip_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(("flip", list(ids), grow)) or 1
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


def test_pv_edit_click_selection_replace_ignores_native_toggled_selection_payload():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        pick_mode=True,
        group_select=False,
        selection_count=2,
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
        lambda ids, grow=False, angle_threshold=None: actions.append(
            ("replace", list(ids), grow)
        )
        or len(ids)
    )
    edit_session.add_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(
            ("add", list(ids), grow)
        )
        or len(ids)
    )
    edit_session.subtract_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(
            ("subtract", list(ids), grow)
        )
        or 0
    )
    edit_session.flip_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(
            ("flip", list(ids), grow)
        )
        or 0
    )

    register_paraview_controllers(
        ctrl,
        state,
        is_paraview_backend=lambda: True,
        pv_backend=SimpleNamespace(
            pick_visible_cell_ids=lambda x, y: [1, 2, 3] if (x, y) == (12, 34) else []
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

    ctrl.handlers["pv_edit_click_selection"](
        {
            "position": {"x": 12, "y": 34},
            "selection": [{"compositeID": 2}],
        }
    )

    assert actions == [("replace", [1, 2, 3], False)]
    assert state.selection_count == 3
    assert state.edit_selection_status == "Selected 3 cell(s) with click selection. 3 selected total."


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
        lambda ids, grow=False, angle_threshold=None: actions.append(("replace", list(ids), grow)) or 2
    )
    edit_session.add_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(("add", list(ids), grow)) or 5
    )
    edit_session.subtract_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(("subtract", list(ids), grow)) or 3
    )
    edit_session.flip_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(("flip", list(ids), grow)) or 4
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


def test_surface_selection_passes_angle_threshold_to_edit_session():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        pick_mode=True,
        group_select=True,
        angle_threshold=22,
        selection_count=0,
        edit_selection_event="",
        edit_selection_status="",
        edit_selection_status_type="info",
        selection_behavior="touch",
        edit_selection_mode="replace",
        edit_geometry_mode="surface",
        edit_view_style="width: 100%; height: 100%; cursor: crosshair; outline: none;",
    )
    actions = []
    edit_session = SimpleNamespace(active=True, geometry_mode="surface")
    edit_session.replace_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(
            ("replace", list(ids), grow, angle_threshold)
        )
        or 1
    )
    edit_session.add_selection = lambda ids, grow=False, angle_threshold=None: 1
    edit_session.subtract_selection = lambda ids, grow=False, angle_threshold=None: 0
    edit_session.flip_selection = lambda ids, grow=False, angle_threshold=None: 1

    register_paraview_controllers(
        ctrl,
        state,
        is_paraview_backend=lambda: True,
        pv_backend=SimpleNamespace(
            pick_visible_surface_keys_in_rect=lambda *args, **kwargs: [(1, 2, 3)],
            pick_visible_cell_ids_in_rect=lambda *args, **kwargs: [10],
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

    assert actions == [("replace", [(1, 2, 3)], True, 22)]
    assert calls == ["sync", "overlay", "render"]
