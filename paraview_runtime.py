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
        # Keep backend-originated state writes (e.g. during load) in sync with Trame state.
        self.pv_backend.state = state
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
        available_fields = []
        fields_getter = getattr(self.edit_session, "available_fields", None)
        if callable(fields_getter):
            available_fields = list(fields_getter() or [])
        create_option = {"text": "Create new...", "value": "__create_new__"}
        self.state.edit_field_options = available_fields + [create_option]
        available_values = {
            item.get("value")
            for item in self.state.edit_field_options
            if isinstance(item, dict) and item.get("value")
        }
        selected_choice = ""
        if self.edit_session.field_name:
            association = "cell"
            infer = getattr(self.edit_session, "infer_field_association", None)
            if callable(infer):
                association = infer(self.edit_session.field_name) or association
            selected_choice = f"{association}:{self.edit_session.field_name}"
        elif (
            isinstance(getattr(self.state, "edit_field_choice", ""), str)
            and self.state.edit_field_choice in available_values
            and self.state.edit_field_choice != "__create_new__"
        ):
            selected_choice = self.state.edit_field_choice
        self.state.edit_field_choice = selected_choice
        self.state.edit_field_association = (
            "point"
            if isinstance(selected_choice, str) and selected_choice.startswith("point:")
            else "cell"
        )
        if self.state.edit_field_association == "point":
            getter = getattr(self.edit_session, "available_point_variables", None)
            self.state.edit_available_variables = getter() if callable(getter) else []
        else:
            self.state.edit_available_variables = self.edit_session.available_cell_variables()
        if self.state.edit_field_association == "point":
            self.state.edit_geometry_mode_options = list(
                getattr(
                    self.state,
                    "edit_point_geometry_mode_options",
                    [{"text": "Point", "value": "point"}],
                )
            )
            self.state.edit_geometry_mode = "point"
            self.edit_session.geometry_mode = "point"
        else:
            self.state.edit_geometry_mode_options = list(
                getattr(
                    self.state,
                    "edit_cell_geometry_mode_options",
                    [
                        {"text": "Volume", "value": "volume"},
                        {"text": "Surface", "value": "surface"},
                    ],
                )
            )
            if self.state.edit_geometry_mode not in {"volume", "surface"}:
                self.state.edit_geometry_mode = "volume"
                self.edit_session.geometry_mode = "volume"
        self.state.selection_count = self.edit_session.selected_count()
        self.state.edit_enable_picking = bool(
            self.edit_session.active and self.state.pick_mode
        )
        self.state.edit_picking_modes = (
            ["select"]
            if self.edit_session.active and self.state.pick_mode
            else []
        )
        self.state.edit_interactor_events = ["EndAnimation"]
        if self.edit_session.active and self.state.pick_mode:
            # Disable all grid manipulation when picking is active as requested by user.
            self.state.edit_interactor_settings = []
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
            coords = self._resolve_event_view_coordinates(event)
            if coords is not None:
                return [("coords", coords[0], coords[1])]

            if isinstance(event.get("compositeID"), int):
                return [event["compositeID"]]
            if isinstance(event.get("selection"), list):
                result = []
                for item in event["selection"]:
                    if isinstance(item, dict) and isinstance(item.get("compositeID"), int):
                        result.append(item["compositeID"])
                if result:
                    return result

            return []

        if isinstance(event, list):
            result = []
            for item in event:
                if isinstance(item, dict) and isinstance(item.get("compositeID"), int):
                    result.append(item["compositeID"])
            return result

        return []

    def _resolve_event_view_coordinates(self, event):
        """Map browser-side pointer coordinates into ParaView view coordinates."""
        if not isinstance(event, dict):
            return None

        x = y = None
        pos = event.get("position")
        if isinstance(pos, dict) and "x" in pos and "y" in pos:
            x = pos["x"]
            y = pos["y"]
        elif "x" in event and "y" in event:
            x = event["x"]
            y = event["y"]
        else:
            return None

        try:
            x = float(x)
            y = float(y)
        except (TypeError, ValueError):
            return None

        size_width, size_height = self._extract_size_pair(event.get("size"))
        scale_x, scale_y = self._extract_scale_pair(event.get("scale"))
        view_width, view_height = self._view_size()

        if scale_x is not None and scale_y is not None:
            x *= scale_x
            y *= scale_y
        elif (
            size_width is not None
            and size_height is not None
            and view_width is not None
            and view_height is not None
            and size_width > 0
            and size_height > 0
        ):
            x *= view_width / size_width
            y *= view_height / size_height

        if view_width is not None:
            x = min(max(x, 0.0), max(view_width - 1.0, 0.0))
        if view_height is not None:
            y = min(max(y, 0.0), max(view_height - 1.0, 0.0))

        return int(round(x)), int(round(y))

    def _view_size(self):
        """Return the current ParaView view size when available."""
        view = getattr(self.pv_backend, "view", None)
        if view is None or not hasattr(view, "ViewSize"):
            return None, None

        try:
            width, height = view.ViewSize
            return float(width), float(height)
        except (TypeError, ValueError):
            return None, None

    @staticmethod
    def _extract_size_pair(size):
        """Extract width/height from an event size payload."""
        if isinstance(size, dict):
            for width_key, height_key in (
                ("width", "height"),
                ("w", "h"),
                ("x", "y"),
            ):
                if width_key in size and height_key in size:
                    try:
                        return float(size[width_key]), float(size[height_key])
                    except (TypeError, ValueError):
                        return None, None
        if isinstance(size, (list, tuple)) and len(size) >= 2:
            try:
                return float(size[0]), float(size[1])
            except (TypeError, ValueError):
                return None, None
        return None, None

    @staticmethod
    def _extract_scale_pair(scale):
        """Extract x/y scale factors from an event scale payload."""
        if isinstance(scale, dict):
            for x_key, y_key in (
                ("x", "y"),
                ("width", "height"),
                ("sx", "sy"),
            ):
                if x_key in scale and y_key in scale:
                    try:
                        return float(scale[x_key]), float(scale[y_key])
                    except (TypeError, ValueError):
                        return None, None
        try:
            uniform = float(scale)
        except (TypeError, ValueError):
            uniform = None
        if uniform is not None:
            return uniform, uniform
        return None, None

    def sync_edit_selection_overlay(self):
        """Update the transient selection highlight for the active edit session."""
        self.pv_backend.clear_active_selection()
        if not self.edit_session.active:
            self.pv_backend.clear_edit_selection_overlay()
            self.call_view_update()
            return

        build_dataset = getattr(self.edit_session, "build_selected_dataset", None)
        if callable(build_dataset):
            dataset = build_dataset()
        else:
            dataset = self.edit_session.build_selected_volume_dataset()
        if dataset is None or dataset.GetNumberOfCells() == 0:
            self.pv_backend.clear_edit_selection_overlay()
            self.call_view_update()
            return

        self.pv_backend.update_edit_selection_overlay(dataset)
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
        ui_state = self.pv_backend.get_ui_state() or {}
        ui_state = {
            "pipeline_items": [],
            "active_pipeline_item": None,
            "active_source_label": "",
            "active_source_type": "",
            "active_source_kind": "Reader Type",
            "active_parent_label": "",
            "source_path": "",
            "point_arrays": [],
            "cell_arrays": [],
            "data_stats": [],
            "source_properties": [],
            "display_properties": [],
            "show_calculator_help": False,
            "calculator_attribute_type": "",
            "calculator_input_variables": [],
            "calculator_coordinate_variables": ["coordsX", "coordsY", "coordsZ"],
            "active_visibility": True,
            "selected_array": ARRAY_SOLID,
            "representation": "Surface with Edges",
            "color_controls_enabled": False,
            "color_range_min": "",
            "color_range_max": "",
            "color_bar_visible": False,
            "orientation_axes_visible": True,
            "categorical_coloring": False,
            "time_values": [],
            "current_time": 0.0,
            "time_index": 0,
            "total_timesteps": 0,
            "is_time_dependent": False,
            **ui_state,
        }
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
        self.state.color_controls_enabled = ui_state["color_controls_enabled"]
        self.state.color_range_min = ui_state["color_range_min"]
        self.state.color_range_max = ui_state["color_range_max"]
        self.state.color_bar_visible = ui_state["color_bar_visible"]
        self.state.orientation_axes_visible = ui_state["orientation_axes_visible"]
        self.state.categorical_coloring = ui_state["categorical_coloring"]
        self.state.time_values = ui_state["time_values"]
        self.state.current_time = ui_state["current_time"]
        self.state.time_index = ui_state["time_index"]
        self.state.total_timesteps = ui_state["total_timesteps"]
        self.state.is_time_dependent = ui_state["is_time_dependent"]
        if not self.state.is_time_dependent:
            self.state.time_playing = False
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
