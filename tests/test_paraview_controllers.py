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
