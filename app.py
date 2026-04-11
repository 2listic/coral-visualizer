import argparse
import os
from pathlib import Path

if os.environ.get("PV_VENV") or "--venv" in os.sys.argv:
    import paraview.web.venv  # noqa: F401

from trame.app.file_upload import ClientFile
from trame.app import get_server
from vtkmodules.vtkCommonCore import vtkOutputWindow, vtkStringOutputWindow

from constants import (
    ARRAY_SOLID,
    BOUNDARY,
    CELL_PREFIX,
    MANIFOLD_ID_ARRAY,
    MATERIAL_ID_ARRAY,
    REPR_SURFACE_EDGES,
    SCALAR_BAR_ACTIVE_ARRAY,
    SCALAR_BAR_BOUNDARY,
    VOLUME,
)
from edit_session import EditSession
from file_utils import get_vtk_files_from_data_folder
from pv_backend import ParaViewBackend, is_paraview_available
from vtk_pipeline import (
    build_visualization,
    apply_categorical_coloring,
    get_available_arrays,
    apply_coloring,
    apply_representation,
    create_vtk_rendering_context,
)
from scalar_bars import ScalarBarManager
from interactor import PickInteractorManager
from mesh_edit import (
    BoundaryEditState,
    assign_id_to_selection,
    update_selection_actor,
    save_as_vtu,
    setup_edit_state,
)
from ui import build_ui

# -----------------------------------------------------------------------------
# Command-line arguments
# -----------------------------------------------------------------------------

parser = argparse.ArgumentParser(description="Flexible VTK Visualization with Trame")
parser.add_argument(
    "--file",
    # default=os.path.join(CURRENT_DIRECTORY, "data/grid-1.vtk"),
    default=None,
    help="Path to VTK file to open on start (i.e.: data/grid-1.vtk)",
)
parser.add_argument(
    "--data-directory",
    default="./data",
    help="Directory containing input/output VTK files (default: ./data)",
)
parser.add_argument(
    "--backend",
    choices=["auto", "vtk", "paraview"],
    default="auto",
    help="Rendering backend to use (default: auto)",
)
parser.add_argument(
    "--dev",
    action="store_true",
    help="Enable development mode conveniences, including Trame hot reload.",
)
parser.add_argument(
    "--hide-experimental-filters",
    action="store_true",
    help="Hide experimentally discovered ParaView filters from the Filter menu.",
)
# Parse known args and let trame handle the rest (--port, --host, --debug, etc.)
args, unknown = parser.parse_known_args()
data_directory = os.path.abspath(args.data_directory)

if args.dev and "--hot-reload" not in os.sys.argv:
    os.sys.argv.append("--hot-reload")
    os.environ["TRAME_HOT_RELOAD"] = "1"

PARAVIEW_AVAILABLE = is_paraview_available()
if args.backend == "auto":
    BACKEND = "paraview" if PARAVIEW_AVAILABLE else "vtk"
elif args.backend == "paraview" and not PARAVIEW_AVAILABLE:
    BACKEND = "vtk"
else:
    BACKEND = args.backend

BACKEND_MESSAGE = ""
if args.backend == "paraview" and BACKEND != "paraview":
    BACKEND_MESSAGE = (
        "ParaView backend requested but not available in this Python environment. "
        "Falling back to the VTK backend."
    )
elif args.backend == "auto" and BACKEND == "vtk" and not PARAVIEW_AVAILABLE:
    BACKEND_MESSAGE = (
        "ParaView backend not detected. Running with the legacy VTK backend."
    )


# -----------------------------------------------------------------------------
# Rendering setup
# -----------------------------------------------------------------------------

renderer = None
renderWindow = None
renderWindowInteractor = None
render_target = None

# Module-level pipeline references (updated whenever a file is loaded)
_viz = None  # VisualizationResult | None
_active_lut = None  # LUT currently used for the "Color by" coloring
_pv_backend = None
_edit_session = EditSession()
_pv_output_window = None
_pv_output_offset = 0

if BACKEND == "paraview":
    _pv_output_window = vtkStringOutputWindow()
    vtkOutputWindow.SetInstance(_pv_output_window)
    _pv_backend = ParaViewBackend(
        data_directory=data_directory,
        show_experimental_filters=not args.hide_experimental_filters,
    )
    render_target = _pv_backend.initialize_view()
    _scalar_bars = None
