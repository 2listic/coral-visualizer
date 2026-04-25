"""VTK-specific Trame state and controller registrations."""

import os
import traceback

from constants import BOUNDARY, MATERIAL_ID_ARRAY, VOLUME
from diagnostics import debug_log, devtools_enabled


def register_vtk_handlers(
    state,
    ctrl,
    *,
    is_vtk_backend,
    viz_getter,
    edit_state,
    pick_interactor,
    data_directory,
    apply_edit_coloring,
    render_and_push,
    update_selection_actor,
    assign_id_to_selection,
    save_as_vtu,
    refresh_available_files,
    update_scalar_bars,
    active_lut_getter,
    apply_vtk_coloring,
    apply_vtk_representation_to_scene,
):
    """Register VTK-only state callbacks and controller callbacks."""

    @state.change("edit_mode")
    def on_edit_mode_change(edit_mode, **kwargs):
        """Toggle between view mode and boundary edit mode."""
        if not is_vtk_backend():
            if edit_mode:
                state.edit_mode = False
                state.error_message = (
                    "Edit mode is not available on the ParaView backend yet."
                )
            return

        if edit_state.merged_bnd_actor is None:
            if edit_mode:
                state.edit_mode = False
                state.error_message = "No boundary cells available for editing"
            return

        viz = viz_getter()

        if edit_mode:
            state.edit_target = BOUNDARY
            state.pick_mode = True
            if viz and viz.bnd_actor:
                viz.bnd_actor.SetVisibility(0)
            apply_edit_coloring(BOUNDARY)
            pick_interactor.install()
        else:
            pick_interactor.remove()
            edit_state.merged_bnd_actor.SetVisibility(0)
            edit_state.bnd_selection_actor.SetVisibility(0)
            edit_state.bnd_selection_set.clear()
            if edit_state.vol_selection_actor:
                edit_state.vol_selection_actor.SetVisibility(0)
            edit_state.vol_selection_set.clear()
            state.selection_count = 0
            if viz and viz.bnd_actor:
                viz.bnd_actor.SetVisibility(1)
            update_scalar_bars(active_lut_getter(), state.selected_array)
            apply_vtk_coloring(state.selected_array)
            apply_vtk_representation_to_scene(state.representation)

        render_and_push()

    @state.change("edit_target")
    def on_edit_target_change(edit_target, **kwargs):
        """Switch between boundary and volume edit targets, clearing the selection."""
        if not is_vtk_backend():
            return

        if not state.edit_mode:
            return

        edit_state.bnd_selection_set.clear()
        edit_state.vol_selection_set.clear()
        update_selection_actor(
            edit_state.bnd_selection_set,
            edit_state.merged_bnd_dataset,
            edit_state.bnd_selection_actor,
            edit_state.bnd_selection_mapper,
        )
        if edit_state.vol_dataset is not None:
            update_selection_actor(
                edit_state.vol_selection_set,
                edit_state.vol_dataset,
                edit_state.vol_selection_actor,
                edit_state.vol_selection_mapper,
            )
        state.selection_count = 0

        apply_edit_coloring(edit_target)
        render_and_push()

    @ctrl.add("clear_selection")
    def clear_selection():
        """Clear all selected cells (boundary or volume depending on edit_target)."""
        if not is_vtk_backend():
            return

        if state.edit_target == VOLUME:
            edit_state.vol_selection_set.clear()
            if edit_state.vol_dataset is not None:
                update_selection_actor(
                    edit_state.vol_selection_set,
                    edit_state.vol_dataset,
                    edit_state.vol_selection_actor,
                    edit_state.vol_selection_mapper,
                )
        else:
            edit_state.bnd_selection_set.clear()
            update_selection_actor(
                edit_state.bnd_selection_set,
                edit_state.merged_bnd_dataset,
                edit_state.bnd_selection_actor,
                edit_state.bnd_selection_mapper,
            )
        state.selection_count = 0
        render_and_push()

    @ctrl.add("select_all")
    def select_all():
        """Select all cells (boundary or volume depending on edit_target)."""
        if not is_vtk_backend():
            return

        if state.edit_target == VOLUME:
            if edit_state.vol_dataset is not None:
                n = edit_state.vol_dataset.GetNumberOfCells()
                edit_state.vol_selection_set = set(range(n))
                update_selection_actor(
                    edit_state.vol_selection_set,
                    edit_state.vol_dataset,
                    edit_state.vol_selection_actor,
                    edit_state.vol_selection_mapper,
                )
                state.selection_count = n
                render_and_push()
        else:
            if edit_state.merged_bnd_dataset is not None:
                n = edit_state.merged_bnd_dataset.GetNumberOfCells()
                edit_state.bnd_selection_set = set(range(n))
                update_selection_actor(
                    edit_state.bnd_selection_set,
                    edit_state.merged_bnd_dataset,
                    edit_state.bnd_selection_actor,
                    edit_state.bnd_selection_mapper,
                )
                state.selection_count = n
                render_and_push()

    @ctrl.add("assign_id")
    def assign_id():
        """Assign the chosen ID value to all selected cells (boundary or volume)."""
        if not is_vtk_backend():
            state.error_message = "Editing is only available on the VTK backend."
            return

        try:
            value = int(state.assign_id_value)
        except (ValueError, TypeError):
            state.error_message = "Invalid ID value — must be an integer"
            return

        if state.edit_target == VOLUME:
            if not edit_state.vol_selection_set or edit_state.vol_dataset is None:
                return

            arr = edit_state.vol_dataset.GetCellData().GetArray(MATERIAL_ID_ARRAY)
            if arr is None:
                return
            for cell_idx in edit_state.vol_selection_set:
                arr.SetValue(cell_idx, value)
            edit_state.vol_dataset.Modified()

            apply_edit_coloring(VOLUME)

            edit_state.vol_selection_set.clear()
            update_selection_actor(
                edit_state.vol_selection_set,
                edit_state.vol_dataset,
                edit_state.vol_selection_actor,
                edit_state.vol_selection_mapper,
            )
        else:
            if (
                not edit_state.bnd_selection_set
                or edit_state.merged_bnd_dataset is None
            ):
                return

            assign_id_to_selection(edit_state, MATERIAL_ID_ARRAY, value)
            apply_edit_coloring(BOUNDARY)

            edit_state.bnd_selection_set.clear()
            update_selection_actor(
                edit_state.bnd_selection_set,
                edit_state.merged_bnd_dataset,
                edit_state.bnd_selection_actor,
                edit_state.bnd_selection_mapper,
            )

        state.selection_count = 0
        render_and_push()

    @ctrl.add("save_vtu")
    def save_vtu_controller():
        """Save the modified mesh as .vtu."""
        if not is_vtk_backend():
            state.save_status = "Save is not available on the ParaView backend yet"
            state.save_status_type = "error"
            return

        if edit_state.full_dataset is None or edit_state.merged_bnd_dataset is None:
            state.save_status = "No data to save"
            state.save_status_type = "error"
            return

        try:
            filename = state.save_filename.strip()
            if not filename:
                filename = "output"
            if not filename.endswith(".vtu"):
                filename += ".vtu"
            os.makedirs(data_directory, exist_ok=True)
            output_path = os.path.join(data_directory, filename)

            save_as_vtu(edit_state, output_path)

            state.save_status = f"Saved to {os.path.relpath(output_path)}"
            state.save_status_type = "success"

            refresh_available_files()
            debug_log(f"  Saved to {output_path}")
        except Exception as exc:
            state.save_status = f"Error: {str(exc)}"
            state.save_status_type = "error"
            debug_log(f"Save error: {exc}")
            if devtools_enabled():
                traceback.print_exc()
