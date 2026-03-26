import argparse
import os
from trame.app import get_server

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
from file_utils import get_vtk_files_from_data_folder, CURRENT_DIRECTORY
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
    extract_all_boundary_subcells,
    build_merged_boundary_dataset,
    build_adjacency_graph,
    compute_cell_normals,
    create_boundary_actor,
    create_selection_actor,
    create_cell_picker,
    assign_id_to_selection,
    update_selection_actor,
    save_as_vtu,
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
# Parse known args and let trame handle the rest (--port, --host, --debug, etc.)
args, unknown = parser.parse_known_args()


# -----------------------------------------------------------------------------
# VTK Setup
# -----------------------------------------------------------------------------

renderer, renderWindow, renderWindowInteractor = create_vtk_rendering_context()

# Module-level pipeline references (updated whenever a file is loaded)
_viz = None  # VisualizationResult | None
_active_lut = None  # LUT currently used for the "Color by" coloring

_scalar_bars = ScalarBarManager(renderer)

# Boundary editing state
_edit = BoundaryEditState()

DEFAULT_REPRESENTATION = REPR_SURFACE_EDGES

available_files = get_vtk_files_from_data_folder()
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

build_ui(server, renderWindow)

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


def _setup_edit_infrastructure():
    """Extract boundary cells and create edit actors after a file is loaded."""
    _edit.clear()
    if _viz is None:
        return

    _edit.full_dataset = _viz.full_dataset

    vol_indices, bnd_indices, extracted_subcells = extract_all_boundary_subcells(
        _viz.full_dataset
    )
    _edit.vol_cell_indices = vol_indices
    _edit.file_bnd_cell_indices = bnd_indices

    if not extracted_subcells:
        print("  No exterior boundary sub-cells found for editing.")
        return

    print(f"  Extracted {len(extracted_subcells)} exterior boundary sub-cells")
    print(f"  ({len(bnd_indices)} were in the file)")

    _edit.merged_bnd_dataset = build_merged_boundary_dataset(
        _viz.full_dataset, bnd_indices, extracted_subcells
    )
    _edit.merged_bnd_actor, _edit.merged_bnd_mapper = create_boundary_actor(
        _edit.merged_bnd_dataset
    )
    _edit.bnd_selection_actor, _edit.bnd_selection_mapper = create_selection_actor()
    _edit.bnd_picker = create_cell_picker(_edit.merged_bnd_actor)
    _edit.adjacency = build_adjacency_graph(_edit.merged_bnd_dataset)
    _edit.cell_normals = compute_cell_normals(_edit.merged_bnd_dataset)

    renderer.AddActor(_edit.merged_bnd_actor)
    renderer.AddActor(_edit.bnd_selection_actor)

    # Volume cell editing infrastructure
    _edit.vol_dataset = _viz.vol_dataset
    _edit.vol_picker = create_cell_picker(_viz.vol_actor)
    _edit.vol_selection_actor, _edit.vol_selection_mapper = create_selection_actor()
    renderer.AddActor(_edit.vol_selection_actor)


def _apply_edit_coloring(edit_target):
    """Apply coloring and actor visibility for the given edit target.

    BOUNDARY: shows the boundary overlay with categorical MaterialID coloring,
      sets the volume actor to solid gray.
    VOLUME: hides the boundary overlay, applies categorical MaterialID coloring
      to the volume actor.
    """
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
            _setup_edit_infrastructure()

            state.available_arrays = arrays
            state.selected_array = default_array
            state.has_boundary = (
                _viz.bnd_actor is not None or _edit.merged_bnd_dataset is not None
            )
            state.error_message = ""
            state.selection_count = 0
            state.save_status = ""

            renderWindow.Render()
            ctrl.view_update()
        except Exception as e:
            state.error_message = f"Error loading file: {str(e)}"
            print(f"Error: {e}")
            import traceback

            traceback.print_exc()


@state.change("selected_array")
def on_array_change(selected_array, **kwargs):
    """Update coloring when the user picks a different array."""
    global _active_lut
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
        renderWindow.Render()
        ctrl.view_update()


@state.change("representation")
def on_representation_change(representation, **kwargs):
    """Update actor representation when the user picks a different mode."""
    if _viz is not None:
        apply_representation(_viz.vol_actor, _viz.bnd_actor, representation)
        renderWindow.Render()
        ctrl.view_update()


@state.change("edit_mode")
def on_edit_mode_change(edit_mode, **kwargs):
    """Toggle between view mode and boundary edit mode."""
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

    renderWindow.Render()
    ctrl.view_update()


@state.change("edit_target")
def on_edit_target_change(edit_target, **kwargs):
    """Switch between boundary and volume edit targets, clearing the selection."""
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

    renderWindow.Render()
    ctrl.view_update()


# -----------------------------------------------------------------------------
# Controller methods (called from UI buttons)
# -----------------------------------------------------------------------------


@ctrl.add("clear_selection")
def clear_selection():
    """Clear all selected cells (boundary or volume depending on edit_target)."""
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
    renderWindow.Render()
    ctrl.view_update()


@ctrl.add("select_all")
def select_all():
    """Select all cells (boundary or volume depending on edit_target)."""
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
            renderWindow.Render()
            ctrl.view_update()
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
            renderWindow.Render()
            ctrl.view_update()


@ctrl.add("assign_id")
def assign_id():
    """Assign the chosen ID value to all selected cells (boundary or volume)."""
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
    renderWindow.Render()
    ctrl.view_update()


@ctrl.add("save_vtu")
def save_vtu():
    """Save the modified mesh as .vtu."""
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
        output_path = os.path.join(CURRENT_DIRECTORY, "data", filename)

        save_as_vtu(_edit, output_path)

        state.save_status = f"Saved to data/{filename}"
        state.save_status_type = "success"

        # Refresh file list so the new file appears in the dropdown
        state.available_files = get_vtk_files_from_data_folder()
        print(f"  Saved to {output_path}")
    except Exception as e:
        state.save_status = f"Error: {str(e)}"
        state.save_status_type = "error"
        print(f"Save error: {e}")
        import traceback

        traceback.print_exc()


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    server.start()