else:
    renderer, renderWindow, renderWindowInteractor = create_vtk_rendering_context()
    render_target = renderWindow
    _scalar_bars = ScalarBarManager(renderer)

# Boundary editing state
_edit = BoundaryEditState()

DEFAULT_REPRESENTATION = REPR_SURFACE_EDGES
INTERACTION_QUALITY_PRESETS = {
    "fast": {"interactive_quality": 60, "interactive_ratio": 0.7},
    "balanced": {"interactive_quality": 80, "interactive_ratio": 0.85},
    "high": {"interactive_quality": 95, "interactive_ratio": 1},
}

available_files = get_vtk_files_from_data_folder(data_directory)
initial_file = (
    args.file
    if args.file and os.path.exists(args.file)
    else (available_files[0]["value"] if available_files else None)
)
_initial_arrays = [{"text": "Solid Color", "value": ARRAY_SOLID}]
_initial_array = ARRAY_SOLID


# -----------------------------------------------------------------------------
# Trame Server Setup
# -----------------------------------------------------------------------------

server = get_server(client_type="vue2")
state = server.state
ctrl = server.controller

# Initialize state.
state.available_files = available_files
# selected_file will trigger on_file_change and render the initial file.
state.selected_file = initial_file
state.error_message = ""
state.available_arrays = _initial_arrays
state.selected_array = _initial_array
state.representation = DEFAULT_REPRESENTATION
state.has_boundary = False
state.backend = BACKEND
state.backend_message = BACKEND_MESSAGE
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
_filter_catalog = _pv_backend.get_available_filters() if _pv_backend else {"supported": [], "experimental": []}
state.filter_supported_options = _filter_catalog["supported"]
state.filter_experimental_options = _filter_catalog["experimental"]
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
state.can_edit_active = False
state.edit_session_active = False
state.edit_session_label = ""
state.edit_status = ""
state.edit_status_type = "info"
state.save_target_label = "Active pipeline result"
state.pv_runtime_message = ""
state.pv_runtime_type = "error"
state.show_calculator_help = False
state.calculator_attribute_type = ""
state.calculator_input_variables = []
state.calculator_coordinate_variables = []

# Edit mode state
state.edit_mode = False
state.edit_target = BOUNDARY  # BOUNDARY | VOLUME
state.selection_count = 0
state.assign_id_value = "0"
state.save_filename = "output"
state.save_status = ""
state.save_status_type = "success"
state.pick_mode = True
state.group_select = False
state.angle_threshold = 15


# -----------------------------------------------------------------------------
# Build UI
# -----------------------------------------------------------------------------

build_ui(server, render_target, BACKEND)

_pick_interactor = None
if BACKEND == "vtk":
    _pick_interactor = PickInteractorManager(
        renderWindowInteractor, renderer, renderWindow, state, ctrl, _edit
    )


# -----------------------------------------------------------------------------
# Private helpers
# -----------------------------------------------------------------------------


def _array_label(array_value):
    """Human-readable label for a Color by array value."""
    if array_value == f"{CELL_PREFIX}{MATERIAL_ID_ARRAY}":
        return "Material ID"
    if array_value == f"{CELL_PREFIX}{MANIFOLD_ID_ARRAY}":
        return "Manifold ID"
    if ":" in array_value:
        return array_value.split(":", 1)[1]
    return array_value


def _update_scalar_bars(active_lut, array_value):
    """Manage all scalar bars: the active coloring bar and the boundary ID bar."""
    if BACKEND != "vtk":
        return

    if active_lut is not None:
        _scalar_bars.set_bar(
            SCALAR_BAR_ACTIVE_ARRAY, active_lut, _array_label(array_value)
        )
    else:
        _scalar_bars.remove_bar(SCALAR_BAR_ACTIVE_ARRAY)

    # Boundary coloring bar only when MaterialID selected + boundary exists in view mode
    is_material_id = array_value == f"{CELL_PREFIX}{MATERIAL_ID_ARRAY}"
    bnd_lut = _viz.bnd_luts.get(MATERIAL_ID_ARRAY) if is_material_id and _viz else None
    if bnd_lut is not None:
        _scalar_bars.set_bar(SCALAR_BAR_BOUNDARY, bnd_lut, "Boundary ID")
    else:
        _scalar_bars.remove_bar(SCALAR_BAR_BOUNDARY)


