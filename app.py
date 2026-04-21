import argparse
import json
import os
from pathlib import Path

if os.environ.get("PV_VENV") or "--venv" in os.sys.argv:
    import paraview.web.venv  # noqa: F401

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
from common_controllers import register_common_controllers
from paraview_controllers import register_paraview_controllers
from state_handlers import register_state_handlers
from vtk_controllers import register_vtk_handlers
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


def _debug_view(message, **values):
    """Emit a compact debug trace for RemoteLocal view lifecycle."""
    if not (BACKEND == "paraview" and args.dev):
        return
    payload = " ".join(f"{key}={values[key]!r}" for key in sorted(values))
    if payload:
        print(f"[view-debug] {message} {payload}", flush=True)
    else:
        print(f"[view-debug] {message}", flush=True)


def _is_paraview_backend():
    return BACKEND == "paraview"


def _is_vtk_backend():
    return BACKEND == "vtk"


def _call_view_update(*args, **kwargs):
    if hasattr(ctrl, "view_update"):
        _debug_view(
            "view.update",
            mode=state.mainViewMode,
            args=args,
            kwargs=kwargs,
            edit_session_active=state.edit_session_active,
        )
        return ctrl.view_update(*args, **kwargs)
    return None


def _call_view_update_geometry(*args, **kwargs):
    if hasattr(ctrl, "view_update_geometry"):
        _debug_view(
            "view.update_geometry",
            mode=state.mainViewMode,
            args=args,
            kwargs=kwargs,
            edit_session_active=state.edit_session_active,
        )
        return ctrl.view_update_geometry(*args, **kwargs)
    return None


def _call_view_update_image(*args, **kwargs):
    if hasattr(ctrl, "view_update_image"):
        _debug_view(
            "view.update_image",
            mode=state.mainViewMode,
            args=args,
            kwargs=kwargs,
            edit_session_active=state.edit_session_active,
        )
        return ctrl.view_update_image(*args, **kwargs)
    return None


def _call_view_set_local_rendering(*args, **kwargs):
    if hasattr(ctrl, "view_set_local_rendering"):
        _debug_view(
            "view.set_local_rendering",
            mode_before=state.mainViewMode,
            args=args,
            kwargs=kwargs,
            edit_session_active=state.edit_session_active,
        )
        result = ctrl.view_set_local_rendering(*args, **kwargs)
        _debug_view("view.set_local_rendering.done", mode_after=state.mainViewMode)
        return result
    return None


def _call_view_set_remote_rendering(*args, **kwargs):
    if hasattr(ctrl, "view_set_remote_rendering"):
        _debug_view(
            "view.set_remote_rendering",
            mode_before=state.mainViewMode,
            args=args,
            kwargs=kwargs,
            edit_session_active=state.edit_session_active,
        )
        result = ctrl.view_set_remote_rendering(*args, **kwargs)
        _debug_view("view.set_remote_rendering.done", mode_after=state.mainViewMode)
        return result
    return None


