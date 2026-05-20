"""Helpers for initializing Trame state."""

import os

from constants import ARRAY_SOLID, BOUNDARY, INTERACTION_QUALITY_PRESETS

DEFAULT_REPRESENTATION = "Surface with Edges"


def resolve_initial_file(requested_file, available_files):
    """Pick the initial dataset path to expose in state."""
    if requested_file and os.path.exists(requested_file):
        return requested_file
    for item in available_files or []:
        if item.get("value"):
            return item["value"]
    return None


def initialize_state(
    state,
    *,
    available_files,
    initial_file,
    pv_backend,
):
    """Populate the Trame state object with the app defaults."""
    initial_arrays = [{"text": "Solid Color", "value": ARRAY_SOLID}]
    filter_catalog = pv_backend.get_available_filters()

    state.available_files = available_files
    state.selected_file = initial_file
    state.error_message = ""
    state.notification_message = ""
    state.notification_type = "info"
    state.notification_show = False
    state.available_arrays = initial_arrays
    state.selected_array = ARRAY_SOLID
    state.representation = DEFAULT_REPRESENTATION
    state.show_cells = True
    state.show_faces = True
    state.has_boundary = False
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
    state.color_controls_enabled = False
    state.color_map_preset = "Viridis (matplotlib)"
    state.color_map_preset_options = [
        {"text": "Viridis", "value": "Viridis (matplotlib)"},
        {"text": "Cool to Warm", "value": "Cool to Warm"},
        {"text": "Rainbow Desaturated", "value": "Rainbow Desaturated"},
        {"text": "Black-Body Radiation", "value": "Black-Body Radiation"},
        {"text": "X Ray", "value": "X Ray"},
        {"text": "Grayscale", "value": "Grayscale"},
    ]
    state.color_range_min = ""
    state.color_range_max = ""
    state.color_bar_visible = False
    state.orientation_axes_visible = True
    state.categorical_coloring = False

    # Time/Simulation state
    state.time_values = []
    state.current_time = 0.0
    state.time_index = 0
    state.total_timesteps = 0
    state.is_time_dependent = False
    state.rescale_over_time_dialog = False
    state.time_playing = False
    state.time_loop = True
    state.inspector_tab = 0
    state.pv_properties_dirty = False
    state.active_visibility = True
    state.remote_browser_dialog = False
    state.remote_search_term = ""
    state.filtered_available_files = available_files
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
    state.interactive_quality = INTERACTION_QUALITY_PRESETS["high"][
        "interactive_quality"
    ]
    state.interactive_ratio = INTERACTION_QUALITY_PRESETS["high"]["interactive_ratio"]
    state.still_quality = 98
    state.still_ratio = 1
    state.mainViewMode = "remote"
    state.can_edit_active = False
    state.edit_session_active = False
    state.edit_session_label = ""
    state.save_target_label = "Active pipeline result"
    state.edit_geometry_mode = "volume"
    state.edit_geometry_mode_options = [
        {"text": "Volume", "value": "volume"},
        {"text": "Surface", "value": "surface"},
        {"text": "Point", "value": "point"},
    ]
    state.edit_cell_geometry_mode_options = [
        {"text": "Volume", "value": "volume"},
        {"text": "Surface", "value": "surface"},
    ]
    state.edit_point_geometry_mode_options = [
        {"text": "Point", "value": "point"},
    ]
    state.edit_field_association = "cell"
    state.edit_field_choice = ""
    state.edit_field_options = []
    state.edit_field_name = ""
    state.edit_expression = ""
    state.edit_default_value = "0"
    state.edit_available_variables = []
    state.edit_create_field_dialog = False
    state.edit_new_field_name = ""
    state.edit_new_field_default_value = "0"
    state.edit_new_field_association = "cell"
    state.edit_new_field_association_options = [
        {"text": "Cell data array", "value": "cell"},
        {"text": "Point data array", "value": "point"},
    ]
    state.edit_vector_syntax = "Use arrayName[0], arrayName[1], arrayName[2]"
    state.edit_overwrite_dialog = False
    state.edit_overwrite_field_name = ""
    state.edit_selection_event = ""
    state.selection_timing_last = ""
    state.selection_timing_payload = {}
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
    state.state_files = []
    state.state_filename = "session.coral.state.json"
    state.state_browser_dialog = False
    state.state_browser_search_term = ""
    state.filtered_state_files = []
    state.save_dialog = False
    state.save_dialog_action = ""
    state.save_overwrite_dialog = False
    state.save_overwrite_target = ""
    state.save_overwrite_action = ""
    state.pick_mode = False
    state.selection_behavior = "touch"
    state.selection_behavior_options = [
        {"text": "Touch", "value": "touch"},
        {"text": "Contained", "value": "inside"},
    ]
    state.group_select = False
    state.angle_threshold = 15
