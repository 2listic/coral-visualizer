import argparse
import os
from trame.app import get_server

from file_utils import get_vtk_files_from_data_folder, CURRENT_DIRECTORY
from vtk_pipeline import (
    build_visualization,
    build_scalar_bar,
    get_available_arrays,
    apply_coloring,
    apply_representation,
    create_vtk_rendering_context,
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
_active_coloring_bar = None  # scalar bar tracking the current "Color by" selection

DEFAULT_REPRESENTATION = "Surface with Edges"

available_files = get_vtk_files_from_data_folder()
initial_file = (
    args.file
    if args.file and os.path.exists(args.file)
    else (available_files[0]["value"] if available_files else None)
)
_initial_arrays = [{"text": "Solid Color", "value": "__solid__"}]
_initial_array = "__solid__"


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
state.show_boundary = True
state.show_scalar_bars = True
state.has_boundary = False


# -----------------------------------------------------------------------------
# Build UI
# -----------------------------------------------------------------------------

build_ui(server, renderWindow)


# -----------------------------------------------------------------------------
# Private helpers
# -----------------------------------------------------------------------------


def _array_label(array_value):
    """Human-readable label for a Color by array value."""
    if array_value == "cell:MaterialID":
        return "Material ID"
    if ":" in array_value:
        return array_value.split(":", 1)[1]
    return array_value


def _update_active_coloring_bar(active_lut, array_value):
    """Replace the dynamic scalar bar that tracks the active Color by selection."""
    global _active_coloring_bar
    if _active_coloring_bar is not None:
        renderer.RemoveActor(_active_coloring_bar)
        _active_coloring_bar = None
    if active_lut is not None:
        _active_coloring_bar = build_scalar_bar(
            active_lut,
            _array_label(array_value),
            position=(0.82, 0.05),
            width=0.08,
            height=0.35,
        )
        renderer.AddActor(_active_coloring_bar)
        _active_coloring_bar.SetVisibility(1 if state.show_scalar_bars else 0)


def _apply_boundary_visibility(show):
    if _viz and _viz.bnd_actor:
        _viz.bnd_actor.SetVisibility(1 if show else 0)
    if _viz and _viz.bnd_scalar_bar:
        _viz.bnd_scalar_bar.SetVisibility(1 if show else 0)


def _apply_scalar_bar_visibility(show):
    bars = [_active_coloring_bar]
    if _viz:
        bars.append(_viz.bnd_scalar_bar)
    for bar in bars:
        if bar is not None:
            bar.SetVisibility(1 if show else 0)


# -----------------------------------------------------------------------------
# State Callbacks
# -----------------------------------------------------------------------------


@state.change("selected_file")
def on_file_change(selected_file, **kwargs):
    """Reload pipeline and reset coloring/representation when file changes."""
    global _viz

    if selected_file and os.path.exists(selected_file):
        try:
            print(f"\nLoading file: {selected_file}")
            _viz = build_visualization(selected_file, renderer)

            arrays = get_available_arrays(_viz.full_dataset)
            default_array = next(
                (a["value"] for a in arrays if a["value"] == "cell:MaterialID"),
                arrays[1]["value"] if len(arrays) > 1 else "__solid__",
            )

            active_lut = apply_coloring(
                _viz.vol_actor,
                _viz.vol_mapper,
                _viz.vol_dataset,
                default_array,
                _viz.vol_lut,
            )
            apply_representation(_viz.vol_actor, _viz.bnd_actor, state.representation)
            _update_active_coloring_bar(active_lut, default_array)
            _apply_boundary_visibility(state.show_boundary)
            _apply_scalar_bar_visibility(state.show_scalar_bars)

            state.available_arrays = arrays
            state.selected_array = default_array
            state.has_boundary = _viz.bnd_actor is not None
            state.error_message = ""

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
    if _viz is not None:
        active_lut = apply_coloring(
            _viz.vol_actor,
            _viz.vol_mapper,
            _viz.vol_dataset,
            selected_array,
            _viz.vol_lut,
        )
        _update_active_coloring_bar(active_lut, selected_array)
        renderWindow.Render()
        ctrl.view_update()


@state.change("representation")
def on_representation_change(representation, **kwargs):
    """Update actor representation when the user picks a different mode."""
    if _viz is not None:
        apply_representation(_viz.vol_actor, _viz.bnd_actor, representation)
        renderWindow.Render()
        ctrl.view_update()


@state.change("show_boundary")
def on_show_boundary_change(show_boundary, **kwargs):
    """Show or hide the boundary cells actor and its scalar bar."""
    _apply_boundary_visibility(show_boundary)
    if _viz is not None:
        renderWindow.Render()
        ctrl.view_update()


@state.change("show_scalar_bars")
def on_show_scalar_bars_change(show_scalar_bars, **kwargs):
    """Show or hide all scalar bar legends."""
    _apply_scalar_bar_visibility(show_scalar_bars)
    if _viz is not None:
        renderWindow.Render()
        ctrl.view_update()


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    server.start()
