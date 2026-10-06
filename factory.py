"""Application factory — wires the full stack without starting the server."""

from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from trame.app import get_server

from app_config import AppConfig, configure_app
from constants import INTERACTION_QUALITY_PRESETS
from diagnostics import set_devtools_enabled
from file_operations import FileOperationService
from file_utils import get_vtk_files_from_data_folder
from handler_registration import register_app_handlers
from paraview_runtime import ParaViewRuntime
from runtime_setup import RuntimeContext, create_runtime_context
from state_setup import initialize_state, resolve_initial_file
from trame_vtk_patches import apply_all as apply_trame_vtk_patches
from ui import build_ui
from view_controls import ViewControllerProxy

SUPPORTED_VTK_EXTENSIONS = (".pvd", ".pvtu", ".vtu", ".vtk")


@dataclass
class AppComponents:
    """All wired application objects, ready for server.start()."""

    server: Any
    state: Any
    ctrl: Any
    config: AppConfig
    runtime_context: RuntimeContext
    view_controls: ViewControllerProxy
    paraview_runtime: ParaViewRuntime
    file_operations: FileOperationService


def create_app(
    *,
    config: AppConfig | None = None,
    server: Any = None,
) -> AppComponents:
    """Wire the full application stack without starting the server.

    Pass ``config`` to bypass CLI argument parsing (required in tests).
    Pass ``server`` to reuse an existing Trame server instance.
    """
    if config is None:
        config = configure_app()
    set_devtools_enabled(config.devtools_enabled)

    # Must run before any client connects and the web protocols are registered.
    apply_trame_vtk_patches()

    runtime_context = create_runtime_context(config)
    data_directory = config.data_directory

    available_files = get_vtk_files_from_data_folder(data_directory)
    initial_file = resolve_initial_file(config.file, available_files)

    if server is None:
        server = get_server(f"app-{uuid4().hex[:8]}", client_type="vue2")
    state = server.state
    ctrl = server.controller

    view_controls = ViewControllerProxy(
        ctrl,
        state,
        devtools_enabled=config.devtools_enabled,
    )

    initialize_state(
        state,
        available_files=available_files,
        initial_file=initial_file,
        pv_backend=runtime_context.pv_backend,
    )

    build_ui(server, runtime_context.render_target)

    paraview_runtime = ParaViewRuntime(
        state=state,
        pv_backend=runtime_context.pv_backend,
        edit_session=runtime_context.edit_session,
        output_window=runtime_context.pv_output_window,
        call_view_update=view_controls.update,
    )

    file_operations = FileOperationService(
        state=state,
        data_directory=data_directory,
        pv_backend=paraview_runtime.pv_backend,
        edit_session=paraview_runtime.edit_session,
    )
    file_operations.refresh_available_state_files()

    register_app_handlers(
        ctrl=ctrl,
        state=state,
        paraview_runtime=paraview_runtime,
        file_operations=file_operations,
        interaction_quality_presets=INTERACTION_QUALITY_PRESETS,
        view_controls=view_controls,
    )

    return AppComponents(
        server=server,
        state=state,
        ctrl=ctrl,
        config=config,
        runtime_context=runtime_context,
        view_controls=view_controls,
        paraview_runtime=paraview_runtime,
        file_operations=file_operations,
    )


def make_download_handler(data_directory: str):
    """Return an aiohttp request handler that serves files from data_directory."""

    async def _handle(request):
        from aiohttp.web import Response

        file_param = request.rel_url.query.get("file", "").strip()
        if not file_param:
            return Response(status=400, text="Missing file parameter")
        data_dir_abs = os.path.realpath(data_directory)
        abs_path = (
            os.path.realpath(file_param)
            if os.path.isabs(file_param)
            else os.path.realpath(os.path.join(data_dir_abs, file_param))
        )
        if not abs_path.startswith(data_dir_abs + os.sep):
            return Response(status=403, text="Forbidden")
        if not os.path.isfile(abs_path):
            return Response(status=404, text="Not found")
        filename = os.path.basename(abs_path)
        mime = mimetypes.guess_type(abs_path)[0] or "application/octet-stream"
        with open(abs_path, "rb") as fh:  # noqa: ASYNC230 — small local file
            content = fh.read()
        return Response(
            body=content,
            content_type=mime,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return _handle


def resolve_requested_vtk_file(
    data_directory: str,
    working_directory: str,
    filename: str,
) -> str:
    """Resolve a VTK file only inside the visualizer's configured data directory."""
    root = os.path.realpath(os.path.abspath(data_directory))
    requested_root = os.path.realpath((working_directory or "").strip())
    file_value = (filename or "").strip()
    if not requested_root or requested_root != root:
        raise PermissionError(
            "working_directory must match the visualizer data directory"
        )
    if not file_value or os.path.isabs(file_value):
        raise ValueError("file must be relative to working_directory")

    candidate = os.path.realpath(os.path.join(root, file_value))
    try:
        inside_root = os.path.commonpath((root, candidate)) == root
    except ValueError:
        inside_root = False
    if not inside_root:
        raise PermissionError("file must remain inside working_directory")
    if not candidate.lower().endswith(SUPPORTED_VTK_EXTENSIONS):
        raise ValueError("unsupported VTK file extension")
    if not os.path.isfile(candidate):
        raise FileNotFoundError(candidate)
    return candidate


def make_open_file_handler(data_directory: str, state):
    """Return a deep-link handler that appends one VTK file to the pipeline."""

    async def _handle(request):
        from aiohttp import web

        try:
            selected_file = resolve_requested_vtk_file(
                data_directory,
                request.rel_url.query.get("working_directory", ""),
                request.rel_url.query.get("file", ""),
            )
        except PermissionError as exc:
            return web.Response(status=403, text=str(exc))
        except FileNotFoundError:
            return web.Response(status=404, text="VTK file not found")
        except ValueError as exc:
            return web.Response(status=400, text=str(exc))

        state.selected_file = selected_file
        prefix = request.path.rsplit("/api/open", 1)[0]
        return web.HTTPFound(prefix or "/")

    return _handle
