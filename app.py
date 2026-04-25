from app_config import configure_app, enable_paraview_web_venv_if_requested

enable_paraview_web_venv_if_requested()

from trame.app import get_server
from vtkmodules.vtkCommonCore import vtkOutputWindow, vtkStringOutputWindow

from constants import (
    BOUNDARY,
    INTERACTION_QUALITY_PRESETS,
)
from edit_session import EditSession
from file_utils import get_vtk_files_from_data_folder
from file_operations import persist_uploaded_file, refresh_available_files, save_paraview_output
from handler_registration import register_app_handlers
from paraview_runtime import ParaViewRuntime
from paraview_backend import ParaViewBackend, is_paraview_available
from state_setup import initialize_state, resolve_initial_file
from view_controls import ViewControllerProxy
from vtk_runtime import VtkRuntime
from vtk_pipeline import (
    create_vtk_rendering_context,
)
from scalar_bars import ScalarBarManager
from interactor import PickInteractorManager
from mesh_edit import (
    BoundaryEditState,
    assign_id_to_selection,
    update_selection_actor,
    save_as_vtu,
)
from ui import build_ui

config = configure_app(paraview_available=is_paraview_available())
BACKEND = config.backend
data_directory = config.data_directory


# -----------------------------------------------------------------------------
# Rendering setup
# -----------------------------------------------------------------------------

renderer = None
renderWindow = None
renderWindowInteractor = None
render_target = None

_pv_backend = None
_edit_session = EditSession()
_pv_output_window = None

if BACKEND == "paraview":
    _pv_output_window = vtkStringOutputWindow()
    vtkOutputWindow.SetInstance(_pv_output_window)
    _pv_backend = ParaViewBackend(
        data_directory=data_directory,
        show_experimental_filters=config.show_experimental_filters,
    )
    render_target = _pv_backend.initialize_view()
    _scalar_bars = None
else:
    renderer, renderWindow, renderWindowInteractor = create_vtk_rendering_context()
    render_target = renderWindow
    _scalar_bars = ScalarBarManager(renderer)

# Boundary editing state
_edit = BoundaryEditState()

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
    pv_backend=_pv_backend,
)


# -----------------------------------------------------------------------------
# Build UI
# -----------------------------------------------------------------------------

build_ui(server, render_target, BACKEND)

_pick_interactor = None
if BACKEND == "vtk":
    _pick_interactor = PickInteractorManager(
        renderWindowInteractor, renderer, renderWindow, state, ctrl, _edit
    )

_vtk_runtime = None
if BACKEND == "vtk":
    _vtk_runtime = VtkRuntime(
        state=state,
        renderer=renderer,
        render_window=renderWindow,
        scalar_bars=_scalar_bars,
        edit_state=_edit,
        call_view_update=view_controls.update,
    )

_paraview_runtime = None
if BACKEND == "paraview":
    _paraview_runtime = ParaViewRuntime(
        state=state,
        pv_backend=_pv_backend,
        edit_session=_edit_session,
        output_window=_pv_output_window,
        call_view_update=view_controls.update,
    )
register_app_handlers(
    ctrl=ctrl,
    state=state,
    backend=BACKEND,
    data_directory=data_directory,
    pv_backend=_pv_backend,
    edit_session=_edit_session,
    edit_state=_edit,
    pick_interactor=_pick_interactor,
    vtk_runtime=_vtk_runtime,
    paraview_runtime=_paraview_runtime,
    update_selection_actor=update_selection_actor,
    assign_id_to_selection=assign_id_to_selection,
    save_as_vtu=save_as_vtu,
    refresh_available_files=lambda: refresh_available_files(state, data_directory),
    persist_uploaded_file=lambda client_file: persist_uploaded_file(
        data_directory, client_file
    ),
    save_paraview_output=lambda: save_paraview_output(
        state=state,
        data_directory=data_directory,
        pv_backend=_pv_backend,
        edit_session=_edit_session,
    ),
    interaction_quality_presets=INTERACTION_QUALITY_PRESETS,
    debug_view=view_controls.debug,
    call_view_update=view_controls.update,
    call_view_update_geometry=view_controls.update_geometry,
    call_view_set_remote_rendering=view_controls.set_remote_rendering,
)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    server.start()
