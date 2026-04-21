"""ParaView backend orchestration helpers."""

import json

from constants import ARRAY_SOLID


class ParaViewRuntime:
    """Own ParaView-side UI synchronization and runtime plumbing."""

    def __init__(
        self,
        *,
        state,
        pv_backend,
        edit_session,
        output_window,
        call_view_update,
    ):
        self.state = state
        self.pv_backend = pv_backend
        self.edit_session = edit_session
        self.output_window = output_window
        self.call_view_update = call_view_update
        self.output_offset = 0

    def render_and_push(self):
        """Render the active ParaView view and push the update to the client."""
        self.pv_backend.render()
        self.call_view_update()

    def refresh_runtime_message(self, clear=False):
        """Drain recent ParaView/VTK runtime output into a user-facing alert."""
        if self.output_window is None:
            return

        output = self.output_window.GetOutput() or ""
        if clear:
            self.state.pv_runtime_message = ""
            self.state.pv_runtime_type = "error"
            self.output_offset = len(output)
            return

        if len(output) <= self.output_offset:
            return

        new_output = output[self.output_offset :]
        self.output_offset = len(output)
        lines = [
            line.strip()
            for line in new_output.splitlines()
            if line.strip() and "Saving settings file" not in line
        ]
        if not lines:
            return

        self.state.pv_runtime_message = "\n".join(lines[-4:])
        self.state.pv_runtime_type = (
            "error"
            if any(("ERROR:" in line or "Err:" in line) for line in lines)
            else "warning"
        )

    def sync_edit_session_state(self):
        """Synchronize Trame state from the current edit session."""
        self.state.edit_session_active = self.edit_session.active
        self.state.edit_session_label = self.edit_session.source_label or ""
        self.state.edit_geometry_mode = self.edit_session.geometry_mode
        self.state.edit_field_name = self.edit_session.field_name
        self.state.edit_expression = self.edit_session.expression
        self.state.edit_default_value = self.edit_session.default_value
        self.state.edit_available_variables = self.edit_session.available_cell_variables()
        self.state.selection_count = self.edit_session.selected_count()
        self.state.edit_picking_modes = (
            ["click", "mesh", "box"]
            if self.edit_session.active and self.state.pick_mode
            else []
        )
        self.state.edit_interactor_events = ["EndAnimation"]
        if self.edit_session.active and self.state.pick_mode:
            self.state.edit_interactor_settings = [
                {"button": 1, "action": "Pan"},
                {"button": 2, "action": "Pan"},
                {"button": 3, "action": "Zoom", "scrollEnabled": True},
            ]
            return

        self.state.edit_interactor_settings = [
            {"button": 1, "action": "Rotate"},
            {"button": 2, "action": "Pan"},
            {"button": 3, "action": "Zoom", "scrollEnabled": True},
        ]

    def normalize_edit_selection_ids(self, event):
        """Extract picked cell IDs or screen coordinates from picking payloads."""
        if event is None:
            return []

        if isinstance(event, dict):
            if isinstance(event.get("compositeID"), int):
                return [event["compositeID"]]
            if isinstance(event.get("selection"), list):
                result = []
                for item in event["selection"]:
                    if isinstance(item, dict) and isinstance(item.get("compositeID"), int):
                        result.append(item["compositeID"])
                if result:
                    return result

            pos = event.get("position")
            if isinstance(pos, dict) and "x" in pos and "y" in pos:
                return [("coords", pos["x"], pos["y"])]
            if "x" in event and "y" in event:
                return [("coords", event["x"], event["y"])]
            return []

        if isinstance(event, list):
            result = []
            for item in event:
                if isinstance(item, dict) and isinstance(item.get("compositeID"), int):
                    result.append(item["compositeID"])
            return result

        return []

    def sync_edit_selection_overlay(self):
        """Update the transient selection highlight for the active edit session."""
        if not self.edit_session.active:
            self.pv_backend.clear_active_selection()
            self.pv_backend.clear_edit_selection_overlay()
            self.call_view_update()
            return

        overlay_dataset = self.edit_session.build_selected_volume_dataset()
        if overlay_dataset is None:
            self.pv_backend.clear_active_selection()
            self.pv_backend.clear_edit_selection_overlay()
            self.call_view_update()
            return

        self.pv_backend.update_edit_selection_overlay(overlay_dataset)
        self.call_view_update()

    def summarize_edit_event(self, event):
        """Return a compact, UI-friendly summary of a picking/selection event."""
        if event is None:
            return "No event payload"

        if isinstance(event, dict):
            summary = {}
            for key in (
                "mode",
                "remoteId",
                "representationId",
                "view",
                "x",
                "y",
                "z",
                "compositeID",
                "position",
                "pany",
                "panx",
            ):
                if key in event:
                    summary[key] = event[key]

            normalized_ids = self.normalize_edit_selection_ids(event)
            if normalized_ids:
                if (
                    isinstance(normalized_ids[0], tuple)
                    and normalized_ids[0][0] == "coords"
                ):
                    summary["resolved_coords"] = normalized_ids[0][1:]
                else:
                    summary["selection_count"] = len(normalized_ids)
                    summary["sample_ids"] = normalized_ids[:8]

            summary["all_keys"] = list(event.keys())
            return json.dumps(summary, indent=2, default=str)

        if isinstance(event, (list, tuple)):
            return json.dumps(event, indent=2, default=str)

        return str(event)

    def update_ui_state(self):
        """Synchronize Trame state with the active ParaView source metadata."""
        ui_state = self.pv_backend.get_ui_state()
        self.state.pipeline_items = ui_state["pipeline_items"]
        self.state.active_pipeline_item = ui_state["active_pipeline_item"]
        self.state.active_source_label = ui_state["active_source_label"]
        self.state.active_source_type = ui_state["active_source_type"]
        self.state.active_source_kind = ui_state["active_source_kind"]
        self.state.active_parent_label = ui_state["active_parent_label"]
        self.state.source_path = ui_state["source_path"]
        self.state.point_arrays = ui_state["point_arrays"]
        self.state.cell_arrays = ui_state["cell_arrays"]
        self.state.data_stats = ui_state["data_stats"]
        self.state.source_properties = ui_state["source_properties"]
        self.state.display_properties = ui_state["display_properties"]
        self.state.show_calculator_help = ui_state["show_calculator_help"]
        self.state.calculator_attribute_type = ui_state["calculator_attribute_type"]
        self.state.calculator_input_variables = ui_state["calculator_input_variables"]
        self.state.calculator_coordinate_variables = ui_state[
            "calculator_coordinate_variables"
        ]
        self.state.source_default_property_count = len(
            [item for item in self.state.source_properties if item["visibility"] == "default"]
        )
        self.state.source_advanced_property_count = len(
            [item for item in self.state.source_properties if item["visibility"] == "advanced"]
        )
        self.state.display_default_property_count = len(
            [item for item in self.state.display_properties if item["visibility"] == "default"]
        )
        self.state.display_advanced_property_count = len(
            [item for item in self.state.display_properties if item["visibility"] == "advanced"]
        )
        self.state.active_visibility = ui_state["active_visibility"]
        self.state.available_arrays = ui_state["point_arrays"] + ui_state["cell_arrays"]
        self.state.available_arrays.insert(0, {"text": "Solid Color", "value": ARRAY_SOLID})
        self.state.selected_array = ui_state["selected_array"]
        self.state.representation = ui_state["representation"]
        self.state.pv_properties_dirty = False
        if not self.state.save_filename or self.state.save_filename == "output":
            self.state.save_filename = (
                self.edit_session.default_output_filename()
                if self.edit_session.active
                else self.pv_backend.default_output_filename()
            )
        self.state.save_target_label = (
            f"Edited dataset: {self.edit_session.source_label}"
            if self.edit_session.active
            else f"Active pipeline result: {self.state.active_source_label}"
            if self.state.active_source_label
            else "Active pipeline result"
        )
        try:
            self.pv_backend.export_active_dataset_for_editing()
            self.state.can_edit_active = True
        except Exception:
            self.state.can_edit_active = False
        self.sync_edit_session_state()

    def apply_representation(self, representation):
        """Apply representation to the active ParaView pipeline item."""
        if self.pv_backend.display is None:
            return
        self.pv_backend.apply_representation(representation)
        self.update_ui_state()
        self.call_view_update()

    def apply_coloring(self, selected_array):
        """Apply coloring to the active ParaView pipeline item."""
        if selected_array and self.pv_backend.source is not None:
            self.pv_backend.apply_coloring(selected_array)
            self.update_ui_state()
            self.call_view_update()

    def load_file(self, selected_file):
        """Load a dataset through the ParaView backend and refresh derived state."""
        self.refresh_runtime_message(clear=True)
        arrays, default_array = self.pv_backend.load_file(selected_file)
        self.pv_backend.apply_representation(self.state.representation)
        self.pv_backend.apply_coloring(default_array)
        self.refresh_runtime_message()
        self.update_ui_state()
        self.state.has_boundary = False
        self.state.error_message = ""
        self.state.selection_count = 0
        self.state.save_status = ""
        self.render_and_push()
