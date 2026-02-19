import argparse
import os
from trame.app import get_server

from file_utils import get_vtk_files_from_data_folder, save_tagged_mesh
from vtk_pipeline import (
    build_visualization,
    create_vtk_rendering_context,
    handle_left_click,
    _pipeline_state,
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

# Build initial visualization if file passed as arg or if an available file exists
available_files = get_vtk_files_from_data_folder()
initial_file = (
    args.file
    if args.file and os.path.exists(args.file)
    else (available_files[0]["value"] if available_files else None)
)
if initial_file:
    build_visualization(initial_file, renderer)
    renderWindow.Render()


# -----------------------------------------------------------------------------
# Trame Server Setup
# -----------------------------------------------------------------------------

server = get_server(client_type="vue2")
state = server.state
ctrl = server.controller

# Initialize state
state.available_files = available_files
state.selected_file = initial_file
state.error_message = ""
state.tag_mode = False
state.active_tag_id = 1
state.save_status = ""

# Give the picker callback access to Trame state and controller
_pipeline_state["state"] = state
_pipeline_state["ctrl"] = ctrl

# Register the cell-pick observer once for the lifetime of the app.
# Priority 1.0 fires before the interactor style's default 0.0 priority.
renderWindowInteractor.AddObserver("LeftButtonPressEvent", handle_left_click, 1.0)


# -----------------------------------------------------------------------------
# Save callback — defined before build_ui so ctrl.save_tags is set when the
# UI is constructed and the button's click handler is bound.
# -----------------------------------------------------------------------------

def on_save_tags():
    """Write the current mesh with its BoundaryID CellData array to a new file."""
    dataset = _pipeline_state.get("dataset")
    if dataset is None:
        state.save_status = "Error: no mesh loaded"
        return
    if not state.selected_file:
        state.save_status = "Error: no file selected"
        return
    try:
        output_path = save_tagged_mesh(dataset, state.selected_file)
        state.save_status = f"Saved: {os.path.basename(output_path)}"
    except Exception as e:
        state.save_status = f"Error: {e}"
        print(f"Save error: {e}")


ctrl.save_tags = on_save_tags


# -----------------------------------------------------------------------------
# Build UI
# -----------------------------------------------------------------------------

build_ui(server, renderWindow)


# -----------------------------------------------------------------------------
# State Callbacks
# -----------------------------------------------------------------------------


@state.change("selected_file")
def on_file_change(selected_file, **_kwargs):
    """Automatically load the selected file when dropdown changes."""
    if selected_file and os.path.exists(selected_file):
        try:
            print(f"\nLoading file: {selected_file}")
            build_visualization(selected_file, renderer)
            # Sync tag actor visibility in case tag mode is currently active
            tag_actor = _pipeline_state.get("tag_actor")
            if tag_actor is not None:
                tag_actor.VisibilityOn() if state.tag_mode else tag_actor.VisibilityOff()
            state.save_status = ""
            renderWindow.Render()
            ctrl.view_update()
            state.error_message = ""
        except Exception as e:
            state.error_message = f"Error loading file: {str(e)}"
            print(f"Error: {e}")


@state.change("tag_mode")
def on_tag_mode_change(tag_mode, **kwargs):
    """Swap interactor style and toggle tag actor visibility without rebuilding the pipeline."""
    style = _pipeline_state["style_tag"] if tag_mode else _pipeline_state["style_navigate"]
    if style is not None:
        renderWindowInteractor.SetInteractorStyle(style)
    tag_actor = _pipeline_state.get("tag_actor")
    if tag_actor is not None:
        tag_actor.VisibilityOn() if tag_mode else tag_actor.VisibilityOff()
    renderWindow.Render()
    ctrl.view_update()


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    server.start()
