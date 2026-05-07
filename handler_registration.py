"""Centralized registration of Trame handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trame_server.controller import Controller
    from trame_server.state import State

    from file_operations import FileOperationService
    from paraview_runtime import ParaViewRuntime
    from view_controls import ViewControllerProxy

from runtime_setup import RuntimeContext
from common_controllers import register_common_controllers
from paraview_controllers import register_paraview_controllers
from state_handlers import register_state_handlers


def register_app_handlers(
    *,
    ctrl: Controller,
    state: State,
    runtime: RuntimeContext,
    file_operations: FileOperationService,
    interaction_quality_presets: dict,
    view_controls: ViewControllerProxy,
):
    """Register all app handlers against the active ParaView runtime."""
    pv_backend = runtime.pv_backend
    edit_session = runtime.edit_session
    paraview_runtime: ParaViewRuntime = runtime.paraview_runtime

    register_paraview_controllers(
        ctrl,
        state,
        pv_backend=pv_backend,
        edit_session=edit_session,
        refresh_runtime_message=paraview_runtime.refresh_runtime_message,
        update_paraview_ui_state=paraview_runtime.update_ui_state,
        render_and_push=paraview_runtime.render_and_push,
        save_paraview_output=file_operations.save_paraview_output,
        save_paraview_state=file_operations.save_paraview_state,
        load_paraview_state=file_operations.load_paraview_state,
        debug_view=view_controls.debug,
        call_view_update_geometry=view_controls.update_geometry,
        call_view_set_remote_rendering=view_controls.set_remote_rendering,
        call_view_update=view_controls.update,
        sync_edit_session_state=paraview_runtime.sync_edit_session_state,
        sync_paraview_edit_selection_overlay=paraview_runtime.sync_edit_selection_overlay,
        summarize_edit_event=paraview_runtime.summarize_edit_event,
        normalize_edit_selection_ids=paraview_runtime.normalize_edit_selection_ids,
    )

    register_state_handlers(
        state,
        load_file=paraview_runtime.load_file,
        apply_coloring=paraview_runtime.apply_coloring,
        apply_active_representation=paraview_runtime.apply_representation,
        pv_backend=pv_backend,
        update_paraview_ui_state=paraview_runtime.update_ui_state,
        render_and_push=paraview_runtime.render_and_push,
        sync_edit_session_state=paraview_runtime.sync_edit_session_state,
        interaction_quality_presets=interaction_quality_presets,
    )

    register_common_controllers(
        ctrl,
        state,
        pv_backend=pv_backend,
        call_view_update=view_controls.update,
        persist_uploaded_file=file_operations.persist_uploaded_file,
        refresh_available_files=file_operations.refresh_available_files,
        persist_uploaded_state_file=file_operations.persist_uploaded_state_file,
        refresh_available_state_files=file_operations.refresh_available_state_files,
    )