def _refresh_local_view(reset_camera=False):
    """Force the RemoteLocal view to rebuild its local scene."""
    if not _is_paraview_backend():
        return

    was_local = state.mainViewMode == "local"
    _debug_view(
        "view.refresh_local.start",
        mode_before=state.mainViewMode,
        reset_camera=reset_camera,
        was_local=was_local,
    )
    if was_local:
        _call_view_set_remote_rendering(True)
        _call_view_update(reset_camera=reset_camera)
    _call_view_update_geometry(reset_camera=reset_camera)
    _call_view_set_local_rendering(True)
    _call_view_update_geometry(reset_camera=reset_camera)
    _call_view_update(reset_camera=reset_camera)
    _debug_view("view.refresh_local.end", mode_after=state.mainViewMode)

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
state.edit_selection_status = ""
state.edit_selection_status_type = "info"
state.edit_selection_event = ""
state.edit_picking_modes = []
state.edit_interactor_events = []
# Initialize with valid actions to prevent "this.interactor[l] is not a function"
state.edit_interactor_settings = [
    {"button": 1, "action": "Rotate"},
    {"button": 2, "action": "Pan"},
    {"button": 3, "action": "Zoom", "scrollEnabled": True},
]
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
state.selection_behavior = "touch"
state.selection_behavior_options = [
    {"text": "Touch", "value": "touch"},
    {"text": "Contained", "value": "inside"},
]
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
    if not _is_vtk_backend():
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
    if not _is_vtk_backend():
        return

    if edit_target == BOUNDARY:
        if _edit.merged_bnd_actor:
            _edit.merged_bnd_actor.SetVisibility(1)
            apply_representation(None, _edit.merged_bnd_actor, state.representation)
        if _edit.merged_bnd_dataset is not None and _edit.merged_bnd_mapper is not None:
            lut, _ = apply_categorical_coloring(
                _edit.merged_bnd_mapper, _edit.merged_bnd_dataset, MATERIAL_ID_ARRAY
            )
            if lut is not None:
                _scalar_bars.set_bar(SCALAR_BAR_BOUNDARY, lut, "Boundary ID")
        if _viz:
            _viz.vol_mapper.ScalarVisibilityOff()
            _viz.vol_actor.GetProperty().SetColor(0.7, 0.7, 0.7)
            apply_representation(_viz.vol_actor, None, state.representation)
        _scalar_bars.remove_bar(SCALAR_BAR_ACTIVE_ARRAY)
    else:  # VOLUME
        if _edit.merged_bnd_actor:
            _edit.merged_bnd_actor.SetVisibility(0)
        _scalar_bars.remove_bar(SCALAR_BAR_BOUNDARY)
        if _edit.vol_dataset is None or _viz is None:
            return
        
        # Ensure volume actor has correct representation and color is reset by apply_coloring later
        apply_representation(_viz.vol_actor, None, state.representation)

        lut, _ = apply_categorical_coloring(
            _viz.vol_mapper, _edit.vol_dataset, MATERIAL_ID_ARRAY
        )
        if lut is None:
            return
        _viz.vol_dataset.Modified()
        _scalar_bars.set_bar(SCALAR_BAR_ACTIVE_ARRAY, lut, "Material ID")


def _render_and_push():
    """Render the active backend and push the updated view to the client."""
    if _is_paraview_backend():
        _pv_backend.render()
    else:
        renderWindow.Render()
    _call_view_update()


def _apply_vtk_representation_to_scene(representation):
    """Apply the chosen representation to the active VTK scene actors."""
    if _viz is not None:
        apply_representation(_viz.vol_actor, _viz.bnd_actor, representation)
    if _edit.merged_bnd_actor:
        apply_representation(None, _edit.merged_bnd_actor, representation)
    if _edit.vol_selection_actor:
        apply_representation(None, _edit.vol_selection_actor, representation)
    if _edit.bnd_selection_actor:
        apply_representation(None, _edit.bnd_selection_actor, representation)


def _apply_active_representation(representation):
    """Apply the current representation using the active backend."""
    if _is_paraview_backend():
        if _pv_backend.display is not None:
            _pv_backend.apply_representation(representation)
            _update_paraview_ui_state()
            _call_view_update()
        return

    _apply_vtk_representation_to_scene(representation)
    _render_and_push()


def _apply_vtk_coloring(selected_array):
    """Apply coloring to the active VTK scene."""
    global _active_lut

    if _viz is None:
        return

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


def _apply_paraview_coloring(selected_array):
    """Apply coloring to the active ParaView pipeline item."""
    if selected_array and _pv_backend.source is not None:
        _pv_backend.apply_coloring(selected_array)
        _update_paraview_ui_state()
        _call_view_update()


def _load_file_with_vtk_backend(selected_file):
    """Load a dataset through the VTK backend and refresh derived state."""
    global _viz, _active_lut

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

    setup_edit_state(_edit, _viz, renderer)

    state.available_arrays = arrays
    state.selected_array = default_array
    state.has_boundary = _viz.bnd_actor is not None or _edit.merged_bnd_dataset is not None
    state.error_message = ""
    state.selection_count = 0
    state.save_status = ""

    _render_and_push()


def _load_file_with_paraview_backend(selected_file):
    """Load a dataset through the ParaView backend and refresh derived state."""
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


def _reset_vtk_camera():
    """Reset the VTK camera and push the updated render."""
    if renderer is None or renderWindow is None:
        return
    renderer.ResetCamera()
    _render_and_push()


