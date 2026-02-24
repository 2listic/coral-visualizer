import argparse
import os
from trame.app import get_server

from file_utils import get_vtk_files_from_data_folder, CURRENT_DIRECTORY
from vtk_pipeline import (
    build_visualization,
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
_current_actor = None
_current_mapper = None
_current_dataset = None

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


# -----------------------------------------------------------------------------
# Build UI
# -----------------------------------------------------------------------------

build_ui(server, renderWindow)


# -----------------------------------------------------------------------------
# State Callbacks
# -----------------------------------------------------------------------------


@state.change("selected_file")
def on_file_change(selected_file, **kwargs):
    """Reload pipeline and reset coloring/representation when file changes."""
    global _current_actor, _current_mapper, _current_dataset

    if selected_file and os.path.exists(selected_file):
        try:
            print(f"\nLoading file: {selected_file}")
            _current_actor, _current_mapper, _current_dataset = build_visualization(
                selected_file, renderer
            )
            arrays = get_available_arrays(_current_dataset)
            default_array = arrays[1]["value"] if len(arrays) > 1 else "__solid__"

            apply_coloring(
                _current_actor, _current_mapper, _current_dataset, default_array
            )
            apply_representation(_current_actor, state.representation)

            state.available_arrays = arrays
            state.selected_array = default_array
            state.error_message = ""

            renderWindow.Render()
            ctrl.view_update()
        except Exception as e:
            state.error_message = f"Error loading file: {str(e)}"
            print(f"Error: {e}")


@state.change("selected_array")
def on_array_change(selected_array, **kwargs):
    """Update coloring when the user picks a different array."""
    if _current_actor is not None:
        apply_coloring(
            _current_actor, _current_mapper, _current_dataset, selected_array
        )
        renderWindow.Render()
        ctrl.view_update()


@state.change("representation")
def on_representation_change(representation, **kwargs):
    """Update actor representation when the user picks a different mode."""
    if _current_actor is not None:
        apply_representation(_current_actor, representation)
        renderWindow.Render()
        ctrl.view_update()


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    server.start()
