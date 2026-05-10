"""Backend rendering and runtime construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vtkmodules.vtkCommonCore import vtkOutputWindow, vtkStringOutputWindow

from edit_session import EditSession
from paraview_backend import ParaViewBackend

if TYPE_CHECKING:
    from app_config import AppConfig


@dataclass
class RuntimeContext:
    """Pre-Trame application objects, created before the server is available."""

    data_directory: str
    render_target: object
    edit_session: EditSession
    pv_backend: ParaViewBackend
    pv_output_window: vtkStringOutputWindow


def create_runtime_context(config: AppConfig) -> RuntimeContext:
    """Create ParaView rendering objects before Trame wiring."""
    pv_output_window = vtkStringOutputWindow()
    vtkOutputWindow.SetInstance(pv_output_window)
    pv_backend = ParaViewBackend(
        data_directory=config.data_directory,
        show_experimental_filters=config.show_experimental_filters,
    )
    return RuntimeContext(
        data_directory=config.data_directory,
        render_target=pv_backend.initialize_view(),
        edit_session=EditSession(),
        pv_backend=pv_backend,
        pv_output_window=pv_output_window,
    )