def _apply_edit_coloring(edit_target):
    """Apply coloring and actor visibility for the given edit target.

    BOUNDARY: shows the boundary overlay with categorical MaterialID coloring,
      sets the volume actor to solid gray.
    VOLUME: hides the boundary overlay, applies categorical MaterialID coloring
      to the volume actor.
    """
    if BACKEND != "vtk":
        return

    if edit_target == BOUNDARY:
        if _edit.merged_bnd_actor:
            _edit.merged_bnd_actor.SetVisibility(1)
        if _edit.merged_bnd_dataset is not None and _edit.merged_bnd_mapper is not None:
            lut, _ = apply_categorical_coloring(
                _edit.merged_bnd_mapper, _edit.merged_bnd_dataset, MATERIAL_ID_ARRAY
            )
            if lut is not None:
                _scalar_bars.set_bar(SCALAR_BAR_BOUNDARY, lut, "Boundary ID")
        if _viz:
            _viz.vol_mapper.ScalarVisibilityOff()
            _viz.vol_actor.GetProperty().SetColor(0.7, 0.7, 0.7)
        _scalar_bars.remove_bar(SCALAR_BAR_ACTIVE_ARRAY)
    else:  # VOLUME
        if _edit.merged_bnd_actor:
            _edit.merged_bnd_actor.SetVisibility(0)
        _scalar_bars.remove_bar(SCALAR_BAR_BOUNDARY)
        if _edit.vol_dataset is None or _viz is None:
            return
        lut, _ = apply_categorical_coloring(
            _viz.vol_mapper, _edit.vol_dataset, MATERIAL_ID_ARRAY
        )
        if lut is None:
            return
        _viz.vol_dataset.Modified()
        _scalar_bars.set_bar(SCALAR_BAR_ACTIVE_ARRAY, lut, "Material ID")


def _render_and_push():
    """Render the active backend and push the updated view to the client."""
    if BACKEND == "paraview":
        _pv_backend.render()
    else:
        renderWindow.Render()
    ctrl.view_update()


def _refresh_available_files():
    """Refresh the file list exposed to the UI."""
    state.available_files = get_vtk_files_from_data_folder(data_directory)


def _resolve_output_path(filename, fallback_name):
    """Resolve a save target strictly inside ``data_directory``."""
    raw_name = (filename or "").strip() or fallback_name
    candidate = Path(raw_name)
    relative_candidate = Path(*candidate.parts[1:]) if candidate.is_absolute() else candidate
    normalized = Path(os.path.normpath(str(relative_candidate)))
    if str(normalized).startswith(".."):
        raise ValueError("Output path must stay inside --data-directory")
    return os.path.join(data_directory, str(normalized))


def _persist_uploaded_file(client_file):
    """Persist an uploaded client-side dataset into the data directory."""
    uploads_dir = Path(data_directory) / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    original_name = Path(client_file.name or "upload.vtu").name
    stem = Path(original_name).stem
    suffix = Path(original_name).suffix or ".vtu"
    candidate = uploads_dir / original_name
    counter = 1
    while candidate.exists():
        candidate = uploads_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    candidate.write_bytes(client_file.content)
    return str(candidate)


def _refresh_paraview_runtime_message(clear=False):
    """Drain recent ParaView/VTK runtime output into a user-facing alert."""
    global _pv_output_offset

    if BACKEND != "paraview" or _pv_output_window is None:
        return

    output = _pv_output_window.GetOutput() or ""
    if clear:
        state.pv_runtime_message = ""
        state.pv_runtime_type = "error"
        _pv_output_offset = len(output)
        return

    if len(output) <= _pv_output_offset:
        return

    new_output = output[_pv_output_offset:]
    _pv_output_offset = len(output)
    lines = [
        line.strip()
        for line in new_output.splitlines()
        if line.strip() and "Saving settings file" not in line
    ]
    if not lines:
        return

    state.pv_runtime_message = "\n".join(lines[-4:])
    state.pv_runtime_type = (
        "error"
        if any(("ERROR:" in line or "Err:" in line) for line in lines)
        else "warning"
    )


