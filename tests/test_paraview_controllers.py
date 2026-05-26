from types import SimpleNamespace

from paraview_controllers import register_paraview_controllers


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
        pv_backend=SimpleNamespace(),
        edit_session=SimpleNamespace(),
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
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
        pv_backend=pv_backend,
        edit_session=SimpleNamespace(),
        refresh_runtime_message=lambda **kwargs: calls.append(("runtime", kwargs)),
        update_paraview_ui_state=lambda: calls.append("update_ui"),
        update_color_state=lambda: None,
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
        notification_message="",
        notification_type="info",
        notification_show=False,
        save_dialog=False,
        save_dialog_action="",
    )
    pv_backend = SimpleNamespace(
        get_visibility=lambda node_id: True if node_id == "node-1" else None,
        set_visibility=lambda node_id, visible: calls.append((node_id, visible)),
    )

    register_paraview_controllers(
        ctrl,
        state,
        pv_backend=pv_backend,
        edit_session=SimpleNamespace(),
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: calls.append("update_ui"),
        update_color_state=lambda: None,
        render_and_push=lambda: calls.append("render"),
        save_paraview_output=lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("cannot save")
        ),
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
    assert state.save_dialog is True

    ctrl.handlers["pv_confirm_save_dialog"]("output.vtu")

    assert calls[:3] == [("node-1", False), "update_ui", "render"]
    assert state.notification_message == "Error: cannot save"
    assert state.notification_type == "error"


def test_pv_save_existing_target_opens_overwrite_dialog_and_confirm_retries():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        active_pipeline_item="node-1",
        active_visibility=True,
        notification_message="",
        notification_type="info",
        notification_show=False,
        save_dialog=False,
        save_dialog_action="",
        save_overwrite_dialog=False,
        save_overwrite_target="",
        save_overwrite_action="",
    )

    def save_with_confirmation(*, filename=None, overwrite=False):
        calls.append(overwrite)
        if not overwrite:
            raise FileExistsError(17, "exists", "exports/final.vtu")

    register_paraview_controllers(
        ctrl,
        state,
        pv_backend=SimpleNamespace(),
        edit_session=SimpleNamespace(active=False),
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
        render_and_push=lambda: None,
        save_paraview_output=save_with_confirmation,
        debug_view=lambda *args, **kwargs: None,
        call_view_update_geometry=lambda **kwargs: None,
        call_view_set_remote_rendering=lambda enabled: None,
        call_view_update=lambda **kwargs: None,
        sync_edit_session_state=lambda: None,
        sync_paraview_edit_selection_overlay=lambda: None,
        summarize_edit_event=lambda event: "",
        normalize_edit_selection_ids=lambda ids: ids,
    )

    ctrl.handlers["pv_save_active_data"]()
    assert state.save_dialog is True

    ctrl.handlers["pv_confirm_save_dialog"]("exports/final.vtu")

    assert calls == [False]
    assert state.save_overwrite_dialog is True
    assert state.save_overwrite_target == "exports/final.vtu"
    assert state.save_overwrite_action == "save"

    ctrl.handlers["pv_confirm_save_overwrite"]()

    assert calls == [False, True]
    assert state.save_overwrite_dialog is False
    assert state.save_overwrite_target == ""
    assert state.save_overwrite_action == ""


def test_pv_save_dialog_passes_filename_to_save():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        active_pipeline_item="node-1",
        active_visibility=True,
        notification_message="",
        notification_type="info",
        notification_show=False,
        save_dialog=False,
        save_dialog_action="",
        save_overwrite_dialog=False,
        save_overwrite_target="",
        save_overwrite_action="",
    )

    def save_with_confirmation(*, filename=None, overwrite=False):
        calls.append((filename, overwrite))

    register_paraview_controllers(
        ctrl,
        state,
        pv_backend=SimpleNamespace(),
        edit_session=SimpleNamespace(active=False),
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
        render_and_push=lambda: None,
        save_paraview_output=save_with_confirmation,
        debug_view=lambda *args, **kwargs: None,
        call_view_update_geometry=lambda **kwargs: None,
        call_view_set_remote_rendering=lambda enabled: None,
        call_view_update=lambda **kwargs: None,
        sync_edit_session_state=lambda: None,
        sync_paraview_edit_selection_overlay=lambda: None,
        summarize_edit_event=lambda event: "",
        normalize_edit_selection_ids=lambda ids: ids,
    )

    ctrl.handlers["pv_save_active_data"]()
    assert state.save_dialog is True
    assert state.save_dialog_action == "save"

    ctrl.handlers["pv_confirm_save_dialog"]("e2e_surface_boundaryid_left.vtu")

    assert calls == [("e2e_surface_boundaryid_left.vtu", False)]
    assert state.save_dialog is False


