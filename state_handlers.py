"""Shared Trame state-change registrations."""

from __future__ import annotations

import os
import traceback
from typing import TYPE_CHECKING

from diagnostics import debug_log, devtools_enabled
from notifications import notify

if TYPE_CHECKING:
    from paraview_runtime import ParaViewRuntime


def register_state_handlers(
    state,
    *,
    paraview_runtime: ParaViewRuntime,
    edit_session,
    interaction_quality_presets,
):
    """Register state callbacks for the ParaView backend."""

    @state.change("selected_file")
    def on_file_change(selected_file, **kwargs):
        """Reload pipeline and reset coloring/representation when file changes."""
        if not selected_file or not os.path.exists(selected_file):
            return

        try:
            debug_log(f"\nLoading file: {selected_file}")
            paraview_runtime.load_file(selected_file)
        except Exception as exc:
            notify(state, f"Error loading file: {exc}", "error")
            debug_log(f"Error: {exc}")
            if devtools_enabled():
                traceback.print_exc()

    @state.change("selected_array")
    def on_array_change(selected_array, **kwargs):
        """Update coloring when the user picks a different array."""
        if selected_array and paraview_runtime.pv_backend.source is not None:
            paraview_runtime.pv_backend.apply_coloring(selected_array)
            paraview_runtime.update_color_state()
            paraview_runtime.call_view_update()

    @state.change("representation")
    def on_representation_change(representation, **kwargs):
        """Update actor representation when the user picks a different mode."""
        if paraview_runtime.pv_backend.display is None:
            return
        paraview_runtime.pv_backend.apply_representation(representation)
        paraview_runtime.update_ui_state()
        paraview_runtime.call_view_update()

    @state.change("active_pipeline_item")
    def on_active_pipeline_item_change(active_pipeline_item, **kwargs):
        """Switch active ParaView node when the pipeline selection changes."""
        if not active_pipeline_item:
            return
        if edit_session.active:
            if active_pipeline_item == paraview_runtime.pv_backend.active_node_id:
                # Programmatic sync (e.g. update_ui_state updating to the edit node) —
                # no user action, no warning needed.
                return
            notify(
                state, "Cannot switch pipeline node during an edit session.", "warning"
            )
            state.active_pipeline_item = paraview_runtime.pv_backend.active_node_id
            return
        if not paraview_runtime.pv_backend.set_active_node(active_pipeline_item):
            return

        paraview_runtime.update_ui_state()
        paraview_runtime.render_and_push()

    @state.change("interaction_quality")
    def on_interaction_quality_change(interaction_quality, **kwargs):
        """Update remote-render interaction quality preset."""
        preset = interaction_quality_presets.get(
            interaction_quality, interaction_quality_presets["high"]
        )
        state.interactive_quality = preset["interactive_quality"]
        state.interactive_ratio = preset["interactive_ratio"]

    @state.change("pick_mode", "edit_session_active")
    def on_interaction_mode_change(pick_mode, edit_session_active, **kwargs):
        """Update ParaView interactor rotation and cursor style based on pick mode."""
        # Only disable rotation if an edit session is active and we are in pick mode.
        # In non-edit mode, rotation should always be enabled.
        rotation_enabled = not (edit_session_active and pick_mode)
        paraview_runtime.pv_backend.set_interactor_rotation(rotation_enabled)

        # Update cursor style: crosshair only when picking in an active edit session.
        state.edit_view_style = (
            "width: 100%; height: 100%; cursor: crosshair; outline: none;"
            if edit_session_active and pick_mode
            else "width: 100%; height: 100%; cursor: default; outline: none;"
        )

        paraview_runtime.sync_edit_session_state()

    @state.change("remote_search_term", "available_files")
    def on_remote_search_change(remote_search_term, available_files, **kwargs):
        """Filter the available files based on the search term."""
        if not remote_search_term:
            state.filtered_available_files = available_files
            return

        term = remote_search_term.lower()
        filtered = []

        # Group items by their preceding header
        groups = []  # list of (header_item_or_None, list_of_data_items)
        current_header = None
        current_items = []

        for item in available_files:
            if item.get("header"):
                groups.append((current_header, current_items))
                current_header = item
                current_items = []
            elif item.get("divider"):
                continue
            elif item.get("value"):
                text_match = term in item.get("text", "").lower()
                path_match = term in item.get("path", "").lower()
                if text_match or path_match:
                    current_items.append(item)
        groups.append((current_header, current_items))

        # Reconstruct filtered list
        for header, items in groups:
            if items:
                if filtered:
                    filtered.append({"divider": True})
                if header:
                    filtered.append(header)
                filtered.extend(items)

        state.filtered_available_files = filtered

    @state.change("state_browser_search_term", "state_files")
    def on_state_browser_search_change(
        state_browser_search_term, state_files, **kwargs
    ):
        """Filter the available state files based on the search term."""
        if not state_browser_search_term:
            state.filtered_state_files = list(state_files or [])
            return

        term = state_browser_search_term.lower()
        state.filtered_state_files = [
            item for item in (state_files or []) if term in item.get("text", "").lower()
        ]