def _save_paraview_output():
    """Save the active ParaView output or edit-session dataset and return its path."""
    if _pv_backend.source is None and not _edit_session.active:
        raise RuntimeError("No active pipeline item to save")

    if _edit_session.active:
        fallback_name = _edit_session.default_output_filename()
        output_path = _resolve_output_path(state.save_filename, fallback_name)
        if not os.path.splitext(output_path)[1]:
            output_path += ".vtu"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        _edit_session.save(output_path)
        saved_kind = "edited dataset"
    else:
        fallback_name = _pv_backend.default_output_filename()
        output_path = _resolve_output_path(state.save_filename, fallback_name)
        if not os.path.splitext(output_path)[1]:
            output_path += _pv_backend._default_output_extension()
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        _pv_backend.save_active_data(output_path)
        saved_kind = "pipeline result"

    _refresh_available_files()
    relative_output = os.path.relpath(output_path, data_directory)
    state.save_filename = relative_output
    state.save_status = f"Saved {saved_kind} to {relative_output}"
    state.save_status_type = "success"
    return output_path


def _update_paraview_ui_state():
    """Synchronize Trame state with the active ParaView source metadata."""
    if BACKEND != "paraview" or _pv_backend is None:
        return

    ui_state = _pv_backend.get_ui_state()
    state.pipeline_items = ui_state["pipeline_items"]
    state.active_pipeline_item = ui_state["active_pipeline_item"]
    state.active_source_label = ui_state["active_source_label"]
    state.active_source_type = ui_state["active_source_type"]
    state.active_source_kind = ui_state["active_source_kind"]
    state.active_parent_label = ui_state["active_parent_label"]
    state.source_path = ui_state["source_path"]
    state.point_arrays = ui_state["point_arrays"]
    state.cell_arrays = ui_state["cell_arrays"]
    state.data_stats = ui_state["data_stats"]
    state.source_properties = ui_state["source_properties"]
    state.display_properties = ui_state["display_properties"]
    state.show_calculator_help = ui_state["show_calculator_help"]
    state.calculator_attribute_type = ui_state["calculator_attribute_type"]
    state.calculator_input_variables = ui_state["calculator_input_variables"]
    state.calculator_coordinate_variables = ui_state["calculator_coordinate_variables"]
    state.source_default_property_count = len(
        [item for item in state.source_properties if item["visibility"] == "default"]
    )
    state.source_advanced_property_count = len(
        [item for item in state.source_properties if item["visibility"] == "advanced"]
    )
    state.display_default_property_count = len(
        [item for item in state.display_properties if item["visibility"] == "default"]
    )
    state.display_advanced_property_count = len(
        [item for item in state.display_properties if item["visibility"] == "advanced"]
    )
    state.active_visibility = ui_state["active_visibility"]
    state.available_arrays = ui_state["point_arrays"] + ui_state["cell_arrays"]
    state.available_arrays.insert(0, {"text": "Solid Color", "value": ARRAY_SOLID})
    state.selected_array = ui_state["selected_array"]
    state.representation = ui_state["representation"]
    state.pv_properties_dirty = False
    if not state.save_filename or state.save_filename == "output":
        state.save_filename = _edit_session.default_output_filename() if _edit_session.active else _pv_backend.default_output_filename()
    state.save_target_label = (
        f"Edited dataset: {_edit_session.source_label}"
        if _edit_session.active
        else f"Active pipeline result: {state.active_source_label}"
        if state.active_source_label
        else "Active pipeline result"
    )
    try:
        _pv_backend.export_active_dataset_for_editing()
        state.can_edit_active = True
    except Exception:
        state.can_edit_active = False


# -----------------------------------------------------------------------------
# State Callbacks
# -----------------------------------------------------------------------------