def test_pv_save_state_existing_target_opens_overwrite_dialog_and_confirm_retries():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        active_pipeline_item="node-1",
        state_filename="states/demo",
        notification_message="",
        notification_type="info",
        notification_show=False,
        save_overwrite_dialog=False,
        save_overwrite_target="",
        save_overwrite_action="",
    )

    def save_state_with_confirmation(*, overwrite=False):
        calls.append(overwrite)
        if not overwrite:
            raise FileExistsError(17, "exists", "states/demo.coral.state.json")

    register_paraview_controllers(
        ctrl,
        state,
        pv_backend=SimpleNamespace(),
        edit_session=SimpleNamespace(active=False),
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
        render_and_push=lambda: None,
        save_paraview_output=lambda **kwargs: None,
        debug_view=lambda *args, **kwargs: None,
        call_view_update_geometry=lambda **kwargs: None,
        call_view_set_remote_rendering=lambda enabled: None,
        call_view_update=lambda **kwargs: None,
        sync_edit_session_state=lambda: None,
        sync_paraview_edit_selection_overlay=lambda: None,
        summarize_edit_event=lambda event: "",
        normalize_edit_selection_ids=lambda ids: ids,
        save_paraview_state=save_state_with_confirmation,
    )

    ctrl.handlers["pv_save_state"]()

    assert calls == [False]
    assert state.save_overwrite_dialog is True
    assert state.save_overwrite_target == "states/demo.coral.state.json"
    assert state.save_overwrite_action == "state_save"

    ctrl.handlers["pv_confirm_save_overwrite"]()

    assert calls == [False, True]
    assert state.save_overwrite_dialog is False
    assert state.save_overwrite_target == ""
    assert state.save_overwrite_action == ""


def test_pv_commit_existing_target_opens_overwrite_dialog_and_confirm_commits():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        mainViewMode="remote",
        notification_message="",
        notification_type="info",
        notification_show=False,
        save_dialog=False,
        save_dialog_action="",
        save_overwrite_dialog=False,
        save_overwrite_target="",
        save_overwrite_action="",
        inspector_tab=3,
        representation="Surface",
        available_arrays=[],
        selected_array="__solid__",
    )
    edit_session = SimpleNamespace(active=True, clear=lambda: calls.append("clear"))
    pv_backend = SimpleNamespace(
        clear_edit_target_dataset=lambda: calls.append("clear_target"),
        load_file=lambda output_path: (
            [{"text": "Solid Color", "value": "__solid__"}],
            "__solid__",
        ),
        apply_representation=lambda representation: calls.append(
            ("representation", representation)
        ),
        apply_coloring=lambda array_name: calls.append(("coloring", array_name)),
    )

    def save_with_confirmation(*, filename=None, overwrite=False):
        calls.append(("save", overwrite))
        if not overwrite:
            raise FileExistsError(17, "exists", "results/edited_mesh.vtu")
        return "/tmp/data/results/edited_mesh.vtu"

    register_paraview_controllers(
        ctrl,
        state,
        pv_backend=pv_backend,
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: calls.append("update_ui"),
        update_color_state=lambda: None,
        render_and_push=lambda: calls.append("render"),
        save_paraview_output=save_with_confirmation,
        debug_view=lambda *args, **kwargs: calls.append(("debug", args[0])),
        call_view_update_geometry=lambda **kwargs: None,
        call_view_set_remote_rendering=lambda enabled: calls.append(
            ("remote", enabled)
        ),
        call_view_update=lambda **kwargs: None,
        sync_edit_session_state=lambda: calls.append("sync_edit"),
        sync_paraview_edit_selection_overlay=lambda: calls.append("sync_overlay"),
        summarize_edit_event=lambda event: "",
        normalize_edit_selection_ids=lambda ids: ids,
    )

    ctrl.handlers["pv_commit_edit_session"]()
    assert state.save_dialog is True
    assert state.save_dialog_action == "commit"

    ctrl.handlers["pv_confirm_save_dialog"]("results/edited_mesh.vtu")

    assert state.save_overwrite_dialog is True
    assert state.save_overwrite_target == "results/edited_mesh.vtu"
    assert state.save_overwrite_action == "commit"

    ctrl.handlers["pv_confirm_save_overwrite"]()

    assert ("save", True) in calls
    assert "clear" in calls
    assert "sync_edit" in calls
    assert "sync_overlay" in calls
    assert ("remote", True) in calls
    assert "update_ui" in calls
    assert "render" in calls
    assert state.notification_message == "Edit session saved and added to the pipeline"
    assert state.notification_type == "success"


