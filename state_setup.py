"""Helpers for initializing Trame state."""

import os

from constants import ARRAY_SOLID, BOUNDARY, INTERACTION_QUALITY_PRESETS


DEFAULT_REPRESENTATION = "Surface with Edges"


def resolve_initial_file(requested_file, available_files):
    """Pick the initial dataset path to expose in state."""
    if requested_file and os.path.exists(requested_file):
        return requested_file
    if available_files:
        return available_files[0]["value"]
    return None


def initialize_state(
    state,
    *,
    available_files,
    initial_file,
    backend,
    backend_message,
    pv_backend,
):
    """Populate the Trame state object with the app defaults."""
    initial_arrays = [{"text": "Solid Color", "value": ARRAY_SOLID}]
    filter_catalog = (
        pv_backend.get_available_filters()
        if pv_backend
        else {"supported": [], "experimental": []}
    )

    state.available_files = available_files
    state.selected_file = initial_file
    state.error_message = ""
    state.available_arrays = initial_arrays
    state.selected_array = ARRAY_SOLID
    state.representation = DEFAULT_REPRESENTATION
    state.has_boundary = False
    state.backend = backend
    state.backend_message = backend_message
    state.pipeline_items = []
    state.active_pipeline_item = None
    state.active_source_label = ""
    state.active_source_type = ""
    state.active_source_kind = "Reader Type"
    state.active_parent_label = ""
    state.source_path = ""
    state.point_arrays = []
    state.cell_arrays = []
    state.data_stats = []
    state.source_properties = []
    state.display_properties = []
    state.source_default_property_count = 0
    state.source_advanced_property_count = 0
    state.display_default_property_count = 0
    state.display_advanced_property_count = 0
    state.inspector_tab = 0
    state.pv_properties_dirty = False
    state.active_visibility = True
    state.upload_status = ""
    state.upload_status_type = "info"
    state.remote_browser_dialog = False
    state.filter_supported_options = filter_catalog["supported"]
    state.filter_experimental_options = filter_catalog["experimental"]
    state.show_experimental_filters = bool(state.filter_experimental_options)
    state.filter_menu = False
    state.filter_search = ""
    state.interaction_quality_options = [
        {"text": "Fast", "value": "fast"},
        {"text": "Balanced", "value": "balanced"},
        {"text": "High", "value": "high"},
    ]
    state.interaction_quality = "high"
    state.interactive_quality = INTERACTION_QUALITY_PRESETS["high"]["interactive_quality"]
    state.interactive_ratio = INTERACTION_QUALITY_PRESETS["high"]["interactive_ratio"]
    state.still_quality = 98
    state.still_ratio = 1
    state.mainViewMode = "remote"
    state.can_edit_active = False
    state.edit_session_active = False
    state.edit_session_label = ""
    state.edit_status = ""
    state.edit_status_type = "info"
    state.save_target_label = "Active pipeline result"
    state.edit_geometry_mode = "volume"
    state.edit_geometry_mode_options = [
        {"text": "Volume", "value": "volume"},
        {"text": "Surface", "value": "surface"},
        {"text": "Edge", "value": "edge"},
        {"text": "Point", "value": "point"},
    ]
    state.edit_field_name = ""
    state.edit_expression = ""
    state.edit_default_value = "0"
    state.edit_available_variables = []
    state.edit_vector_syntax = "Use arrayName[0], arrayName[1], arrayName[2]"
    state.edit_apply_status = ""
    state.edit_apply_status_type = "info"
    state.edit_overwrite_dialog = False
    state.edit_overwrite_field_name = ""
    state.edit_selection_status = ""
    state.edit_selection_status_type = "info"
    state.edit_selection_event = ""
    state.edit_selection_mode = "replace"
    state.edit_selection_mode_options = [
        {"text": "Replace", "value": "replace"},
        {"text": "Add", "value": "add"},
        {"text": "Subtract", "value": "subtract"},
        {"text": "Flip", "value": "flip"},
    ]
    state.edit_enable_picking = False
    state.edit_picking_modes = []
    state.edit_interactor_events = []
    state.edit_interactor_settings = [
        {"button": 1, "action": "Rotate"},
        {"button": 2, "action": "Pan"},
        {"button": 3, "action": "Zoom", "scrollEnabled": True},
    ]
    state.edit_view_style = "width: 100%; height: 100%; cursor: default; outline: none;"
    state.pv_runtime_message = ""
    state.pv_runtime_type = "error"
    state.show_calculator_help = False
    state.calculator_attribute_type = ""
    state.calculator_input_variables = []
    state.calculator_coordinate_variables = []
    state.edit_mode = False
    state.edit_target = BOUNDARY
    state.selection_count = 0
    state.assign_id_value = "0"
    state.save_filename = "output"
    state.save_status = ""
    state.save_status_type = "success"
    state.pick_mode = False
    state.selection_behavior = "touch"
    state.selection_behavior_options = [
        {"text": "Touch", "value": "touch"},
        {"text": "Contained", "value": "inside"},
    ]
    state.group_select = False
    state.angle_threshold = 15