@state.change("selected_file")
def on_file_change(selected_file, **kwargs):
    """Reload pipeline and reset coloring/representation when file changes."""
    global _viz, _active_lut

    if selected_file and os.path.exists(selected_file):
        try:
            print(f"\nLoading file: {selected_file}")

            # Exit edit mode if active
            if state.edit_mode:
                state.edit_mode = False

            if BACKEND == "paraview":
                _refresh_paraview_runtime_message(clear=True)
                arrays, default_array = _pv_backend.load_file(selected_file)
                _pv_backend.apply_representation(state.representation)
                _pv_backend.apply_coloring(default_array)
                _refresh_paraview_runtime_message()
                _update_paraview_ui_state()
                state.has_boundary = False
                state.error_message = ""
                state.selection_count = 0
                state.save_status = ""

                _render_and_push()
                return

            _viz = build_visualization(selected_file, renderer)

            arrays = get_available_arrays(_viz.full_dataset)
            default_array = next(
                (
                    a["value"]
                    for a in arrays
                    if a["value"] == f"{CELL_PREFIX}{MATERIAL_ID_ARRAY}"
                ),
                arrays[1]["value"] if len(arrays) > 1 else ARRAY_SOLID,
            )

            _active_lut = apply_coloring(
                _viz.vol_actor,
                _viz.vol_mapper,
                _viz.vol_dataset,
                default_array,
                _viz.vol_luts,
            )
            if _viz.bnd_actor is not None:
                apply_coloring(
                    _viz.bnd_actor,
                    _viz.bnd_mapper,
                    _viz.bnd_dataset,
                    default_array,
                    _viz.bnd_luts,
                )
            apply_representation(_viz.vol_actor, _viz.bnd_actor, state.representation)
            _update_scalar_bars(_active_lut, default_array)

            # Set up boundary editing infrastructure
            setup_edit_state(_edit, _viz, renderer)

            state.available_arrays = arrays
            state.selected_array = default_array
            state.has_boundary = (
                _viz.bnd_actor is not None or _edit.merged_bnd_dataset is not None
            )
            state.error_message = ""
            state.selection_count = 0
            state.save_status = ""

            _render_and_push()
        except Exception as e:
            state.error_message = f"Error loading file: {str(e)}"
            print(f"Error: {e}")
            import traceback

            traceback.print_exc()


@state.change("selected_array")
def on_array_change(selected_array, **kwargs):
    """Update coloring when the user picks a different array."""
    global _active_lut
    if BACKEND == "paraview":
        if selected_array and _pv_backend.source is not None:
            _pv_backend.apply_coloring(selected_array)
            _update_paraview_ui_state()
            ctrl.view_update()
        return

    if _viz is not None:
        _active_lut = apply_coloring(
            _viz.vol_actor,
            _viz.vol_mapper,
            _viz.vol_dataset,
            selected_array,
            _viz.vol_luts,
        )
        if _viz.bnd_actor is not None:
            apply_coloring(
                _viz.bnd_actor,
                _viz.bnd_mapper,
                _viz.bnd_dataset,
                selected_array,
                _viz.bnd_luts,
            )
        _update_scalar_bars(_active_lut, selected_array)
        _render_and_push()


@state.change("representation")
def on_representation_change(representation, **kwargs):
    """Update actor representation when the user picks a different mode."""
    if BACKEND == "paraview":
        if _pv_backend.display is not None:
            _pv_backend.apply_representation(representation)
            _update_paraview_ui_state()
            ctrl.view_update()
        return


@state.change("active_pipeline_item")
def on_active_pipeline_item_change(active_pipeline_item, **kwargs):
    """Switch active ParaView node when the pipeline selection changes."""
    if BACKEND != "paraview":
        return
    if not active_pipeline_item:
        return
    if not _pv_backend.set_active_node(active_pipeline_item):
        return

    _update_paraview_ui_state()
    _render_and_push()

    if _viz is not None:
        apply_representation(_viz.vol_actor, _viz.bnd_actor, representation)
        _render_and_push()


@state.change("interaction_quality")
def on_interaction_quality_change(interaction_quality, **kwargs):
    """Update remote-render interaction quality preset."""
    preset = INTERACTION_QUALITY_PRESETS.get(
        interaction_quality, INTERACTION_QUALITY_PRESETS["high"]
    )
    state.interactive_quality = preset["interactive_quality"]
    state.interactive_ratio = preset["interactive_ratio"]