def test_pv_commit_dialog_passes_filename_to_save():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        mainViewMode="remote",
        notification_message="",
        notification_type="info",
        notification_show=False,
        save_dialog=False,
        save_dialog_action="",
        save_overwrite_dialog=False,
        save_overwrite_target="",
        save_overwrite_action="",
        inspector_tab=3,
        representation="Surface",
        available_arrays=[],
        selected_array="__solid__",
    )
    edit_session = SimpleNamespace(active=True, clear=lambda: calls.append("clear"))
    pv_backend = SimpleNamespace(
        clear_edit_target_dataset=lambda: calls.append("clear_target"),
        load_file=lambda output_path: (
            [{"text": "Solid Color", "value": "__solid__"}],
            "__solid__",
        ),
        apply_representation=lambda representation: calls.append(
            ("representation", representation)
        ),
        apply_coloring=lambda array_name: calls.append(("coloring", array_name)),
    )

    def save_result(*, filename=None, overwrite=False):
        calls.append(("save", filename, overwrite))
        return "/tmp/data/" + (filename or "output.vtu")

    register_paraview_controllers(
        ctrl,
        state,
        pv_backend=pv_backend,
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: calls.append("update_ui"),
        update_color_state=lambda: None,
        render_and_push=lambda: calls.append("render"),
        save_paraview_output=save_result,
        debug_view=lambda *args, **kwargs: None,
        call_view_update_geometry=lambda **kwargs: None,
        call_view_set_remote_rendering=lambda enabled: calls.append(
            ("remote", enabled)
        ),
        call_view_update=lambda **kwargs: None,
        sync_edit_session_state=lambda: calls.append("sync_edit"),
        sync_paraview_edit_selection_overlay=lambda: calls.append("sync_overlay"),
        summarize_edit_event=lambda event: "",
        normalize_edit_selection_ids=lambda ids: ids,
    )

    ctrl.handlers["pv_commit_edit_session"]()
    assert state.save_dialog is True
    assert state.save_dialog_action == "commit"

    ctrl.handlers["pv_confirm_save_dialog"]("e2e_surface_boundaryid_left.vtu")

    assert ("save", "e2e_surface_boundaryid_left.vtu", False) in calls
    assert state.save_dialog is False


