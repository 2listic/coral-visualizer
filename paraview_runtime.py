"""ParaView backend orchestration helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import paraview_event_utils

if TYPE_CHECKING:
    from vtkmodules.vtkCommonCore import vtkStringOutputWindow
    from edit_session import EditSession
    from paraview_backend import ParaViewBackend

from constants import ARRAY_SOLID

DEFAULT_REPRESENTATION = "Surface with Edges"


class ParaViewRuntime:
    """Own ParaView-side UI synchronization and runtime plumbing."""

    def __init__(
        self,
        *,
        state,
        pv_backend: ParaViewBackend,
        edit_session: EditSession,
        output_window: vtkStringOutputWindow | None,
        call_view_update: Callable,
    ):
        self.state = state
        self.pv_backend: ParaViewBackend = pv_backend
        # Keep backend-originated state writes (e.g. during load) in sync with Trame state.
        self.pv_backend.state = state
        self.edit_session: EditSession = edit_session
        self.output_window: vtkStringOutputWindow | None = output_window
        self.call_view_update: Callable = call_view_update
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
            self.state.edit_available_variables = (
                self.edit_session.available_cell_variables()
            )
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
            ["select"] if self.edit_session.active and self.state.pick_mode else []
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

    def normalize_edit_selection_ids(self, event) -> list:
        """Extract picked cell IDs or screen coordinates from picking payloads."""
        return paraview_event_utils.normalize_edit_selection_ids(
            event, getattr(self.pv_backend, "view", None)
        )

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

    def summarize_edit_event(self, event) -> str:
        """Return a compact, UI-friendly summary of a picking/selection event."""
        return paraview_event_utils.summarize_edit_event(
            event, getattr(self.pv_backend, "view", None)
        )

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
            "show_cells": True,
            "show_faces": True,
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
            [
                item
                for item in self.state.source_properties
                if item["visibility"] == "default"
            ]
        )
        self.state.source_advanced_property_count = len(
            [
                item
                for item in self.state.source_properties
                if item["visibility"] == "advanced"
            ]
        )
        self.state.display_default_property_count = len(
            [
                item
                for item in self.state.display_properties
                if item["visibility"] == "default"
            ]
        )
        self.state.display_advanced_property_count = len(
            [
                item
                for item in self.state.display_properties
                if item["visibility"] == "advanced"
            ]
        )
        self.state.active_visibility = ui_state["active_visibility"]
        self.state.available_arrays = ui_state["point_arrays"] + ui_state["cell_arrays"]
        self.state.available_arrays.insert(
            0, {"text": "Solid Color", "value": ARRAY_SOLID}
        )
        self.state.selected_array = ui_state["selected_array"]
        self.state.representation = ui_state["representation"]
        self.state.show_cells = ui_state["show_cells"]
        self.state.show_faces = ui_state["show_faces"]
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
            else (
                f"Active pipeline result: {self.state.active_source_label}"
                if self.state.active_source_label
                else "Active pipeline result"
            )
        )
        try:
            self.pv_backend.export_active_dataset_for_editing()
            self.state.can_edit_active = True
        except Exception:
            self.state.can_edit_active = False
        self.sync_edit_session_state()

    def load_file(self, selected_file):
        """Load a dataset through the ParaView backend and refresh derived state."""
        self.refresh_runtime_message(clear=True)
        self.pv_backend.load_file(selected_file)
        self.state.selected_array = ARRAY_SOLID
        self.state.representation = DEFAULT_REPRESENTATION
        self.pv_backend.apply_representation(DEFAULT_REPRESENTATION)
        self.pv_backend.apply_coloring(ARRAY_SOLID)
        reset_view = getattr(self.pv_backend, "reset_view", None)
        if callable(reset_view):
            reset_view()
        self.refresh_runtime_message()
        self.update_ui_state()
        self.state.has_boundary = False
        self.state.error_message = ""
        self.state.selection_count = 0
        self.state.save_status = ""
        self.render_and_push()