def _reset_vtk_view():
    """Restore a canonical view using the VTK renderer."""
    if renderer is None or renderWindow is None:
        return

    camera = renderer.GetActiveCamera()
    bounds = renderer.ComputeVisiblePropBounds()
    if bounds and bounds[0] <= bounds[1]:
        xmin, xmax, ymin, ymax, zmin, zmax = bounds
        center = (
            0.5 * (xmin + xmax),
            0.5 * (ymin + ymax),
            0.5 * (zmin + zmax),
        )
        span_x = max(abs(xmax - xmin), 1e-6)
        span_y = max(abs(ymax - ymin), 1e-6)
        span_z = max(abs(zmax - zmin), 1e-6)
        distance = max(span_x, span_y, span_z) * 2.5
        camera.SetFocalPoint(*center)
        camera.SetPosition(center[0], center[1], center[2] + distance)
        camera.SetViewUp(0.0, 1.0, 0.0)
    renderer.ResetCamera()
    renderer.ResetCameraClippingRange()
    _render_and_push()


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

    if not _is_paraview_backend() or _pv_output_window is None:
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
            output_path += _pv_backend.default_output_extension()
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        _pv_backend.save_active_data(output_path)
        saved_kind = "pipeline result"

    _refresh_available_files()
    relative_output = os.path.relpath(output_path, data_directory)
    state.save_filename = relative_output
    state.save_status = f"Saved {saved_kind} to {relative_output}"
    state.save_status_type = "success"
    return output_path


def _sync_edit_session_state():
    """Synchronize Trame state from the current edit session."""
    state.edit_session_active = _edit_session.active
    state.edit_session_label = _edit_session.source_label or ""
    state.edit_geometry_mode = _edit_session.geometry_mode
    state.edit_field_name = _edit_session.field_name
    state.edit_expression = _edit_session.expression
    state.edit_default_value = _edit_session.default_value
    state.edit_available_variables = _edit_session.available_cell_variables()
    state.selection_count = _edit_session.selected_count()
    
    # Enable 'mesh' and 'box' for interactive selection in ParaView
    state.edit_picking_modes = ["click", "mesh", "box"] if _edit_session.active and state.pick_mode else []
    # trame-vtk expects interactor method suffixes such as "EndAnimation",
    # not vtk.js event names like "EndAnimationEvent".
    state.edit_interactor_events = ["EndAnimation"]

    if _edit_session.active and state.pick_mode:
        # Map button 1 to Pan instead of Rotate on the client as well,
        # and ensure a full set of actions to avoid "interactor[l] is not a function".
        state.edit_interactor_settings = [
            {"button": 1, "action": "Pan"}, 
            {"button": 2, "action": "Pan"},
            {"button": 3, "action": "Zoom", "scrollEnabled": True},
        ]
    else:
        state.edit_interactor_settings = [
            {"button": 1, "action": "Rotate"},
            {"button": 2, "action": "Pan"},
            {"button": 3, "action": "Zoom", "scrollEnabled": True},
        ]


def _normalize_edit_selection_ids(event):
    """Extract picked cell IDs or screen coordinates from picking payloads."""
    if event is None:
        return []

    if isinstance(event, dict):
        # Local vtk.js picking
        if isinstance(event.get("compositeID"), int):
            return [event["compositeID"]]
        if isinstance(event.get("selection"), list):
            result = []
            for item in event["selection"]:
                if isinstance(item, dict) and isinstance(item.get("compositeID"), int):
                    result.append(item["compositeID"])
            if result:
                return result
        
        # Remote picking (return coordinates from position object)
        pos = event.get("position")
        if isinstance(pos, dict) and "x" in pos and "y" in pos:
            return [("coords", pos["x"], pos["y"])]
        
        # Direct x, y at root
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


def _extract_pointer_position(event):
    """Extract display-space x/y coordinates from an interactor event payload."""
    if not isinstance(event, dict):
        return None

    position = event.get("position")
    if isinstance(position, dict):
        x = position.get("x")
        y = position.get("y")
        if x is not None and y is not None:
            return x, y

    x = event.get("x")
    y = event.get("y")
    if x is not None and y is not None:
        return x, y

    return None


