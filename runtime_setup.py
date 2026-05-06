"""Backend rendering and runtime construction."""

from dataclasses import dataclass

from vtkmodules.vtkCommonCore import vtkOutputWindow, vtkStringOutputWindow

from edit_session import EditSession
from interactor import PickInteractorManager
from mesh_edit import BoundaryEditState
from paraview_backend import ParaViewBackend
from paraview_runtime import ParaViewRuntime
from scalar_bars import ScalarBarManager
from vtk_pipeline import create_vtk_rendering_context
from vtk_runtime import VtkRuntime


@dataclass
class RuntimeContext:
    """Mutable application runtime objects for the selected rendering backend."""

    backend: str
    data_directory: str
    render_target: object
    edit_session: EditSession
    edit_state: BoundaryEditState
    pv_backend: ParaViewBackend | None = None
    pv_output_window: vtkStringOutputWindow | None = None
    renderer: object | None = None
    render_window: object | None = None
    render_window_interactor: object | None = None
    scalar_bars: object | None = None
    pick_interactor: object | None = None
    vtk_runtime: VtkRuntime | None = None
    paraview_runtime: ParaViewRuntime | None = None


def create_runtime_context(config):
    """Create backend-specific rendering objects before Trame wiring."""
    edit_session = EditSession()
    edit_state = BoundaryEditState()

    if config.backend == "paraview":
        pv_output_window = vtkStringOutputWindow()
        vtkOutputWindow.SetInstance(pv_output_window)
        pv_backend = ParaViewBackend(
            data_directory=config.data_directory,
            show_experimental_filters=config.show_experimental_filters,
        )
        return RuntimeContext(
            backend=config.backend,
            data_directory=config.data_directory,
            render_target=pv_backend.initialize_view(),
            edit_session=edit_session,
            edit_state=edit_state,
            pv_backend=pv_backend,
            pv_output_window=pv_output_window,
        )

    renderer, render_window, render_window_interactor = create_vtk_rendering_context()
    return RuntimeContext(
        backend=config.backend,
        data_directory=config.data_directory,
        render_target=render_window,
        edit_session=edit_session,
        edit_state=edit_state,
        renderer=renderer,
        render_window=render_window,
        render_window_interactor=render_window_interactor,
        scalar_bars=ScalarBarManager(renderer),
    )


def attach_runtime_services(context, *, state, ctrl, view_controls):
    """Create Trame-dependent backend services after server setup."""
    if context.backend == "vtk":
        context.pick_interactor = PickInteractorManager(
            context.render_window_interactor,
            context.renderer,
            context.render_window,
            state,
            ctrl,
            context.edit_state,
        )
        context.vtk_runtime = VtkRuntime(
            state=state,
            renderer=context.renderer,
            render_window=context.render_window,
            scalar_bars=context.scalar_bars,
            edit_state=context.edit_state,
            call_view_update=view_controls.update,
        )
        return context

    context.paraview_runtime = ParaViewRuntime(
        state=state,
        pv_backend=context.pv_backend,
        edit_session=context.edit_session,
        output_window=context.pv_output_window,
        call_view_update=view_controls.update,
    )
    return context