@state.change("edit_mode")
def on_edit_mode_change(edit_mode, **kwargs):
    """Toggle between view mode and boundary edit mode."""
    if BACKEND != "vtk":
        if edit_mode:
            state.edit_mode = False
            state.error_message = (
                "Edit mode is not available on the ParaView backend yet."
            )
        return

    if _edit.merged_bnd_actor is None:
        if edit_mode:
            state.edit_mode = False
            state.error_message = "No boundary cells available for editing"
        return

    if edit_mode:
        # Enter edit mode — always start in boundary target
        state.edit_target = BOUNDARY
        state.pick_mode = True
        if _viz and _viz.bnd_actor:
            _viz.bnd_actor.SetVisibility(0)
        _apply_edit_coloring(BOUNDARY)
        _pick_interactor.install()
    else:
        # Exit edit mode
        _pick_interactor.remove()
        _edit.merged_bnd_actor.SetVisibility(0)
        _edit.bnd_selection_actor.SetVisibility(0)
        _edit.bnd_selection_set.clear()
        if _edit.vol_selection_actor:
            _edit.vol_selection_actor.SetVisibility(0)
        _edit.vol_selection_set.clear()
        state.selection_count = 0
        if _viz and _viz.bnd_actor:
            _viz.bnd_actor.SetVisibility(1)
        # Restore boundary scalar bar and volume coloring from the saved view-mode LUT
        _update_scalar_bars(_active_lut, state.selected_array)
        if _viz:
            apply_coloring(
                _viz.vol_actor,
                _viz.vol_mapper,
                _viz.vol_dataset,
                state.selected_array,
                _viz.vol_luts,
            )

    _render_and_push()


@state.change("edit_target")
def on_edit_target_change(edit_target, **kwargs):
    """Switch between boundary and volume edit targets, clearing the selection."""
    if BACKEND != "vtk":
        return

    if not state.edit_mode:
        return

    # Clear both selections
    _edit.bnd_selection_set.clear()
    _edit.vol_selection_set.clear()
    update_selection_actor(
        _edit.bnd_selection_set,
        _edit.merged_bnd_dataset,
        _edit.bnd_selection_actor,
        _edit.bnd_selection_mapper,
    )
    if _edit.vol_dataset is not None:
        update_selection_actor(
            _edit.vol_selection_set,
            _edit.vol_dataset,
            _edit.vol_selection_actor,
            _edit.vol_selection_mapper,
        )
    state.selection_count = 0

    _apply_edit_coloring(edit_target)

    _render_and_push()


# -----------------------------------------------------------------------------
# Controller methods (called from UI buttons)
# -----------------------------------------------------------------------------


@ctrl.add("clear_selection")
def clear_selection():
    """Clear all selected cells (boundary or volume depending on edit_target)."""
    if BACKEND != "vtk":
        return

    if state.edit_target == VOLUME:
        _edit.vol_selection_set.clear()
        if _edit.vol_dataset is not None:
            update_selection_actor(
                _edit.vol_selection_set,
                _edit.vol_dataset,
                _edit.vol_selection_actor,
                _edit.vol_selection_mapper,
            )
    else:
        _edit.bnd_selection_set.clear()
        update_selection_actor(
            _edit.bnd_selection_set,
            _edit.merged_bnd_dataset,
            _edit.bnd_selection_actor,
            _edit.bnd_selection_mapper,
        )
    state.selection_count = 0
    _render_and_push()


@ctrl.add("select_all")
def select_all():
    """Select all cells (boundary or volume depending on edit_target)."""
    if BACKEND != "vtk":
        return

    if state.edit_target == VOLUME:
        if _edit.vol_dataset is not None:
            n = _edit.vol_dataset.GetNumberOfCells()
            _edit.vol_selection_set = set(range(n))
            update_selection_actor(
                _edit.vol_selection_set,
                _edit.vol_dataset,
                _edit.vol_selection_actor,
                _edit.vol_selection_mapper,
            )
            state.selection_count = n
            _render_and_push()
    else:  # boundary
        if _edit.merged_bnd_dataset is not None:
            n = _edit.merged_bnd_dataset.GetNumberOfCells()
            _edit.bnd_selection_set = set(range(n))
            update_selection_actor(
                _edit.bnd_selection_set,
                _edit.merged_bnd_dataset,
                _edit.bnd_selection_actor,
                _edit.bnd_selection_mapper,
            )
            state.selection_count = n
            _render_and_push()