def _sync_paraview_edit_selection_overlay():
    """Update the transient selection highlight for the active ParaView edit session."""
    if not _is_paraview_backend():
        return

    if not _edit_session.active:
        _pv_backend.clear_active_selection()
        _pv_backend.clear_edit_selection_overlay()
        _call_view_update()
        return

    overlay_dataset = _edit_session.build_selected_volume_dataset()
    if overlay_dataset is None:
        _pv_backend.clear_active_selection()
        _pv_backend.clear_edit_selection_overlay()
        _call_view_update()
        return

    _pv_backend.update_edit_selection_overlay(overlay_dataset)
    _call_view_update()


def _summarize_edit_event(event):
    """Return a compact, UI-friendly summary of a picking/selection event."""
    if event is None:
        return "No event payload"

    if isinstance(event, dict):
        summary = {}
        # Include a few more potential keys for debugging
        for key in ("mode", "remoteId", "representationId", "view", "x", "y", "z", "compositeID", "position", "pany", "panx"):
            if key in event:
                summary[key] = event[key]
        
        normalized_ids = _normalize_edit_selection_ids(event)
        if normalized_ids:
            if isinstance(normalized_ids[0], tuple) and normalized_ids[0][0] == "coords":
                summary["resolved_coords"] = normalized_ids[0][1:]
            else:
                summary["selection_count"] = len(normalized_ids)
                summary["sample_ids"] = normalized_ids[:8]
        
        # Add full keys for debugging
        summary["all_keys"] = list(event.keys())
        return json.dumps(summary, indent=2, default=str)

    if isinstance(event, (list, tuple)):
        return json.dumps(event, indent=2, default=str)

    return str(event)


def _update_paraview_ui_state():
    """Synchronize Trame state with the active ParaView source metadata."""
    if not _is_paraview_backend():
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
    _sync_edit_session_state()


register_paraview_controllers(
    ctrl,
    state,
    is_paraview_backend=_is_paraview_backend,
    pv_backend=_pv_backend,
    edit_session=_edit_session,
    refresh_runtime_message=_refresh_paraview_runtime_message,
    update_paraview_ui_state=_update_paraview_ui_state,
    render_and_push=_render_and_push,
    save_paraview_output=_save_paraview_output,
    debug_view=_debug_view,
    call_view_update_geometry=_call_view_update_geometry,
    call_view_set_remote_rendering=_call_view_set_remote_rendering,
    call_view_update=_call_view_update,
    sync_edit_session_state=_sync_edit_session_state,
    sync_paraview_edit_selection_overlay=_sync_paraview_edit_selection_overlay,
    summarize_edit_event=_summarize_edit_event,
    normalize_edit_selection_ids=_normalize_edit_selection_ids,
)

register_vtk_handlers(
    state,
    ctrl,
    is_vtk_backend=_is_vtk_backend,
    viz_getter=lambda: _viz,
    edit_state=_edit,
    pick_interactor=_pick_interactor,
    data_directory=data_directory,
    apply_edit_coloring=_apply_edit_coloring,
    render_and_push=_render_and_push,
    update_selection_actor=update_selection_actor,
    assign_id_to_selection=assign_id_to_selection,
    save_as_vtu=save_as_vtu,
    refresh_available_files=_refresh_available_files,
    update_scalar_bars=_update_scalar_bars,
    active_lut_getter=lambda: _active_lut,
    apply_vtk_coloring=_apply_vtk_coloring,
    apply_vtk_representation_to_scene=_apply_vtk_representation_to_scene,
)

register_state_handlers(
    state,
    is_paraview_backend=_is_paraview_backend,
    load_file_with_paraview_backend=_load_file_with_paraview_backend,
    load_file_with_vtk_backend=_load_file_with_vtk_backend,
    apply_paraview_coloring=_apply_paraview_coloring,
    apply_vtk_coloring=_apply_vtk_coloring,
    apply_active_representation=_apply_active_representation,
    pv_backend=_pv_backend,
    update_paraview_ui_state=_update_paraview_ui_state,
    render_and_push=_render_and_push,
    sync_edit_session_state=_sync_edit_session_state,
    interaction_quality_presets=INTERACTION_QUALITY_PRESETS,
)

register_common_controllers(
    ctrl,
    state,
    is_paraview_backend=_is_paraview_backend,
    pv_backend=_pv_backend,
    call_view_update=_call_view_update,
    reset_vtk_camera=_reset_vtk_camera,
    reset_vtk_view=_reset_vtk_view,
    persist_uploaded_file=_persist_uploaded_file,
    refresh_available_files=_refresh_available_files,
)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    server.start()
