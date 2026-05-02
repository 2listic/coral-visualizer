from ui import build_ui
from mesh_edit import (
    assign_id_to_selection,
    update_selection_actor,
    save_as_vtu,
)
from view_controls import ViewControllerProxy
from state_setup import initialize_state, resolve_initial_file
from runtime_setup import attach_runtime_services, create_runtime_context
from paraview_backend import is_paraview_available
from handler_registration import EditOperations, register_app_handlers
from file_operations import FileOperationService
from file_utils import get_vtk_files_from_data_folder
from constants import (
    BOUNDARY,
    INTERACTION_QUALITY_PRESETS,
)
from trame.app import get_server
from app_config import configure_app, enable_paraview_web_venv_if_requested

enable_paraview_web_venv_if_requested()


config = configure_app(paraview_available=is_paraview_available())
BACKEND = config.backend
data_directory = config.data_directory


# -----------------------------------------------------------------------------
# Rendering setup
# -----------------------------------------------------------------------------

runtime = create_runtime_context(config)

available_files = get_vtk_files_from_data_folder(data_directory)
initial_file = resolve_initial_file(config.file, available_files)


# -----------------------------------------------------------------------------
# Trame Server Setup
# -----------------------------------------------------------------------------

server = get_server(client_type="vue2")
state = server.state
ctrl = server.controller
view_controls = ViewControllerProxy(
    ctrl,
    state,
    backend=BACKEND,
    devtools_enabled=config.devtools_enabled,
)

initialize_state(
    state,
    available_files=available_files,
    initial_file=initial_file,
    backend=BACKEND,
    backend_message=config.backend_message,
    pv_backend=runtime.pv_backend,
)


# -----------------------------------------------------------------------------
# Build UI
# -----------------------------------------------------------------------------

build_ui(server, runtime.render_target, BACKEND)

attach_runtime_services(runtime, state=state, ctrl=ctrl,
                        view_controls=view_controls)
file_operations = FileOperationService(
    state=state,
    data_directory=data_directory,
    pv_backend=runtime.pv_backend,
    edit_session=runtime.edit_session,
)
file_operations.refresh_available_state_files()
register_app_handlers(
    ctrl=ctrl,
    state=state,
    runtime=runtime,
    edit_operations=EditOperations(
        update_selection_actor=update_selection_actor,
        assign_id_to_selection=assign_id_to_selection,
        save_as_vtu=save_as_vtu,
    ),
    file_operations=file_operations,
    interaction_quality_presets=INTERACTION_QUALITY_PRESETS,
    view_controls=view_controls,
)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    server.start()