@ctrl.add("assign_id")
def assign_id():
    """Assign the chosen ID value to all selected cells (boundary or volume)."""
    if BACKEND != "vtk":
        state.error_message = "Editing is only available on the VTK backend."
        return

    try:
        value = int(state.assign_id_value)
    except (ValueError, TypeError):
        state.error_message = "Invalid ID value — must be an integer"
        return

    if state.edit_target == VOLUME:
        if not _edit.vol_selection_set or _edit.vol_dataset is None:
            return

        arr = _edit.vol_dataset.GetCellData().GetArray(MATERIAL_ID_ARRAY)
        if arr is None:
            return
        for cell_idx in _edit.vol_selection_set:
            arr.SetValue(cell_idx, value)
        _edit.vol_dataset.Modified()

        _apply_edit_coloring(VOLUME)

        _edit.vol_selection_set.clear()
        update_selection_actor(
            _edit.vol_selection_set,
            _edit.vol_dataset,
            _edit.vol_selection_actor,
            _edit.vol_selection_mapper,
        )
    else:
        if not _edit.bnd_selection_set or _edit.merged_bnd_dataset is None:
            return

        assign_id_to_selection(_edit, MATERIAL_ID_ARRAY, value)
        _apply_edit_coloring(BOUNDARY)

        _edit.bnd_selection_set.clear()
        update_selection_actor(
            _edit.bnd_selection_set,
            _edit.merged_bnd_dataset,
            _edit.bnd_selection_actor,
            _edit.bnd_selection_mapper,
        )

    state.selection_count = 0
    _render_and_push()


@ctrl.add("save_vtu")
def save_vtu():
    """Save the modified mesh as .vtu."""
    if BACKEND != "vtk":
        state.save_status = "Save is not available on the ParaView backend yet"
        state.save_status_type = "error"
        return

    if _edit.full_dataset is None or _edit.merged_bnd_dataset is None:
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

        save_as_vtu(_edit, output_path)

        state.save_status = f"Saved to {os.path.relpath(output_path)}"
        state.save_status_type = "success"

        # Refresh file list so the new file appears in the dropdown
        state.available_files = get_vtk_files_from_data_folder(data_directory)
        print(f"  Saved to {output_path}")
    except Exception as e:
        state.save_status = f"Error: {str(e)}"
        state.save_status_type = "error"
        print(f"Save error: {e}")
        import traceback

        traceback.print_exc()


@ctrl.add("reset_camera")
def reset_camera():
    """Reset the active camera for the selected backend."""
    if BACKEND == "paraview":
        _pv_backend.reset_camera()
        ctrl.view_update()
        return

    if renderer is not None and renderWindow is not None:
        renderer.ResetCamera()
        _render_and_push()


@ctrl.add("pv_update_property")
def pv_update_property(scope, name, value):
    """Update a pending ParaView property edit in Trame state."""
    if BACKEND != "paraview":
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
    if BACKEND != "paraview":
        return

    _refresh_paraview_runtime_message(clear=True)
    _pv_backend.apply_property_changes(
        state.source_properties, state.display_properties
    )
    _refresh_paraview_runtime_message()
    _update_paraview_ui_state()
    _render_and_push()


@ctrl.add("pv_reset_properties")
def pv_reset_properties():
    """Discard pending property edits and refresh the generated inspector."""
    if BACKEND != "paraview":
        return

    _update_paraview_ui_state()


@ctrl.add("pv_toggle_visibility")
def pv_toggle_visibility():
    """Toggle visibility of the active ParaView node."""
    if BACKEND != "paraview" or not state.active_pipeline_item:
        return

    _pv_backend.set_visibility(state.active_pipeline_item, not state.active_visibility)
    _update_paraview_ui_state()
    _render_and_push()


@ctrl.add("pv_toggle_visibility_for")
def pv_toggle_visibility_for(node_id):
    """Toggle visibility for a specific ParaView pipeline node."""
    if BACKEND != "paraview" or not node_id:
        return

    node = _pv_backend._find_node(node_id)
    if node is None or node.get("display") is None:
        return

    _pv_backend.set_visibility(node_id, not bool(node["display"].Visibility))
    _update_paraview_ui_state()
    _render_and_push()