def test_pv_set_cell_face_visibility_updates_backend_and_refreshes_view():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        active_pipeline_item="node-1",
        show_cells=False,
        show_faces=True,
        notification_message="",
        notification_type="info",
        notification_show=False,
    )
    pv_backend = SimpleNamespace(
        set_cell_face_visibility=lambda cells, faces: calls.append(
            ("cell_visibility", cells, faces)
        )
    )

    register_paraview_controllers(
        ctrl,
        state,
        pv_backend=pv_backend,
        edit_session=SimpleNamespace(),
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: calls.append("update_ui"),
        update_color_state=lambda: None,
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

    ctrl.handlers["pv_set_cell_face_visibility"]()

    assert calls == [("cell_visibility", False, True), "update_ui", "render"]


def test_pv_set_cell_face_visibility_accepts_checkbox_pair_payload():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        active_pipeline_item="node-1",
        show_cells=True,
        show_faces=True,
        notification_message="",
        notification_type="info",
        notification_show=False,
    )
    pv_backend = SimpleNamespace(
        set_cell_face_visibility=lambda cells, faces: calls.append(
            ("cell_visibility", cells, faces)
        )
    )

    register_paraview_controllers(
        ctrl,
        state,
        pv_backend=pv_backend,
        edit_session=SimpleNamespace(),
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: calls.append("update_ui"),
        update_color_state=lambda: None,
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

    ctrl.handlers["pv_set_cell_face_visibility"]([False, True])

    assert calls == [("cell_visibility", False, True), "update_ui", "render"]


def test_pv_reload_active_file_refreshes_pipeline_state():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        active_pipeline_item="node-1",
        selected_array="point:U",
        representation="Wireframe",
        has_boundary=True,
        notification_message="",
        notification_type="info",
        notification_show=False,
        selection_count=4,
        color_bar_visible=False,
        color_range_min="2",
        color_range_max="8",
        color_map_preset="Cool to Warm",
        categorical_coloring=True,
        show_cells=False,
        show_faces=True,
        source_properties=[{"name": "SomeReaderProperty", "pending_value": 2}],
        display_properties=[
            {"name": "Opacity", "pending_value": 0.4},
            {"name": "LineWidth", "pending_value": 3.0},
        ],
    )
    source_properties = state.source_properties
    display_properties = state.display_properties
    pv_backend = SimpleNamespace(
        reload_node_file=lambda node_id: calls.append(("reload", node_id))
        or ([{"text": "M", "value": "cell:M"}], "cell:M"),
        apply_representation=lambda representation: calls.append(
            ("representation", representation)
        ),
        apply_coloring=lambda array: calls.append(("coloring", array)),
        set_cell_face_visibility=lambda cells, faces: calls.append(
            ("cell_visibility", cells, faces)
        ),
        apply_property_changes=lambda source, display: calls.append(
            ("properties", source, display)
        ),
        apply_color_map_preset=lambda preset: calls.append(("preset", preset)),
        apply_color_range=lambda low, high: calls.append(("range", low, high)),
        set_categorical_coloring=lambda enabled: calls.append(("categorical", enabled)),
        set_scalar_bar_visible=lambda visible: calls.append(("bar", visible)),
    )

    register_paraview_controllers(
        ctrl,
        state,
        pv_backend=pv_backend,
        edit_session=SimpleNamespace(),
        refresh_runtime_message=lambda **kwargs: calls.append(("runtime", kwargs)),
        update_paraview_ui_state=lambda: calls.append("update_ui"),
        update_color_state=lambda: None,
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

    ctrl.handlers["pv_reload_active_file"]()

    assert calls[:6] == [
        ("runtime", {"clear": True}),
        ("reload", "node-1"),
        ("representation", "Wireframe"),
        ("coloring", "point:U"),
        ("cell_visibility", False, True),
        ("properties", source_properties, display_properties),
    ]
    assert calls[6:12] == [
        ("preset", "Cool to Warm"),
        ("range", "2", "8"),
        ("categorical", True),
        ("bar", False),
        ("runtime", {}),
        "update_ui",
    ]
    assert calls[-1] == "render"
    assert state.has_boundary is False
    assert state.selection_count == 0


def test_pv_reload_active_file_skips_invalid_restored_preset():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        active_pipeline_item="node-1",
        selected_array="point:U",
        representation="Surface",
        has_boundary=True,
        notification_message="",
        notification_type="info",
        notification_show=False,
        selection_count=4,
        color_bar_visible=True,
        color_range_min="",
        color_range_max="",
        color_map_preset="Viridis (matplotlib)",
        categorical_coloring=False,
    )
    pv_backend = SimpleNamespace(
        reload_node_file=lambda node_id: calls.append(("reload", node_id))
        or ([{"text": "U", "value": "point:U"}], "point:U"),
        apply_representation=lambda representation: calls.append(
            ("representation", representation)
        ),
        apply_coloring=lambda array: calls.append(("coloring", array)),
        apply_color_map_preset=lambda preset: (_ for _ in ()).throw(
            RuntimeError("missing preset")
        ),
        apply_color_range=lambda *args: None,
        set_categorical_coloring=lambda enabled: calls.append(("categorical", enabled)),
        set_scalar_bar_visible=lambda visible: calls.append(("bar", visible)),
        set_cell_face_visibility=lambda *args: None,
        apply_property_changes=lambda *args: None,
    )
    state.show_cells = True
    state.show_faces = True
    state.source_properties = []
    state.display_properties = []

    register_paraview_controllers(
        ctrl,
        state,
        pv_backend=pv_backend,
        edit_session=SimpleNamespace(),
        refresh_runtime_message=lambda **kwargs: calls.append(("runtime", kwargs)),
        update_paraview_ui_state=lambda: calls.append("update_ui"),
        update_color_state=lambda: None,
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

    ctrl.handlers["pv_reload_active_file"]()

    assert "update_ui" in calls
    assert calls[-1] == "render"
    assert state.notification_type == "warning"


def test_pv_delete_active_clears_selected_file_when_pipeline_becomes_empty():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        active_pipeline_item="node-1",
        selected_file="/tmp/data/mesh.vtk",
        notification_message="",
        notification_type="info",
        notification_show=False,
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
        pv_backend=pv_backend,
        edit_session=SimpleNamespace(),
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=update_ui_state,
        update_color_state=lambda: None,
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


def test_pv_add_filter_success_and_failure_paths():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        active_pipeline_item="node-1",
        filter_menu=True,
        notification_message="",
        notification_type="info",
        notification_show=False,
    )

    backend_success = SimpleNamespace(
        add_filter=lambda key: calls.append(("add_filter", key))
    )

    register_paraview_controllers(
        ctrl,
        state,
        pv_backend=backend_success,
        edit_session=SimpleNamespace(),
        refresh_runtime_message=lambda **kwargs: calls.append(("runtime", kwargs)),
        update_paraview_ui_state=lambda: calls.append("update_ui"),
        update_color_state=lambda: None,
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
        pv_backend=failing_backend,
        edit_session=SimpleNamespace(),
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
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

    assert state.notification_message == "Error adding filter: bad filter"


def test_pv_apply_edit_field_requires_field_choice():
    ctrl = FakeCtrl()
    state = SimpleNamespace(
        edit_geometry_mode="volume",
        edit_field_choice="",
        edit_expression="",
        notification_message="",
        notification_type="info",
        notification_show=False,
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
        pv_backend=SimpleNamespace(),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
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

    assert state.notification_type == "error"
    assert "Select a field" in state.notification_message
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
        notification_message="",
        notification_type="info",
        notification_show=False,
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
        pv_backend=pv_backend,
        edit_session=SimpleNamespace(active=False),
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: calls.append("sync-ui")
        or setattr(state, "color_bar_visible", True),
        update_color_state=lambda: None,
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
    assert state.notification_type == "success"


def test_color_action_handlers_route_through_update_color_state_not_full_ui_flush():
    ctrl = FakeCtrl()
    color_state_calls = []
    full_flush_calls = []
    state = SimpleNamespace(
        color_map_preset="Cool to Warm",
        color_range_min="1",
        color_range_max="9",
        color_bar_visible=True,
        orientation_axes_visible=True,
        categorical_coloring=False,
        notification_message="",
        notification_type="info",
        notification_show=False,
    )
    pv_backend = SimpleNamespace(
        display=object(),
        apply_color_map_preset=lambda _: None,
        apply_color_range=lambda _l, _h: None,
        rescale_color_range_to_data=lambda: None,
        set_categorical_coloring=lambda _: None,
    )

    register_paraview_controllers(
        ctrl,
        state,
        pv_backend=pv_backend,
        edit_session=SimpleNamespace(active=False),
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: full_flush_calls.append("full"),
        update_color_state=lambda: color_state_calls.append("color"),
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

    ctrl.handlers["pv_apply_color_map_preset"]("Viridis (matplotlib)")
    ctrl.handlers["pv_apply_color_range"]()
    ctrl.handlers["pv_rescale_color_range_to_data"]()
    ctrl.handlers["pv_set_categorical_coloring"](True)

    assert color_state_calls == ["color", "color", "color", "color"]
    assert full_flush_calls == []


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
        pv_backend=SimpleNamespace(),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
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
        notification_message="",
        notification_type="info",
        notification_show=False,
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
        pv_backend=SimpleNamespace(),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
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
    assert state.notification_type == "warning"
    assert "already exists" in state.notification_message


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
        notification_message="",
        notification_type="info",
        notification_show=False,
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
        )
        or field,
        selected_count=lambda: 4,
    )

    register_paraview_controllers(
        ctrl,
        state,
        pv_backend=SimpleNamespace(),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
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
    assert state.notification_type == "success"
    assert "Created cell field 'A field'" in state.notification_message


def test_pv_apply_edit_field_surface_mode_assigns_to_selected():
    ctrl = FakeCtrl()
    state = SimpleNamespace(
        edit_geometry_mode="surface",
        edit_geometry_mode_options=[],
        edit_field_choice="cell:BoundaryID",
        edit_field_association="cell",
        edit_expression="1",
        notification_message="",
        notification_type="info",
        notification_show=False,
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
        pv_backend=SimpleNamespace(),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
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
    assert state.notification_type == "success"
    assert "Assigned 'BoundaryID'" in state.notification_message
    assert sync_calls == ["sync"]


def test_surface_mode_selection_keeps_surface_mode_after_sync():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        pick_mode=True,
        group_select=False,
        selection_count=0,
        edit_selection_event="",
        notification_message="",
        notification_type="info",
        notification_show=False,
        selection_behavior="touch",
        edit_selection_mode="replace",
        edit_geometry_mode="surface",
        angle_threshold=None,
        edit_view_style="width: 100%; height: 100%; cursor: crosshair; outline: none;",
    )
    edit_session = SimpleNamespace(
        active=True,
        geometry_mode="volume",
        working_dataset=None,
        selected_cell_ids=set(),
        selected_surface_keys=set(),
        selected_point_ids=set(),
    )
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
        pv_backend=SimpleNamespace(
            pick_visible_surface_keys_in_rect=lambda *args, **kwargs: [],
            pick_visible_cell_ids_in_rect=lambda *args, **kwargs: [11, 12],
            consume_selection_backend_timing=lambda: [],
            view=None,
        ),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
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
        notification_message="",
        notification_type="info",
        notification_show=False,
        selection_behavior="touch",
        edit_selection_mode="replace",
        edit_geometry_mode="volume",
        angle_threshold=None,
        edit_view_style="width: 100%; height: 100%; cursor: crosshair; outline: none;",
    )
    edit_session = SimpleNamespace(
        active=True,
        geometry_mode="volume",
        working_dataset=None,
        selected_cell_ids=set(),
        selected_surface_keys=set(),
        selected_point_ids=set(),
    )
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
        pv_backend=SimpleNamespace(
            pick_visible_cell_ids=lambda x, y: calls.append(("click", x, y)) or [7],
            pick_visible_cell_ids_in_rect=lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("degenerate box should not use rectangle picker")
            ),
            consume_selection_backend_timing=lambda: [],
            view=None,
        ),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
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
    assert "click selection" in state.notification_message


