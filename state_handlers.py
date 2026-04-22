"""Shared Trame state-change registrations."""

import os
import traceback


def register_state_handlers(
    state,
    *,
    is_paraview_backend,
    load_file_with_paraview_backend,
    load_file_with_vtk_backend,
    apply_paraview_coloring,
    apply_vtk_coloring,
    apply_active_representation,
    pv_backend,
    update_paraview_ui_state,
    render_and_push,
    sync_edit_session_state,
    interaction_quality_presets,
):
    """Register backend-aware state callbacks shared across the app."""

    @state.change("selected_file")
    def on_file_change(selected_file, **kwargs):
        """Reload pipeline and reset coloring/representation when file changes."""
        if not selected_file or not os.path.exists(selected_file):
            return

        try:
            print(f"\nLoading file: {selected_file}")

            if state.edit_mode:
                state.edit_mode = False

            if is_paraview_backend():
                load_file_with_paraview_backend(selected_file)
            else:
                load_file_with_vtk_backend(selected_file)
        except Exception as exc:
            state.error_message = f"Error loading file: {exc}"
            print(f"Error: {exc}")
            traceback.print_exc()

    @state.change("selected_array")
    def on_array_change(selected_array, **kwargs):
        """Update coloring when the user picks a different array."""
        if is_paraview_backend():
            apply_paraview_coloring(selected_array)
            return

        apply_vtk_coloring(selected_array)

    @state.change("representation")
    def on_representation_change(representation, **kwargs):
        """Update actor representation when the user picks a different mode."""
        apply_active_representation(representation)

    @state.change("active_pipeline_item")
    def on_active_pipeline_item_change(active_pipeline_item, **kwargs):
        """Switch active ParaView node when the pipeline selection changes."""
        if not is_paraview_backend() or not active_pipeline_item:
            return
        if not pv_backend.set_active_node(active_pipeline_item):
            return

        update_paraview_ui_state()
        render_and_push()

    @state.change("interaction_quality")
    def on_interaction_quality_change(interaction_quality, **kwargs):
        """Update remote-render interaction quality preset."""
        preset = interaction_quality_presets.get(
            interaction_quality, interaction_quality_presets["high"]
        )
        state.interactive_quality = preset["interactive_quality"]
        state.interactive_ratio = preset["interactive_ratio"]

    @state.change("pick_mode")
    def on_pick_mode_change(pick_mode, **kwargs):
        """Enable or disable edit-view picking modes for the ParaView path."""
        if not is_paraview_backend():
            return

        if pv_backend is not None:
            pv_backend.set_interactor_rotation(not pick_mode)

        sync_edit_session_state()

    @state.change("edit_mode")
    def on_edit_mode_change(edit_mode, **kwargs):
        """Ensure rotation is restored when exiting edit mode."""
        if not is_paraview_backend() or edit_mode:
            return

        if pv_backend is not None:
            pv_backend.set_interactor_rotation(True)

        sync_edit_session_state()