@ctrl.add("pv_delete_active")
def pv_delete_active():
    """Delete the active ParaView node from the pipeline."""
    if BACKEND != "paraview" or not state.active_pipeline_item:
        return

    _pv_backend.delete_node(state.active_pipeline_item)
    _update_paraview_ui_state()
    state.save_status = ""
    _render_and_push()


@ctrl.add("pv_add_filter")
def pv_add_filter(filter_key):
    """Add a supported filter to the active ParaView node."""
    if BACKEND != "paraview" or not state.active_pipeline_item:
        return
    if not filter_key:
        return

    try:
        _refresh_paraview_runtime_message(clear=True)
        _pv_backend.add_filter(filter_key)
        _refresh_paraview_runtime_message()
        state.filter_menu = False
        _update_paraview_ui_state()
        _render_and_push()
    except Exception as exc:
        state.error_message = f"Error adding filter: {exc}"


@ctrl.add("pv_save_active_data")
def pv_save_active_data():
    """Save the active ParaView output or edit-session result to a new file."""
    if BACKEND != "paraview":
        return

    try:
        _save_paraview_output()
    except Exception as exc:
        state.save_status = f"Error: {exc}"
        state.save_status_type = "error"


@ctrl.add("pv_begin_edit_session")
def pv_begin_edit_session():
    """Initialize an edit session from the active ParaView pipeline node."""
    if BACKEND != "paraview":
        return

    try:
        exported = _pv_backend.export_active_dataset_for_editing()
        _edit_session.begin(
            exported["node_id"],
            exported["label"],
            exported["filename"],
            exported["dataset"],
        )
        state.edit_session_active = True
        state.edit_session_label = exported["label"]
        state.save_filename = _edit_session.default_output_filename()
        state.save_target_label = f"Edited dataset: {exported['label']}"
        state.save_status = ""
        state.edit_status = (
            f"Edit session initialized for {exported['label']}. "
            "Interactive editing tools are the next integration step."
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
    _edit_session.clear()
    state.edit_session_active = False
    state.edit_session_label = ""
    if BACKEND == "paraview" and _pv_backend is not None:
        state.save_filename = _pv_backend.default_output_filename()
        state.save_target_label = (
            f"Active pipeline result: {state.active_source_label}"
            if state.active_source_label
            else "Active pipeline result"
        )
    state.edit_status = "Edit session discarded"
    state.edit_status_type = "info"


@ctrl.add("pv_commit_edit_session")
def pv_commit_edit_session():
    """Save the current edit session and append it as a new pipeline source."""
    if BACKEND != "paraview" or not _edit_session.active:
        return

    try:
        output_path = _save_paraview_output()
        _edit_session.clear()
        state.edit_session_active = False
        state.edit_session_label = ""
        state.edit_status = "Edit session saved and added to the pipeline"
        state.edit_status_type = "success"

        arrays, default_array = _pv_backend.load_file(output_path)
        _pv_backend.apply_representation(state.representation)
        _pv_backend.apply_coloring(default_array)
        _update_paraview_ui_state()
        state.available_arrays = arrays
        state.selected_array = default_array
        _render_and_push()
    except Exception as exc:
        state.edit_status = f"Could not add edited result to pipeline: {exc}"
        state.edit_status_type = "error"


@ctrl.add("upload_dataset")
def upload_dataset(files):
    """Handle a dataset upload from the browser file picker."""
    uploaded_files = files or []
    if not uploaded_files:
        return

    client_file = ClientFile(uploaded_files[0])
    if client_file.is_empty:
        state.upload_status = "Uploaded file was empty"
        state.upload_status_type = "error"
        return

    try:
        saved_path = _persist_uploaded_file(client_file)
        _refresh_available_files()
        state.selected_file = saved_path
        state.upload_status = f"Loaded {os.path.basename(saved_path)}"
        state.upload_status_type = "success"
    except Exception as exc:
        state.upload_status = f"Upload failed: {exc}"
        state.upload_status_type = "error"


@ctrl.add("open_remote_file")
def open_remote_file(path):
    """Open a file that already exists under the remote data directory."""
    if not path:
        return

    state.remote_browser_dialog = False
    state.selected_file = path


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    server.start()