def test_box_selection_scales_event_coordinates_to_paraview_view():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        pick_mode=True,
        group_select=False,
        selection_count=0,
        edit_selection_event="",
        notification_message="",
        notification_type="info",
        notification_show=False,
        selection_behavior="touch",
        edit_selection_mode="replace",
        edit_geometry_mode="volume",
        angle_threshold=None,
        edit_view_style="width: 100%; height: 100%; cursor: crosshair; outline: none;",
    )
    edit_session = SimpleNamespace(
        active=True,
        geometry_mode="volume",
        working_dataset=None,
        selected_cell_ids=set(),
        selected_surface_keys=set(),
        selected_point_ids=set(),
    )
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
        pv_backend=SimpleNamespace(
            view=SimpleNamespace(ViewSize=(200, 400)),
            pick_visible_cell_ids_in_rect=pick_rect,
            consume_selection_backend_timing=lambda: [],
        ),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
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
        pv_backend=SimpleNamespace(),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
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
        notification_message="",
        notification_type="info",
        notification_show=False,
        selection_behavior="touch",
        edit_selection_mode="replace",
        edit_geometry_mode="surface",
        angle_threshold=None,
        edit_view_style="width: 100%; height: 100%; cursor: crosshair; outline: none;",
    )
    actions = []
    edit_session = SimpleNamespace(
        active=True,
        geometry_mode="surface",
        working_dataset=None,
        selected_cell_ids=set(),
        selected_surface_keys=set(),
        selected_point_ids=set(),
    )
    edit_session.replace_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(
            ("replace", list(ids), grow)
        )
        or 1
    )
    edit_session.add_selection = lambda ids, grow=False, angle_threshold=None: 1
    edit_session.subtract_selection = lambda ids, grow=False, angle_threshold=None: 0
    edit_session.flip_selection = lambda ids, grow=False, angle_threshold=None: 1

    register_paraview_controllers(
        ctrl,
        state,
        pv_backend=SimpleNamespace(
            pick_visible_surface_keys=lambda x, y: [(1, 2, 3)],
            pick_visible_cell_ids=lambda x, y: [99],
            consume_selection_backend_timing=lambda: [],
            view=None,
        ),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
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
        notification_message="",
        notification_type="info",
        notification_show=False,
        selection_behavior="inside",
        edit_selection_mode="replace",
        edit_geometry_mode="surface",
        angle_threshold=None,
        edit_view_style="width: 100%; height: 100%; cursor: crosshair; outline: none;",
    )
    actions = []
    edit_session = SimpleNamespace(
        active=True,
        geometry_mode="surface",
        working_dataset=None,
        selected_cell_ids=set(),
        selected_surface_keys=set(),
        selected_point_ids=set(),
    )
    edit_session.replace_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(
            ("replace", list(ids), grow)
        )
        or 2
    )
    edit_session.add_selection = lambda ids, grow=False, angle_threshold=None: 2
    edit_session.subtract_selection = lambda ids, grow=False, angle_threshold=None: 0
    edit_session.flip_selection = lambda ids, grow=False, angle_threshold=None: 2

    register_paraview_controllers(
        ctrl,
        state,
        pv_backend=SimpleNamespace(
            pick_visible_surface_keys_in_rect=lambda *args, **kwargs: [
                (4, 5, 6),
                (7, 8, 9),
            ],
            pick_visible_cell_ids_in_rect=lambda *args, **kwargs: [11, 12],
            consume_selection_backend_timing=lambda: [],
            view=None,
        ),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
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
        state.notification_message
        == "Selected 2 surface element(s) with box selection. 2 selected total."
    )


