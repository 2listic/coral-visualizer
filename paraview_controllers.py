"""ParaView-specific Trame controller registrations."""

from __future__ import annotations

from contextlib import nullcontext
from typing import TYPE_CHECKING, Callable, Protocol

from notifications import notify
from selection_debug import SelectionDebugLogger
from selection_timing import SelectionTiming

if TYPE_CHECKING:
    from trame_server.controller import Controller
    from trame_server.state import State

    from edit_session import EditSession
    from paraview_backend import ParaViewBackend


class _RefreshRuntimeMessage(Protocol):
    def __call__(self, *, clear: bool = False) -> None: ...


def register_paraview_controllers(
    ctrl: Controller,
    state: State,
    *,
    pv_backend: ParaViewBackend,
    edit_session: EditSession,
    refresh_runtime_message: _RefreshRuntimeMessage,
    update_paraview_ui_state: Callable[[], None],
    update_color_state: Callable[[], None],
    render_and_push: Callable[[], None],
    save_paraview_output,
    debug_view,
    call_view_update_geometry,
    call_view_set_remote_rendering,
    call_view_update,
    sync_edit_session_state: Callable[[], None],
    sync_paraview_edit_selection_overlay: Callable[[], None],
    summarize_edit_event,
    normalize_edit_selection_ids,
    save_paraview_state=None,
    load_paraview_state=None,
):
    """Register ParaView-only controller callbacks on the provided Trame controller."""
    selection_debug = SelectionDebugLogger(
        pv_backend=pv_backend,
        debug_view=debug_view,
    )

    def _sync_edit_mode_from_state():
        mode = state.edit_geometry_mode or edit_session.geometry_mode or "volume"
        mode = mode.strip().lower()
        if mode not in {"volume", "surface", "point"}:
            mode = "volume"
        edit_session.geometry_mode = mode
        return mode

    def _parse_field_choice():
        choice = (state.edit_field_choice or "").strip()
        if not choice:
            return "", ""
        if ":" not in choice:
            return "", ""
        association, name = choice.split(":", 1)
        association = association.strip().lower()
        name = name.strip()
        if association not in {"cell", "point"} or not name:
            return "", ""
        return association, name

    def _close_save_overwrite_dialog():
        state.save_overwrite_dialog = False
        state.save_overwrite_target = ""
        state.save_overwrite_action = ""

    def _open_save_overwrite_dialog(action, exc):
        state.save_overwrite_action = action
        state.save_overwrite_target = (
            getattr(exc, "filename", "") or state.save_filename
        )
        state.save_overwrite_dialog = True

    def _save_application_state(overwrite=False):
        if not callable(save_paraview_state):
            raise RuntimeError("Application state save is not available")
        save_paraview_state(overwrite=overwrite)

    def _load_application_state():
        if not callable(load_paraview_state):
            raise RuntimeError("Application state load is not available")
        snapshot, _path = load_paraview_state()
        edit_session.clear()
        pv_backend.clear_edit_target_dataset()
        sync_edit_session_state()
        sync_paraview_edit_selection_overlay()

        pv_backend.import_app_state(snapshot)
        update_paraview_ui_state()
        state.selected_file = snapshot.get("selected_file", state.selected_file)
        state.inspector_tab = snapshot.get("inspector_tab", state.inspector_tab)
        notify(
            state, f"Loaded application state from {state.state_filename}", "success"
        )
        render_and_push()

    def _commit_edit_session(filename=None, overwrite=False):
        debug_view("pv_commit_edit_session.start", mode=state.mainViewMode)
        output_path = save_paraview_output(filename=filename, overwrite=overwrite)
        edit_session.clear()
        pv_backend.clear_edit_target_dataset()
        sync_edit_session_state()
        sync_paraview_edit_selection_overlay()
        state.inspector_tab = 0
        call_view_set_remote_rendering(True)
        notify(state, "Edit session saved and added to the pipeline", "success")

        arrays, default_array = pv_backend.load_file(output_path)
        pv_backend.apply_representation(state.representation)
        pv_backend.apply_coloring(default_array)
        update_paraview_ui_state()
        state.available_arrays = arrays
        state.selected_array = default_array
        render_and_push()
        debug_view("pv_commit_edit_session.end", mode=state.mainViewMode)

    def _apply_geometry_options_for_association(association):
        if association == "point":
            state.edit_geometry_mode_options = list(
                state.edit_point_geometry_mode_options
            )
            state.edit_geometry_mode = "point"
            edit_session.geometry_mode = "point"
            return "point"
        state.edit_geometry_mode_options = list(state.edit_cell_geometry_mode_options)
        mode = (state.edit_geometry_mode or "").strip().lower()
        if mode not in {"volume", "surface"}:
            mode = "volume"
            state.edit_geometry_mode = mode
        edit_session.geometry_mode = mode
        return mode

    def _apply_edit_field():
        association, field_name = _parse_field_choice()
        if not association or not field_name:
            raise RuntimeError("Select a field before assigning values.")

        mode = _apply_geometry_options_for_association(association)
        expression = (state.edit_expression or "").strip()
        field_name = edit_session.assign_to_selected(
            field_name, association, expression
        )
        sync_edit_session_state()

        if mode == "surface":
            scope = "surface element(s)"
        elif mode == "point":
            scope = "point(s)"
        else:
            scope = "cell(s)"
        notify(
            state,
            f"Assigned '{field_name}' on {edit_session.selected_count()} selected {scope}.",
            "success",
        )

    def _set_selection_mode(mode):
        if mode not in {"replace", "add", "subtract", "flip"}:
            mode = "replace"
        state.edit_selection_mode = mode
        state.edit_view_style = (
            "width: 100%; height: 100%; cursor: crosshair; outline: none;"
        )
        return mode

    def _sync_color_controls():
        update_paraview_ui_state()
        render_and_push()

    def _preview_list(values, limit=12):
        seq = list(values or [])
        if len(seq) <= limit:
            return seq
        return seq[:limit] + [f"...(+{len(seq) - limit})"]

    def _expected_editable_from_picks(mode, picked_ids):
        if mode == "surface":
            if len(picked_ids or []) > 50:
                return []
            try:
                resolved = edit_session._surface_keys_from_top_cells(picked_ids)
                return sorted(resolved)
            except Exception:
                return []
        if mode == "point":
            dataset = edit_session.working_dataset
            if dataset is None:
                return []
            point_count = dataset.GetNumberOfPoints()
            return sorted(
                {
                    int(point_id)
                    for point_id in (picked_ids or [])
                    if isinstance(point_id, (int, float))
                    and 0 <= int(point_id) < point_count
                }
            )
        dataset = edit_session.working_dataset
        if dataset is None:
            return []
        cell_count = dataset.GetNumberOfCells()
        return sorted(
            {
                int(cell_id)
                for cell_id in (picked_ids or [])
                if isinstance(cell_id, (int, float)) and 0 <= int(cell_id) < cell_count
            }
        )

    def _refresh_color_state():
        update_color_state()
        render_and_push()

    def _restore_active_color_controls(*, visible, range_min, range_max):
        preset = (state.color_map_preset or "").strip()
        if preset:
            try:
                pv_backend.apply_color_map_preset(preset)
            except Exception as exc:
                _set_color_status(f"Color map restore skipped: {exc}", "warning")

        if range_min != "" and range_max != "":
            try:
                pv_backend.apply_color_range(range_min, range_max)
            except Exception as exc:
                _set_color_status(f"Color range restore skipped: {exc}", "warning")

        try:
            pv_backend.set_categorical_coloring(bool(state.categorical_coloring))
        except Exception as exc:
            _set_color_status(f"Categorical coloring restore skipped: {exc}", "warning")

        try:
            pv_backend.set_scalar_bar_visible(visible)
        except Exception as exc:
            _set_color_status(f"Color scale restore skipped: {exc}", "warning")

    def _set_color_status(message, status_type="success"):
        notify(state, message, status_type)

    def _flush_time_state():
        """Push time-related state updates to the client when available."""
        dirty = getattr(state, "dirty", None)
        if callable(dirty):
            for key in (
                "time_values",
                "current_time",
                "time_index",
                "total_timesteps",
                "is_time_dependent",
                "time_playing",
                "time_loop",
            ):
                try:
                    dirty(key)
                except Exception:
                    pass
        flush = getattr(state, "flush", None)
        if callable(flush):
            try:
                flush()
            except Exception:
                pass

    def _apply_selection_ids(picked_ids, source_label, timing=None, mode=None):
        if mode is None:
            with timing.phase("sync_mode") if timing else nullcontext():
                mode = _sync_edit_mode_from_state()
        with timing.phase("selection_mode") if timing else nullcontext():
            selection_mode = _set_selection_mode(state.edit_selection_mode)
            angle_threshold = state.angle_threshold
        with timing.phase("resolve_expected") if timing else nullcontext():
            expected = _expected_editable_from_picks(mode, picked_ids)
        print(
            "[selection-debug] controller.apply.begin "
            f"mode={mode} selection_mode={selection_mode} source={source_label!r} "
            f"picked_count={len(picked_ids)} picked={_preview_list(picked_ids)} "
            f"expected_editable_count={len(expected)} expected_editable={_preview_list(expected)}"
        )

        with timing.phase("edit_session_apply") if timing else nullcontext():
            if selection_mode == "add":
                count = edit_session.add_selection(
                    picked_ids,
                    grow=bool(state.group_select),
                    angle_threshold=angle_threshold,
                )
                action = "Added"
            elif selection_mode == "subtract":
                count = edit_session.subtract_selection(
                    picked_ids,
                    grow=bool(state.group_select),
                    angle_threshold=angle_threshold,
                )
                action = "Removed"
            elif selection_mode == "flip":
                count = edit_session.flip_selection(
                    picked_ids,
                    grow=bool(state.group_select),
                    angle_threshold=angle_threshold,
                )
                action = "Flipped"
            else:
                count = edit_session.replace_selection(
                    picked_ids,
                    grow=bool(state.group_select),
                    angle_threshold=angle_threshold,
                )
                action = "Selected"
        with timing.phase("sync_edit_state") if timing else nullcontext():
            sync_edit_session_state()
            state.selection_count = count
        with timing.phase("sync_overlay") if timing else nullcontext():
            sync_paraview_edit_selection_overlay()
        if mode == "surface":
            entity_label = "surface element(s)"
        elif mode == "point":
            entity_label = "point(s)"
        else:
            entity_label = "cell(s)"
        notify(
            state,
            f"{action} {len(picked_ids)} {entity_label} with {source_label}. {count} selected total.",
            "success",
        )
        if mode == "surface":
            selected_now = sorted(edit_session.selected_surface_keys)
        elif mode == "point":
            selected_now = sorted(edit_session.selected_point_ids)
        else:
            selected_now = sorted(edit_session.selected_cell_ids)
        print(
            "[selection-debug] controller.apply.end "
            f"mode={mode} selection_mode={selection_mode} "
            f"selected_total={count} selected_now={_preview_list(selected_now)}"
        )
        if timing:
            timing.update(
                mode=mode,
                selection_mode=selection_mode,
                picked_count=len(picked_ids),
                selected_total=count,
                source=source_label,
            )
        with timing.phase("render") if timing else nullcontext():
            render_and_push()

    def _pick_edit_ids_at_coords(mode, x, y):
        if mode == "surface":
            picked_ids = pv_backend.pick_visible_surface_keys(x, y)
            if not picked_ids:
                picked_ids = pv_backend.pick_visible_cell_ids(x, y)
            return picked_ids
        if mode == "point":
            return pv_backend.pick_visible_point_ids(x, y)
        return pv_backend.pick_visible_cell_ids(x, y)

    def _append_backend_timing(timing):
        if timing is None:
            return
        for phase in pv_backend.consume_selection_backend_timing() or []:
            name = phase.get("name") if isinstance(phase, dict) else None
            duration_ms = phase.get("ms") if isinstance(phase, dict) else None
            if name is not None and duration_ms is not None:
                timing.add_phase(f"backend.{name}", duration_ms)

    def _pick_edit_ids_in_rect(mode, x0, y0, x1, y1):
        behavior = state.selection_behavior or "touch"
        if mode == "surface":
            picked_ids = pv_backend.pick_visible_surface_keys_in_rect(
                x0, y0, x1, y1, behavior=behavior
            )
            if not picked_ids and behavior == "inside":
                picked_ids = pv_backend.pick_visible_surface_keys_in_rect(
                    x0, y0, x1, y1, behavior="touch"
                )
            if not picked_ids:
                picked_ids = pv_backend.pick_visible_cell_ids_in_rect(
                    x0, y0, x1, y1, behavior=behavior
                )
            if not picked_ids and behavior == "inside":
                picked_ids = pv_backend.pick_visible_cell_ids_in_rect(
                    x0, y0, x1, y1, behavior="touch"
                )
            return picked_ids
        if mode == "point":
            return pv_backend.pick_visible_point_ids_in_rect(
                x0, y0, x1, y1, behavior=behavior
            )
        return pv_backend.pick_visible_cell_ids_in_rect(
            x0, y0, x1, y1, behavior=behavior
        )

    def _set_empty_selection_status(mode, interaction):
        entity_label = "points" if mode == "point" else "cells"
        notify(
            state,
            f"{interaction} selection did not resolve any editable {entity_label}.",
            "info",
        )

    def _extract_size_pair(value):
        if isinstance(value, dict):
            candidates = (
                (value.get("width"), value.get("height")),
                (value.get("x"), value.get("y")),
            )
        elif isinstance(value, (list, tuple)) and len(value) >= 2:
            candidates = ((value[0], value[1]),)
        else:
            candidates = ()
        for width, height in candidates:
            try:
                width = float(width)
                height = float(height)
            except (TypeError, ValueError):
                continue
            if width > 0.0 and height > 0.0:
                return width, height
        return None, None

    def _view_size():
        view = pv_backend.view
        if view is None or not hasattr(view, "ViewSize"):
            return None, None
        try:
            width, height = view.ViewSize
            width = float(width)
            height = float(height)
        except (TypeError, ValueError):
            return None, None
        if width <= 0.0 or height <= 0.0:
            return None, None
        return width, height

    def _scale_box_selection_to_view(event, x0, x1, y0, y1):
        try:
            x0 = float(x0)
            x1 = float(x1)
            y0 = float(y0)
            y1 = float(y1)
        except (TypeError, ValueError):
            return x0, x1, y0, y1

        event_width, event_height = _extract_size_pair(
            event.get("size") if isinstance(event, dict) else None
        )
        view_width, view_height = _view_size()
        if event_width and view_width:
            scale_x = view_width / event_width
            x0 *= scale_x
            x1 *= scale_x
        if event_height and view_height:
            scale_y = view_height / event_height
            y0 *= scale_y
            y1 *= scale_y
        return x0, x1, y0, y1

    @ctrl.add("pv_update_property")
    def pv_update_property(scope, name, value):
        """Update a pending ParaView property edit in Trame state."""

        target = (
            state.source_properties if scope == "source" else state.display_properties
        )
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

        update_paraview_ui_state()

    @ctrl.add("pv_toggle_visibility")
    def pv_toggle_visibility():
        """Toggle visibility of the active ParaView node."""
        if not state.active_pipeline_item:
            return

        pv_backend.set_visibility(
            state.active_pipeline_item, not state.active_visibility
        )
        update_paraview_ui_state()
        render_and_push()

    @ctrl.add("pv_toggle_visibility_for")
    def pv_toggle_visibility_for(node_id):
        """Toggle visibility for a specific ParaView pipeline node."""
        if not node_id:
            return

        visible = pv_backend.get_visibility(node_id)
        if visible is None:
            return

        pv_backend.set_visibility(node_id, not visible)
        update_paraview_ui_state()
        render_and_push()

    @ctrl.add("pv_set_cell_face_visibility")
    def pv_set_cell_face_visibility(cells_visible=None, faces_visible=None):
        """Show or hide semantic cells/faces for the active ParaView node."""
        if not state.active_pipeline_item:
            return

        if (
            faces_visible is None
            and isinstance(cells_visible, (list, tuple))
            and len(cells_visible) >= 2
        ):
            cells_visible, faces_visible = cells_visible[:2]
        if cells_visible is None:
            cells_visible = state.show_cells
        if faces_visible is None:
            faces_visible = state.show_faces

        try:
            pv_backend.set_cell_face_visibility(
                bool(cells_visible), bool(faces_visible)
            )
            update_paraview_ui_state()
            render_and_push()
        except Exception as exc:
            notify(state, f"Error updating cell visibility: {exc}", "error")

    @ctrl.add("pv_reload_active_file")
    def pv_reload_active_file():
        """Reload the file backing the active ParaView pipeline node."""
        if not state.active_pipeline_item:
            return

        try:
            property_restore_error = ""
            selected_array = state.selected_array or ""
            color_bar_visible = bool(state.color_bar_visible)
            color_range_min = state.color_range_min
            color_range_max = state.color_range_max
            show_cells = bool(state.show_cells)
            show_faces = bool(state.show_faces)
            source_properties = [dict(item) for item in state.source_properties or []]
            display_properties = [dict(item) for item in state.display_properties or []]
            refresh_runtime_message(clear=True)
            _arrays, default_array = pv_backend.reload_node_file(
                state.active_pipeline_item
            )
            pv_backend.apply_representation(state.representation)
            pv_backend.apply_coloring(selected_array or default_array)
            pv_backend.set_cell_face_visibility(show_cells, show_faces)
            try:
                pv_backend.apply_property_changes(source_properties, display_properties)
            except Exception as exc:
                property_restore_error = (
                    f"Some pipeline properties could not be restored: {exc}"
                )
            _restore_active_color_controls(
                visible=color_bar_visible,
                range_min=color_range_min,
                range_max=color_range_max,
            )
            refresh_runtime_message()
            update_paraview_ui_state()
            state.has_boundary = False
            state.selection_count = 0
            if property_restore_error:
                notify(state, property_restore_error, "warning")
            render_and_push()
        except Exception as exc:
            notify(state, f"Error reloading pipeline file: {exc}", "error")

    @ctrl.add("pv_delete_active")
    def pv_delete_active():
        """Delete the active ParaView node from the pipeline."""
        if not state.active_pipeline_item:
            return

        pv_backend.delete_node(state.active_pipeline_item)
        update_paraview_ui_state()
        if not state.active_pipeline_item:
            state.selected_file = ""
        render_and_push()

    @ctrl.add("pv_add_filter")
    def pv_add_filter(filter_key):
        """Add a supported filter to the active ParaView node."""
        if not state.active_pipeline_item:
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
            notify(state, f"Error adding filter: {exc}", "error")

    @ctrl.add("pv_save_active_data")
    def pv_save_active_data():
        """Open the save dialog for saving the active output or edit-session result."""
        state.save_dialog_action = "save"
        state.save_dialog = True

    @ctrl.add("pv_confirm_save_dialog")
    def pv_confirm_save_dialog(filename=None):
        """Perform the save confirmed from the save dialog."""
        action = state.save_dialog_action
        state.save_dialog = False
        state.save_dialog_action = ""
        try:
            if action == "commit":
                _commit_edit_session(filename=filename)
            else:
                save_paraview_output(filename=filename)
        except FileExistsError as exc:
            _open_save_overwrite_dialog(action, exc)
        except Exception as exc:
            notify(state, f"Error: {exc}", "error")

    @ctrl.add("pv_cancel_save_dialog")
    def pv_cancel_save_dialog():
        """Dismiss the save dialog without saving."""
        state.save_dialog = False
        state.save_dialog_action = ""

    @ctrl.add("pv_save_state")
    def pv_save_state(filename=None):
        """Save the current ParaView application state to disk."""

        try:
            if filename is not None:
                candidate = str(filename).strip()
                if candidate:
                    state.state_filename = candidate
            _save_application_state()
        except FileExistsError as exc:
            _open_save_overwrite_dialog("state_save", exc)
        except Exception as exc:
            notify(state, f"Error: {exc}", "error")

    @ctrl.add("pv_load_state")
    def pv_load_state(filename=None):
        """Load a previously saved ParaView application state from disk."""

        try:
            if filename is not None:
                candidate = str(filename).strip()
                if candidate:
                    state.state_filename = candidate
            state.state_browser_dialog = False
            _load_application_state()
        except Exception as exc:
            notify(state, f"Error: {exc}", "error")

    @ctrl.add("pv_confirm_save_overwrite")
    def pv_confirm_save_overwrite():
        """Confirm overwrite for ParaView save operations."""

        action = state.save_overwrite_action
        filename = state.save_overwrite_target
        try:
            _close_save_overwrite_dialog()
            if action == "commit":
                _commit_edit_session(filename=filename, overwrite=True)
            elif action == "state_save":
                _save_application_state(overwrite=True)
            else:
                save_paraview_output(filename=filename, overwrite=True)
        except Exception as exc:
            notify(state, f"Error: {exc}", "error")

    @ctrl.add("pv_cancel_save_overwrite")
    def pv_cancel_save_overwrite():
        """Dismiss save overwrite confirmation without saving."""
        _close_save_overwrite_dialog()

    @ctrl.add("pv_begin_edit_session")
    def pv_begin_edit_session():
        """Initialize an edit session from the active ParaView pipeline node."""

        try:
            debug_view("pv_begin_edit_session.start", mode=state.mainViewMode)
            exported = pv_backend.export_active_dataset_for_editing()
            edit_session.begin(
                exported["node_id"],
                exported["label"],
                exported["filename"],
                exported["dataset"],
            )
            pv_backend.set_edit_target_dataset(edit_session.working_dataset)

            pv_backend.apply_representation("Surface with Edges")
            state.pick_mode = True

            state.mainViewMode = "remote"
            call_view_set_remote_rendering(True)

            call_view_update_geometry(reset_camera=True)
            state.edit_session_active = True
            state.save_filename = edit_session.default_output_filename()
            state.save_target_label = f"Edited dataset: {exported['label']}"
            state.edit_selection_event = ""
            state.selection_count = 0
            state.inspector_tab = 3
            _set_selection_mode("replace")
            update_paraview_ui_state()
            sync_edit_session_state()
            sync_paraview_edit_selection_overlay()
            render_and_push()
            debug_view("pv_begin_edit_session.end", mode=state.mainViewMode)
            notify(state, f"Edit session initialized for {exported['label']}.", "info")
        except Exception as exc:
            state.edit_session_active = False
            state.edit_session_label = ""
            notify(state, f"Edit mode unavailable: {exc}", "error")

    @ctrl.add("pv_discard_edit_session")
    def pv_discard_edit_session():
        """Discard the current edit session."""
        debug_view("pv_discard_edit_session.start", mode=state.mainViewMode)
        edit_session.clear()
        pv_backend.clear_edit_target_dataset()
        update_paraview_ui_state()
        sync_edit_session_state()
        sync_paraview_edit_selection_overlay()
        state.save_filename = pv_backend.default_output_filename()
        state.save_target_label = (
            f"Active pipeline result: {state.active_source_label}"
            if state.active_source_label
            else "Active pipeline result"
        )
        state.edit_selection_event = ""
        state.selection_count = 0
        state.inspector_tab = 0
        _set_selection_mode("replace")
        call_view_set_remote_rendering(True)
        call_view_update(reset_camera=True)
        debug_view("pv_discard_edit_session.end", mode=state.mainViewMode)
        notify(state, "Edit session discarded", "info")

    @ctrl.add("pv_commit_edit_session")
    def pv_commit_edit_session():
        """Open the save dialog for committing the edit session to the pipeline."""
        if not edit_session.active:
            return
        state.save_dialog_action = "commit"
        state.save_dialog = True

    @ctrl.add("pv_apply_color_map_preset")
    def pv_apply_color_map_preset(preset=None):
        """Apply the selected color-map preset to the active scalar coloring."""
        if pv_backend.display is None:
            return
        preset = (preset or state.color_map_preset or "").strip()
        if not preset:
            return
        try:
            state.color_map_preset = preset
            pv_backend.apply_color_map_preset(preset)
            _refresh_color_state()
            _set_color_status(f"Applied color map '{preset}'.")
        except Exception as exc:
            _set_color_status(f"Color map update failed: {exc}", "error")

    @ctrl.add("pv_apply_color_range")
    def pv_apply_color_range():
        """Apply manual min/max values to the active scalar color range."""
        if pv_backend.display is None:
            return
        try:
            pv_backend.apply_color_range(state.color_range_min, state.color_range_max)
            _refresh_color_state()
            _set_color_status("Applied color range.")
        except Exception as exc:
            _set_color_status(f"Color range update failed: {exc}", "error")

    @ctrl.add("pv_rescale_color_range_to_data")
    def pv_rescale_color_range_to_data():
        """Rescale the active color map to the visible data range."""
        if pv_backend.display is None:
            return
        try:
            pv_backend.rescale_color_range_to_data()
            _refresh_color_state()
            _set_color_status("Rescaled color range to data.")
        except Exception as exc:
            _set_color_status(f"Color range rescale failed: {exc}", "error")

    @ctrl.add("pv_rescale_color_range_over_time")
    def pv_rescale_color_range_over_time():
        """Rescale the active color map over all timesteps."""
        if pv_backend.display is None:
            return
        try:
            pv_backend.rescale_color_range_over_time()
            _refresh_color_state()
            _set_color_status("Rescaled color range over time.")
            state.rescale_over_time_dialog = False
        except Exception as exc:
            _set_color_status(f"Color range rescale over time failed: {exc}", "error")

    @ctrl.add("pv_set_time")
    def pv_set_time(time_value):
        """Set the current time from the UI."""
        try:
            pv_backend.set_time(time_value)
            update_paraview_ui_state()
            render_and_push()
            _flush_time_state()
        except Exception as exc:
            notify(state, f"Error setting time: {exc}", "error")

    @ctrl.add("pv_next_time_step")
    def pv_next_time_step():
        """Move to the next available timestep."""
        try:
            pv_backend.set_time_step(1)
            update_paraview_ui_state()
            render_and_push()
            _flush_time_state()
        except Exception as exc:
            notify(state, f"Error moving to next timestep: {exc}", "error")

    @ctrl.add("pv_prev_time_step")
    def pv_prev_time_step():
        """Move to the previous available timestep."""
        try:
            pv_backend.set_time_step(-1)
            update_paraview_ui_state()
            render_and_push()
            _flush_time_state()
        except Exception as exc:
            notify(state, f"Error moving to previous timestep: {exc}", "error")

    @ctrl.add("pv_first_time_step")
    def pv_first_time_step():
        """Move to the first available timestep."""
        try:
            if state.time_values:
                pv_backend.set_time(state.time_values[0])
                update_paraview_ui_state()
                render_and_push()
                _flush_time_state()
        except Exception as exc:
            notify(state, f"Error moving to first timestep: {exc}", "error")

    @ctrl.add("pv_last_time_step")
    def pv_last_time_step():
        """Move to the last available timestep."""
        try:
            if state.time_values:
                pv_backend.set_time(state.time_values[-1])
                update_paraview_ui_state()
                render_and_push()
                _flush_time_state()
        except Exception as exc:
            notify(state, f"Error moving to last timestep: {exc}", "error")

    @ctrl.add("pv_play_pause_time")
    def pv_play_pause_time():
        """Toggle time animation playing."""
        state.time_playing = not state.time_playing
        _flush_time_state()
        if state.time_playing:
            ctrl.pv_animate_step()

    @ctrl.add("pv_toggle_time_loop")
    def pv_toggle_time_loop():
        """Toggle looping while playing the time animation."""
        state.time_loop = not bool(state.time_loop)
        _flush_time_state()

    @ctrl.add("pv_animate_step")
    def pv_animate_step():
        """Perform a single animation step if playing."""
        if not state.time_playing:
            return

        try:
            old_index = state.time_index
            pv_backend.set_time_step(1)
            update_paraview_ui_state()
            render_and_push()
            _flush_time_state()

            # Loop if we didn't advance (at end)
            if state.time_index == old_index and state.total_timesteps > 1:
                if bool(state.time_loop):
                    pv_backend.set_time(state.time_values[0])
                    update_paraview_ui_state()
                    render_and_push()
                    _flush_time_state()
                else:
                    state.time_playing = False
                    _flush_time_state()
                    return

            # Schedule next step
            import asyncio

            async def _next():
                await asyncio.sleep(0.1)
                ctrl.pv_animate_step()

            asyncio.create_task(_next())
        except Exception as exc:
            state.time_playing = False
            _flush_time_state()
            notify(state, f"Animation error: {exc}", "error")

    @ctrl.add("pv_set_scalar_bar_visible")
    def pv_set_scalar_bar_visible(visible=None):
        """Toggle the active scalar color legend."""
        if pv_backend.display is None:
            return
        visible = bool(state.color_bar_visible if visible is None else visible)
        try:
            state.color_bar_visible = visible
            pv_backend.set_scalar_bar_visible(visible)
            render_and_push()
        except Exception as exc:
            _set_color_status(f"Color scale update failed: {exc}", "error")

    @ctrl.add("pv_set_orientation_axes_visible")
    def pv_set_orientation_axes_visible(visible=None):
        """Toggle the orientation axes in the render view."""
        visible = bool(state.orientation_axes_visible if visible is None else visible)
        try:
            state.orientation_axes_visible = visible
            pv_backend.set_orientation_axes_visible(visible)
            render_and_push()
        except Exception as exc:
            _set_color_status(f"Orientation axes update failed: {exc}", "error")

    @ctrl.add("pv_set_categorical_coloring")
    def pv_set_categorical_coloring(enabled=None):
        """Toggle categorical interpretation on the active scalar color map."""
        if pv_backend.display is None:
            return
        enabled = bool(state.categorical_coloring if enabled is None else enabled)
        try:
            state.categorical_coloring = enabled
            pv_backend.set_categorical_coloring(enabled)
            _refresh_color_state()
        except Exception as exc:
            _set_color_status(f"Categorical color update failed: {exc}", "error")

    @ctrl.add("pv_on_edit_field_choice")
    def pv_on_edit_field_choice(choice=None):
        """React to field selection changes (existing field or create new)."""
        if not edit_session.active:
            return

        raw_choice = choice if choice is not None else state.edit_field_choice
        choice = (raw_choice or "").strip()
        state.edit_field_choice = choice
        if choice == "__create_new__":
            state.edit_create_field_dialog = True
            return

        if ":" not in choice:
            return
        association, field_name = choice.split(":", 1)
        association = association.strip().lower()
        field_name = field_name.strip()
        if association not in {"cell", "point"} or not field_name:
            return

        state.edit_field_association = association
        edit_session.field_name = field_name
        _apply_geometry_options_for_association(association)
        sync_edit_session_state()

    @ctrl.add("pv_open_create_edit_field_dialog")
    def pv_open_create_edit_field_dialog():
        state.edit_create_field_dialog = True
        state.edit_field_choice = "__create_new__"

    @ctrl.add("pv_cancel_create_edit_field")
    def pv_cancel_create_edit_field():
        state.edit_create_field_dialog = False
        if state.edit_field_options:
            fallback = next(
                (
                    item.get("value")
                    for item in state.edit_field_options
                    if isinstance(item, dict)
                    and item.get("value")
                    and item.get("value") != "__create_new__"
                ),
                "",
            )
            state.edit_field_choice = fallback

    @ctrl.add("pv_create_edit_field")
    def pv_create_edit_field():
        """Create a new edit field and select it."""
        if not edit_session.active:
            return
        try:
            association = (state.edit_new_field_association or "cell").strip().lower()
            field_name = (state.edit_new_field_name or "").strip()
            default_value = (state.edit_new_field_default_value or "0").strip()
            if edit_session.has_field(field_name, association):
                state.edit_overwrite_field_name = field_name
                state.edit_overwrite_dialog = True
                notify(
                    state,
                    f"Field '{field_name}' already exists. Confirm overwrite to replace it.",
                    "warning",
                )
                sync_edit_session_state()
                return
            edit_session.create_field(
                field_name, association, default_value, overwrite=False
            )
            state.edit_field_choice = f"{association}:{field_name}"
            state.edit_create_field_dialog = False
            state.edit_new_field_name = ""
            state.edit_field_association = association
            _apply_geometry_options_for_association(association)
            sync_edit_session_state()
            notify(state, f"Created {association} field '{field_name}'.", "success")
        except Exception as exc:
            sync_edit_session_state()
            notify(state, f"Create field failed: {exc}", "error")

    @ctrl.add("pv_apply_edit_field")
    def pv_apply_edit_field():
        """Apply the current edit-session field operation."""
        if not edit_session.active:
            return

        try:
            _apply_edit_field()
        except Exception as exc:
            sync_edit_session_state()
            notify(state, f"Edit apply failed: {exc}", "error")

    @ctrl.add("pv_confirm_overwrite_edit_field")
    def pv_confirm_overwrite_edit_field():
        """Confirm overwrite for create-field dialog and create the new field."""
        if not edit_session.active:
            return

        try:
            association = (state.edit_new_field_association or "cell").strip().lower()
            field_name = (state.edit_new_field_name or "").strip()
            default_value = (state.edit_new_field_default_value or "0").strip()
            state.edit_overwrite_dialog = False
            state.edit_overwrite_field_name = ""
            edit_session.create_field(
                field_name, association, default_value, overwrite=True
            )
            state.edit_field_choice = f"{association}:{field_name}"
            state.edit_create_field_dialog = False
            state.edit_new_field_name = ""
            state.edit_field_association = association
            _apply_geometry_options_for_association(association)
            sync_edit_session_state()
            notify(state, f"Created {association} field '{field_name}'.", "success")
        except Exception as exc:
            sync_edit_session_state()
            notify(state, f"Create field failed: {exc}", "error")

    @ctrl.add("pv_cancel_overwrite_edit_field")
    def pv_cancel_overwrite_edit_field():
        """Dismiss overwrite confirmation without modifying the dataset."""
        state.edit_overwrite_dialog = False
        state.edit_overwrite_field_name = ""

    @ctrl.add("pv_edit_click_selection")
    def pv_edit_click_selection(event):
        """Capture single-click picking events for edit-session selection."""
        if not edit_session.active or not state.pick_mode:
            return

        timing = SelectionTiming("click")
        status = "ok"
        try:
            with timing.phase("summarize_event"):
                state.edit_selection_event = summarize_edit_event(event)
            with timing.phase("normalize_event"):
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
            with timing.phase("sync_mode"):
                mode = _sync_edit_mode_from_state()
            if coords is not None:
                selection_debug.log("click", x=coords[0], y=coords[1])
                with timing.phase("backend_pick"):
                    picked_ids = _pick_edit_ids_at_coords(mode, coords[0], coords[1])
                _append_backend_timing(timing)
            else:
                with timing.phase("payload_pick"):
                    picked_ids = [item for item in normalized if isinstance(item, int)]

            if not picked_ids:
                with timing.phase("empty_status"):
                    _set_empty_selection_status(mode, "Click")
                status = "empty"
                timing.update(mode=mode, picked_count=0)
                return

            _apply_selection_ids(
                picked_ids, "click selection", timing=timing, mode=mode
            )
        except Exception:
            status = "error"
            raise
        finally:
            timing.emit(state, status=status)

    @ctrl.add("pv_set_pick_mode")
    def pv_set_pick_mode():
        """Switch edit interaction to picking mode."""
        if not edit_session.active:
            return
        state.pick_mode = True
        sync_edit_session_state()
        call_view_update()

    @ctrl.add("pv_set_rotate_mode")
    def pv_set_rotate_mode():
        """Switch edit interaction to rotation/navigation mode."""
        if not edit_session.active:
            return
        state.pick_mode = False
        sync_edit_session_state()
        call_view_update()

    @ctrl.add("pv_edit_box_selection")
    def pv_edit_box_selection(event):
        """Capture native local-view box-selection events."""
        if not edit_session.active or not state.pick_mode:
            return

        timing = SelectionTiming("box")
        status = "ok"
        try:
            with timing.phase("summarize_event"):
                state.edit_selection_event = summarize_edit_event(event)
            selection = event.get("selection") if isinstance(event, dict) else None
            if not isinstance(selection, (list, tuple)) or len(selection) != 4:
                with timing.phase("invalid_status"):
                    notify(
                        state,
                        "Box selection did not include a usable rectangle.",
                        "warning",
                    )
                status = "invalid"
                return

            x0, x1, y0, y1 = selection
            with timing.phase("scale_rect"):
                x0, x1, y0, y1 = _scale_box_selection_to_view(event, x0, x1, y0, y1)
            with timing.phase("sync_mode"):
                mode = _sync_edit_mode_from_state()
            try:
                is_click_rect = (
                    abs(float(x1) - float(x0)) <= 1e-6
                    and abs(float(y1) - float(y0)) <= 1e-6
                )
            except (TypeError, ValueError):
                is_click_rect = False

            if is_click_rect:
                x = (float(x0) + float(x1)) * 0.5
                y = (float(y0) + float(y1)) * 0.5
                selection_debug.log("click", x=x, y=y)
                with timing.phase("backend_pick"):
                    picked_ids = _pick_edit_ids_at_coords(mode, x, y)
                _append_backend_timing(timing)
                if not picked_ids:
                    with timing.phase("empty_status"):
                        _set_empty_selection_status(mode, "Click")
                    status = "empty"
                    timing.update(mode=mode, picked_count=0)
                    return
                _apply_selection_ids(
                    picked_ids, "click selection", timing=timing, mode=mode
                )
                return

            selection_debug.log("box", x0=x0, y0=y0, x1=x1, y1=y1)
            with timing.phase("backend_pick"):
                picked_ids = _pick_edit_ids_in_rect(mode, x0, y0, x1, y1)
            _append_backend_timing(timing)
            if not picked_ids:
                with timing.phase("empty_status"):
                    _set_empty_selection_status(mode, "Box")
                status = "empty"
                timing.update(mode=mode, picked_count=0)
                return

            _apply_selection_ids(picked_ids, "box selection", timing=timing, mode=mode)
        except Exception:
            status = "error"
            raise
        finally:
            timing.emit(state, status=status)

    @ctrl.add("pv_clear_edit_preview")
    def pv_clear_edit_preview():
        """Clear the temporary selection preview state for ParaView edit mode."""

        _sync_edit_mode_from_state()
        edit_session.clear_selection()
        sync_edit_session_state()
        sync_paraview_edit_selection_overlay()
        state.edit_selection_event = ""
        notify(state, "Selection cleared.", "info")
        render_and_push()

    @ctrl.add("pv_select_all_edit_cells")
    def pv_select_all_edit_cells():
        """Select every editable cell in the current edit-session dataset."""
        if not edit_session.active:
            return

        mode = _sync_edit_mode_from_state()
        count = edit_session.select_all_cells()
        sync_edit_session_state()
        sync_paraview_edit_selection_overlay()
        state.selection_count = count
        if mode == "surface":
            entity_label = "surface element(s)"
        elif mode == "point":
            entity_label = "point(s)"
        else:
            entity_label = "cell(s)"
        notify(
            state,
            f"Selected all {count} {entity_label} in the edit-session dataset.",
            "success",
        )
        render_and_push()
