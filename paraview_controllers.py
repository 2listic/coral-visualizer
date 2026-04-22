"""ParaView-specific Trame controller registrations."""


def register_paraview_controllers(
    ctrl,
    state,
    *,
    is_paraview_backend,
    pv_backend,
    edit_session,
    refresh_runtime_message,
    update_paraview_ui_state,
    render_and_push,
    save_paraview_output,
    debug_view,
    call_view_update_geometry,
    call_view_set_remote_rendering,
    call_view_update,
    sync_edit_session_state,
    sync_paraview_edit_selection_overlay,
    summarize_edit_event,
    normalize_edit_selection_ids,
):
    """Register ParaView-only controller callbacks on the provided Trame controller."""
    def _sync_edit_mode_from_state():
        mode = (
            getattr(state, "edit_geometry_mode", None)
            or getattr(edit_session, "geometry_mode", None)
            or "volume"
        )
        mode = mode.strip().lower()
        if mode not in {"volume", "surface", "edge", "point"}:
            mode = "volume"
        edit_session.geometry_mode = mode
        return mode

    def _apply_edit_field(*, overwrite):
        mode = _sync_edit_mode_from_state()
        edit_session.field_name = (state.edit_field_name or "").strip()
        edit_session.expression = (state.edit_expression or "").strip()
        edit_session.default_value = (state.edit_default_value or "0").strip()

        if mode != "volume":
            if mode == "surface":
                appended = edit_session.materialize_surface_selection()
                sync_edit_session_state()
                if appended:
                    state.edit_apply_status = (
                        f"Added {appended} missing surface cell(s) from the current selection."
                    )
                    state.edit_apply_status_type = "success"
                else:
                    state.edit_apply_status = (
                        "No new surface cells were added. Selected faces/edges are already present."
                    )
                    state.edit_apply_status_type = "info"
                return
            state.edit_apply_status = (
                f"{mode.capitalize()} mode is visible in the UI but not implemented yet. "
                "Volume and Surface modes are currently supported."
            )
            state.edit_apply_status_type = "info"
            sync_edit_session_state()
            return

        field_name = (state.edit_field_name or "").strip()
        if not overwrite and field_name and edit_session.has_cell_field(field_name):
            state.edit_overwrite_field_name = field_name
            state.edit_overwrite_dialog = True
            state.edit_apply_status = (
                f"Field '{field_name}' already exists. Confirm overwrite to replace it."
            )
            state.edit_apply_status_type = "warning"
            sync_edit_session_state()
            return

        field_name = edit_session.apply_volume_field(
            state.edit_field_name,
            state.edit_expression,
            state.edit_default_value,
            overwrite=overwrite,
        )
        sync_edit_session_state()
        target_scope = (
            f"{edit_session.selected_count()} selected cells"
            if edit_session.selected_count()
            else "all cells"
        )
        state.edit_apply_status = (
            f"Updated cell field '{field_name}' on {target_scope} of the edit-session dataset."
        )
        state.edit_apply_status_type = "success"

    def _set_selection_mode(mode):
        if mode not in {"replace", "add", "subtract", "flip"}:
            mode = "replace"
        state.edit_selection_mode = mode
        state.edit_view_style = (
            "width: 100%; height: 100%; cursor: crosshair; outline: none;"
        )
        return mode

    def _apply_selection_ids(picked_ids, source_label):
        _sync_edit_mode_from_state()
        selection_mode = _set_selection_mode(
            getattr(state, "edit_selection_mode", "replace")
        )

        if selection_mode == "add":
            count = edit_session.add_selection(
                picked_ids, grow=bool(state.group_select)
            )
            action = "Added"
        elif selection_mode == "subtract":
            count = edit_session.subtract_selection(
                picked_ids, grow=bool(state.group_select)
            )
            action = "Removed"
        elif selection_mode == "flip":
            count = edit_session.flip_selection(
                picked_ids, grow=bool(state.group_select)
            )
            action = "Flipped"
        else:
            count = edit_session.replace_selection(
                picked_ids, grow=bool(state.group_select)
            )
            action = "Selected"
        sync_edit_session_state()
        sync_paraview_edit_selection_overlay()
        state.selection_count = count
        state.edit_selection_status = (
            f"{action} {len(picked_ids)} cell(s) with {source_label}. {count} selected total."
        )
        state.edit_selection_status_type = "success"
        render_and_push()

    @ctrl.add("pv_update_property")
    def pv_update_property(scope, name, value):
        """Update a pending ParaView property edit in Trame state."""
        if not is_paraview_backend():
            return

        target = state.source_properties if scope == "source" else state.display_properties
        updated = []
        changed = False
        for item in target:
            if item["name"] == name:
                new_item = dict(item)
                new_item["pending_value"] = value
                updated.append(new_item)
                changed = True
            else:
                updated.append(item)

        if not changed:
            return

        if scope == "source":
            state.source_properties = updated
        else:
            state.display_properties = updated
        state.pv_properties_dirty = True

    @ctrl.add("pv_apply_properties")
    def pv_apply_properties():
        """Apply pending generated ParaView property edits."""
        if not is_paraview_backend():
            return

        refresh_runtime_message(clear=True)
        pv_backend.apply_property_changes(
            state.source_properties, state.display_properties
        )
        refresh_runtime_message()
        update_paraview_ui_state()
        render_and_push()

    @ctrl.add("pv_reset_properties")
    def pv_reset_properties():
        """Discard pending property edits and refresh the generated inspector."""
        if not is_paraview_backend():
            return

        update_paraview_ui_state()

    @ctrl.add("pv_toggle_visibility")
    def pv_toggle_visibility():
        """Toggle visibility of the active ParaView node."""
        if not is_paraview_backend() or not state.active_pipeline_item:
            return

        pv_backend.set_visibility(state.active_pipeline_item, not state.active_visibility)
        update_paraview_ui_state()
        render_and_push()

    @ctrl.add("pv_toggle_visibility_for")
    def pv_toggle_visibility_for(node_id):
        """Toggle visibility for a specific ParaView pipeline node."""
        if not is_paraview_backend() or not node_id:
            return

        visible = pv_backend.get_visibility(node_id)
        if visible is None:
            return

        pv_backend.set_visibility(node_id, not visible)
        update_paraview_ui_state()
        render_and_push()

    @ctrl.add("pv_delete_active")
    def pv_delete_active():
        """Delete the active ParaView node from the pipeline."""
        if not is_paraview_backend() or not state.active_pipeline_item:
            return

        pv_backend.delete_node(state.active_pipeline_item)
        update_paraview_ui_state()
        if not state.active_pipeline_item:
            state.selected_file = ""
        state.save_status = ""
        render_and_push()

    @ctrl.add("pv_add_filter")
    def pv_add_filter(filter_key):
        """Add a supported filter to the active ParaView node."""
        if not is_paraview_backend() or not state.active_pipeline_item:
            return
        if not filter_key:
            return

        try:
            refresh_runtime_message(clear=True)
            pv_backend.add_filter(filter_key)
            refresh_runtime_message()
            state.filter_menu = False
            update_paraview_ui_state()
            render_and_push()
        except Exception as exc:
            state.error_message = f"Error adding filter: {exc}"

    @ctrl.add("pv_save_active_data")
    def pv_save_active_data():
        """Save the active ParaView output or edit-session result to a new file."""
        if not is_paraview_backend():
            return

        try:
            save_paraview_output()
        except Exception as exc:
            state.save_status = f"Error: {exc}"
            state.save_status_type = "error"

    @ctrl.add("pv_begin_edit_session")
    def pv_begin_edit_session():
        """Initialize an edit session from the active ParaView pipeline node."""
        if not is_paraview_backend():
            return

        try:
            debug_view("pv_begin_edit_session.start", mode=state.mainViewMode)
            exported = pv_backend.export_active_dataset_for_editing()
            edit_session.begin(
                exported["node_id"],
                exported["label"],
                exported["filename"],
                exported["dataset"],
            )

            pv_backend.apply_representation("Surface with Edges")
            state.pick_mode = True

            state.mainViewMode = "remote"
            call_view_set_remote_rendering(True)

            call_view_update_geometry(reset_camera=True)
            state.edit_session_active = True
            state.save_filename = edit_session.default_output_filename()
            state.save_target_label = f"Edited dataset: {exported['label']}"
            state.save_status = ""
            state.edit_apply_status = ""
            state.edit_selection_status = ""
            state.edit_selection_event = ""
            state.selection_count = 0
            state.inspector_tab = 3
            _set_selection_mode("replace")
            sync_edit_session_state()
            sync_paraview_edit_selection_overlay()
            render_and_push()
            debug_view("pv_begin_edit_session.end", mode=state.mainViewMode)
            state.edit_status = (
                f"Edit session initialized for {exported['label']}. "
                "Volume-mode picking and field authoring are available."
            )
            state.edit_status_type = "info"
        except Exception as exc:
            state.edit_session_active = False
            state.edit_session_label = ""
            state.edit_status = f"Edit mode unavailable: {exc}"
            state.edit_status_type = "error"

    @ctrl.add("pv_discard_edit_session")
    def pv_discard_edit_session():
        """Discard the current edit session."""
        debug_view("pv_discard_edit_session.start", mode=state.mainViewMode)
        edit_session.clear()
        sync_edit_session_state()
        sync_paraview_edit_selection_overlay()
        if is_paraview_backend() and pv_backend is not None:
            state.save_filename = pv_backend.default_output_filename()
            state.save_target_label = (
                f"Active pipeline result: {state.active_source_label}"
                if state.active_source_label
                else "Active pipeline result"
            )
        state.edit_apply_status = ""
        state.edit_selection_status = ""
        state.edit_selection_event = ""
        state.selection_count = 0
        state.inspector_tab = 0
        _set_selection_mode("replace")
        call_view_set_remote_rendering(True)
        call_view_update(reset_camera=True)
        debug_view("pv_discard_edit_session.end", mode=state.mainViewMode)
        state.edit_status = "Edit session discarded"
        state.edit_status_type = "info"

    @ctrl.add("pv_commit_edit_session")
    def pv_commit_edit_session():
        """Save the current edit session and append it as a new pipeline source."""
        if not is_paraview_backend() or not edit_session.active:
            return

        try:
            debug_view("pv_commit_edit_session.start", mode=state.mainViewMode)
            output_path = save_paraview_output()
            edit_session.clear()
            sync_edit_session_state()
            sync_paraview_edit_selection_overlay()
            state.inspector_tab = 0
            call_view_set_remote_rendering(True)
            state.edit_status = "Edit session saved and added to the pipeline"
            state.edit_status_type = "success"

            arrays, default_array = pv_backend.load_file(output_path)
            pv_backend.apply_representation(state.representation)
            pv_backend.apply_coloring(default_array)
            update_paraview_ui_state()
            state.available_arrays = arrays
            state.selected_array = default_array
            render_and_push()
            debug_view("pv_commit_edit_session.end", mode=state.mainViewMode)
        except Exception as exc:
            state.edit_status = f"Could not add edited result to pipeline: {exc}"
            state.edit_status_type = "error"

    @ctrl.add("pv_apply_edit_field")
    def pv_apply_edit_field():
        """Apply the current edit-session field operation."""
        if not is_paraview_backend() or not edit_session.active:
            return

        try:
            _apply_edit_field(overwrite=False)
        except Exception as exc:
            sync_edit_session_state()
            state.edit_apply_status = f"Edit apply failed: {exc}"
            state.edit_apply_status_type = "error"

    @ctrl.add("pv_confirm_overwrite_edit_field")
    def pv_confirm_overwrite_edit_field():
        """Confirm overwrite of an existing edit field and apply the operation."""
        if not is_paraview_backend() or not edit_session.active:
            return

        try:
            state.edit_overwrite_dialog = False
            state.edit_overwrite_field_name = ""
            _apply_edit_field(overwrite=True)
        except Exception as exc:
            sync_edit_session_state()
            state.edit_apply_status = f"Edit apply failed: {exc}"
            state.edit_apply_status_type = "error"

    @ctrl.add("pv_cancel_overwrite_edit_field")
    def pv_cancel_overwrite_edit_field():
        """Dismiss overwrite confirmation without modifying the dataset."""
        state.edit_overwrite_dialog = False
        state.edit_overwrite_field_name = ""

    @ctrl.add("pv_edit_click_selection")
    def pv_edit_click_selection(event):
        """Capture single-click picking events for edit-session selection."""
        if not is_paraview_backend() or not edit_session.active or not state.pick_mode:
            return

        state.edit_selection_event = summarize_edit_event(event)
        normalized = normalize_edit_selection_ids(event)
        picked_ids = []

        coords = next(
            (
                (item[1], item[2])
                for item in normalized
                if isinstance(item, tuple)
                and len(item) == 3
                and item[0] == "coords"
            ),
            None,
        )
        if coords is not None:
            picked_ids = pv_backend.pick_visible_cell_ids(coords[0], coords[1])
        else:
            picked_ids = [item for item in normalized if isinstance(item, int)]

        if not picked_ids:
            state.edit_selection_status = (
                "Click selection did not resolve any editable cells."
            )
            state.edit_selection_status_type = "info"
            return

        _apply_selection_ids(picked_ids, "click selection")

    @ctrl.add("pv_edit_box_selection")
    def pv_edit_box_selection(event):
        """Capture native local-view box-selection events."""
        if not is_paraview_backend() or not edit_session.active or not state.pick_mode:
            return

        state.edit_selection_event = summarize_edit_event(event)
        selection = event.get("selection") if isinstance(event, dict) else None
        if not isinstance(selection, (list, tuple)) or len(selection) != 4:
            state.edit_selection_status = "Box selection did not include a usable rectangle."
            state.edit_selection_status_type = "warning"
            return

        x0, x1, y0, y1 = selection
        picked_ids = pv_backend.pick_visible_cell_ids_in_rect(
            x0,
            y0,
            x1,
            y1,
            behavior=(state.selection_behavior or "touch"),
        )
        if not picked_ids:
            state.edit_selection_status = "Box selection did not resolve any editable cells."
            state.edit_selection_status_type = "info"
            return

        _apply_selection_ids(picked_ids, "box selection")

    @ctrl.add("pv_clear_edit_preview")
    def pv_clear_edit_preview():
        """Clear the temporary selection preview state for ParaView edit mode."""
        if not is_paraview_backend():
            return

        _sync_edit_mode_from_state()
        edit_session.clear_selection()
        sync_edit_session_state()
        sync_paraview_edit_selection_overlay()
        state.edit_selection_event = ""
        state.edit_selection_status = "Selection cleared."
        state.edit_selection_status_type = "info"
        render_and_push()

    @ctrl.add("pv_select_all_edit_cells")
    def pv_select_all_edit_cells():
        """Select every editable cell in the current edit-session dataset."""
        if not is_paraview_backend() or not edit_session.active:
            return

        _sync_edit_mode_from_state()
        count = edit_session.select_all_cells()
        sync_edit_session_state()
        sync_paraview_edit_selection_overlay()
        state.selection_count = count
        state.edit_selection_status = (
            f"Selected all {count} cell(s) in the edit-session dataset."
        )
        state.edit_selection_status_type = "success"
        render_and_push()