def test_surface_mode_box_selection_falls_back_from_inside_to_touch():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        pick_mode=True,
        group_select=False,
        selection_count=0,
        edit_selection_event="",
        notification_message="",
        notification_type="info",
        notification_show=False,
        selection_behavior="inside",
        edit_selection_mode="replace",
        edit_geometry_mode="surface",
        angle_threshold=None,
        edit_view_style="width: 100%; height: 100%; cursor: crosshair; outline: none;",
    )
    actions = []
    edit_session = SimpleNamespace(
        active=True,
        geometry_mode="surface",
        working_dataset=None,
        selected_cell_ids=set(),
        selected_surface_keys=set(),
        selected_point_ids=set(),
    )
    edit_session.replace_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(
            ("replace", list(ids), grow)
        )
        or 1
    )
    edit_session.add_selection = lambda ids, grow=False, angle_threshold=None: 1
    edit_session.subtract_selection = lambda ids, grow=False, angle_threshold=None: 0
    edit_session.flip_selection = lambda ids, grow=False, angle_threshold=None: 1

    surface_calls = []

    def pick_surface_keys_in_rect(*args, **kwargs):
        surface_calls.append(kwargs.get("behavior"))
        if kwargs.get("behavior") == "inside":
            return []
        return [(10, 11, 12)]

    register_paraview_controllers(
        ctrl,
        state,
        pv_backend=SimpleNamespace(
            pick_visible_surface_keys_in_rect=pick_surface_keys_in_rect,
            pick_visible_cell_ids_in_rect=lambda *args, **kwargs: [],
            consume_selection_backend_timing=lambda: [],
            view=None,
        ),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
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

    assert surface_calls == ["inside", "touch"]
    assert actions == [("replace", [(10, 11, 12)], False)]
    assert calls == ["sync", "overlay", "render"]


def test_pv_edit_box_selection_uses_explicit_selection_mode_from_state():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        pick_mode=True,
        group_select=False,
        selection_count=0,
        edit_selection_event="",
        notification_message="",
        notification_type="info",
        notification_show=False,
        selection_behavior="touch",
        edit_selection_mode="add",
        edit_geometry_mode="volume",
        angle_threshold=None,
        edit_view_style="width: 100%; height: 100%; cursor: crosshair; outline: none;",
    )
    actions = []
    edit_session = SimpleNamespace(
        active=True,
        geometry_mode="volume",
        working_dataset=None,
        selected_cell_ids=set(),
        selected_surface_keys=set(),
        selected_point_ids=set(),
    )
    edit_session.replace_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(
            ("replace", list(ids), grow)
        )
        or 2
    )
    edit_session.add_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(
            ("add", list(ids), grow)
        )
        or 5
    )
    edit_session.subtract_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(
            ("subtract", list(ids), grow)
        )
        or 3
    )

    register_paraview_controllers(
        ctrl,
        state,
        pv_backend=SimpleNamespace(
            pick_visible_cell_ids_in_rect=lambda *args, **kwargs: [11, 12],
            consume_selection_backend_timing=lambda: [],
            view=None,
        ),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
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
    assert (
        state.notification_message
        == "Added 2 cell(s) with box selection. 5 selected total."
    )


def test_pv_edit_click_selection_uses_coordinates_and_updates_overlay():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        pick_mode=True,
        group_select=False,
        selection_count=0,
        edit_selection_event="",
        notification_message="",
        notification_type="info",
        notification_show=False,
        selection_behavior="touch",
        edit_selection_mode="replace",
        edit_geometry_mode="volume",
        angle_threshold=None,
        edit_view_style="width: 100%; height: 100%; cursor: crosshair; outline: none;",
    )
    actions = []
    edit_session = SimpleNamespace(
        active=True,
        geometry_mode="volume",
        working_dataset=None,
        selected_cell_ids=set(),
        selected_surface_keys=set(),
        selected_point_ids=set(),
    )
    edit_session.replace_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(
            ("replace", list(ids), grow)
        )
        or 1
    )
    edit_session.add_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(
            ("add", list(ids), grow)
        )
        or 1
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
        or 1
    )

    register_paraview_controllers(
        ctrl,
        state,
        pv_backend=SimpleNamespace(
            pick_visible_cell_ids=lambda x, y: [41] if (x, y) == (12, 34) else [],
            consume_selection_backend_timing=lambda: [],
            view=None,
        ),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
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
    assert (
        state.notification_message
        == "Selected 1 cell(s) with click selection. 1 selected total."
    )
    assert state.selection_timing_payload["interaction"] == "click"
    assert state.selection_timing_payload["picked_count"] == 1
    assert "backend_pick" in state.selection_timing_last


def test_pv_edit_click_selection_replace_ignores_native_toggled_selection_payload():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        pick_mode=True,
        group_select=False,
        selection_count=2,
        edit_selection_event="",
        notification_message="",
        notification_type="info",
        notification_show=False,
        selection_behavior="touch",
        edit_selection_mode="replace",
        edit_geometry_mode="volume",
        angle_threshold=None,
        edit_view_style="width: 100%; height: 100%; cursor: crosshair; outline: none;",
    )
    actions = []
    edit_session = SimpleNamespace(
        active=True,
        geometry_mode="volume",
        working_dataset=None,
        selected_cell_ids=set(),
        selected_surface_keys=set(),
        selected_point_ids=set(),
    )
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
        pv_backend=SimpleNamespace(
            pick_visible_cell_ids=lambda x, y: [1, 2, 3] if (x, y) == (12, 34) else [],
            consume_selection_backend_timing=lambda: [],
            view=None,
        ),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
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
    assert (
        state.notification_message
        == "Selected 3 cell(s) with click selection. 3 selected total."
    )


def test_pv_edit_box_selection_applies_replace_add_and_subtract_modes():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        pick_mode=True,
        group_select=False,
        selection_count=0,
        edit_selection_event="",
        notification_message="",
        notification_type="info",
        notification_show=False,
        selection_behavior="touch",
        edit_selection_mode="replace",
        edit_geometry_mode="volume",
        angle_threshold=None,
        edit_view_style="width: 100%; height: 100%; cursor: crosshair; outline: none;",
    )
    actions = []
    edit_session = SimpleNamespace(
        active=True,
        geometry_mode="volume",
        working_dataset=None,
        selected_cell_ids=set(),
        selected_surface_keys=set(),
        selected_point_ids=set(),
    )
    edit_session.replace_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(
            ("replace", list(ids), grow)
        )
        or 2
    )
    edit_session.add_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(
            ("add", list(ids), grow)
        )
        or 5
    )
    edit_session.subtract_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(
            ("subtract", list(ids), grow)
        )
        or 3
    )
    edit_session.flip_selection = (
        lambda ids, grow=False, angle_threshold=None: actions.append(
            ("flip", list(ids), grow)
        )
        or 4
    )

    register_paraview_controllers(
        ctrl,
        state,
        pv_backend=SimpleNamespace(
            pick_visible_cell_ids_in_rect=lambda *args, **kwargs: [11, 12],
            consume_selection_backend_timing=lambda: [],
            view=None,
        ),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
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
    assert (
        state.notification_message
        == "Flipped 2 cell(s) with box selection. 4 selected total."
    )
    assert state.selection_timing_payload["interaction"] == "box"
    assert state.selection_timing_payload["picked_count"] == 2


def test_surface_selection_passes_angle_threshold_to_edit_session():
    ctrl = FakeCtrl()
    calls = []
    state = SimpleNamespace(
        pick_mode=True,
        group_select=True,
        angle_threshold=22,
        selection_count=0,
        edit_selection_event="",
        notification_message="",
        notification_type="info",
        notification_show=False,
        selection_behavior="touch",
        edit_selection_mode="replace",
        edit_geometry_mode="surface",
        edit_view_style="width: 100%; height: 100%; cursor: crosshair; outline: none;",
    )
    actions = []
    edit_session = SimpleNamespace(
        active=True,
        geometry_mode="surface",
        working_dataset=None,
        selected_cell_ids=set(),
        selected_surface_keys=set(),
        selected_point_ids=set(),
    )
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
        pv_backend=SimpleNamespace(
            pick_visible_surface_keys_in_rect=lambda *args, **kwargs: [(1, 2, 3)],
            pick_visible_cell_ids_in_rect=lambda *args, **kwargs: [10],
            consume_selection_backend_timing=lambda: [],
            view=None,
        ),
        edit_session=edit_session,
        refresh_runtime_message=lambda **kwargs: None,
        update_paraview_ui_state=lambda: None,
        update_color_state=lambda: None,
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
