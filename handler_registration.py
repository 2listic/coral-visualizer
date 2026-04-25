"""Centralized registration of Trame handlers."""

from common_controllers import register_common_controllers
from paraview_controllers import register_paraview_controllers
from state_handlers import register_state_handlers
from vtk_controllers import register_vtk_handlers


def _noop(*args, **kwargs):
    return None


def register_app_handlers(
    *,
    ctrl,
    state,
    backend,
    data_directory,
    pv_backend,
    edit_session,
    edit_state,
    pick_interactor,
    vtk_runtime,
    paraview_runtime,
    update_selection_actor,
    assign_id_to_selection,
    save_as_vtu,
    file_operations,
    interaction_quality_presets,
    debug_view,
    call_view_update,
    call_view_update_geometry,
    call_view_set_remote_rendering,
):
    """Register all app handlers against the active backend runtimes."""

    def is_paraview_backend():
        return backend == "paraview"

    def is_vtk_backend():
        return backend == "vtk"

    def get_vtk_visualization():
        return vtk_runtime.viz

    def get_active_vtk_lut():
        return vtk_runtime.active_lut

    render_and_push = (
        paraview_runtime.render_and_push
        if paraview_runtime
        else vtk_runtime.render_and_push
    )
    refresh_runtime_message = (
        paraview_runtime.refresh_runtime_message if paraview_runtime else _noop
    )
    update_paraview_ui_state = (
        paraview_runtime.update_ui_state if paraview_runtime else _noop
    )
    sync_edit_session_state = (
        paraview_runtime.sync_edit_session_state if paraview_runtime else _noop
    )
    normalize_edit_selection_ids = (
        paraview_runtime.normalize_edit_selection_ids if paraview_runtime else _noop
    )
    sync_paraview_edit_selection_overlay = (
        paraview_runtime.sync_edit_selection_overlay if paraview_runtime else _noop
    )
    summarize_edit_event = (
        paraview_runtime.summarize_edit_event if paraview_runtime else _noop
    )
    apply_edit_coloring = vtk_runtime.apply_edit_coloring if vtk_runtime else _noop
    update_scalar_bars = vtk_runtime.update_scalar_bars if vtk_runtime else _noop
    apply_vtk_coloring = vtk_runtime.apply_coloring if vtk_runtime else _noop
    apply_paraview_coloring = (
        paraview_runtime.apply_coloring if paraview_runtime else _noop
    )
    load_file_with_vtk_backend = vtk_runtime.load_file if vtk_runtime else _noop
    load_file_with_paraview_backend = (
        paraview_runtime.load_file if paraview_runtime else _noop
    )
    reset_vtk_camera = vtk_runtime.reset_camera if vtk_runtime else _noop
    reset_vtk_view = vtk_runtime.reset_view if vtk_runtime else _noop
    apply_vtk_representation_to_scene = (
        vtk_runtime.apply_representation if vtk_runtime else _noop
    )

    def apply_active_representation(representation):
        """Apply the current representation using the active backend runtime."""
        if paraview_runtime is not None:
            paraview_runtime.apply_representation(representation)
            return

        vtk_runtime.apply_representation(representation)
        vtk_runtime.render_and_push()

    register_paraview_controllers(
        ctrl,
        state,
        is_paraview_backend=is_paraview_backend,
        pv_backend=pv_backend,
        edit_session=edit_session,
        refresh_runtime_message=refresh_runtime_message,
        update_paraview_ui_state=update_paraview_ui_state,
        render_and_push=render_and_push,
        save_paraview_output=file_operations.save_paraview_output,
        debug_view=debug_view,
        call_view_update_geometry=call_view_update_geometry,
        call_view_set_remote_rendering=call_view_set_remote_rendering,
        call_view_update=call_view_update,
        sync_edit_session_state=sync_edit_session_state,
        sync_paraview_edit_selection_overlay=sync_paraview_edit_selection_overlay,
        summarize_edit_event=summarize_edit_event,
        normalize_edit_selection_ids=normalize_edit_selection_ids,
    )

    register_vtk_handlers(
        state,
        ctrl,
        is_vtk_backend=is_vtk_backend,
        viz_getter=get_vtk_visualization,
        edit_state=edit_state,
        pick_interactor=pick_interactor,
        data_directory=data_directory,
        apply_edit_coloring=apply_edit_coloring,
        render_and_push=render_and_push,
        update_selection_actor=update_selection_actor,
        assign_id_to_selection=assign_id_to_selection,
        save_as_vtu=save_as_vtu,
        refresh_available_files=file_operations.refresh_available_files,
        update_scalar_bars=update_scalar_bars,
        active_lut_getter=get_active_vtk_lut,
        apply_vtk_coloring=apply_vtk_coloring,
        apply_vtk_representation_to_scene=apply_vtk_representation_to_scene,
    )

    register_state_handlers(
        state,
        is_paraview_backend=is_paraview_backend,
        load_file_with_paraview_backend=load_file_with_paraview_backend,
        load_file_with_vtk_backend=load_file_with_vtk_backend,
        apply_paraview_coloring=apply_paraview_coloring,
        apply_vtk_coloring=apply_vtk_coloring,
        apply_active_representation=apply_active_representation,
        pv_backend=pv_backend,
        update_paraview_ui_state=update_paraview_ui_state,
        render_and_push=render_and_push,
        sync_edit_session_state=sync_edit_session_state,
        interaction_quality_presets=interaction_quality_presets,
    )

    register_common_controllers(
        ctrl,
        state,
        is_paraview_backend=is_paraview_backend,
        pv_backend=pv_backend,
        call_view_update=call_view_update,
        reset_vtk_camera=reset_vtk_camera,
        reset_vtk_view=reset_vtk_view,
        persist_uploaded_file=file_operations.persist_uploaded_file,
        refresh_available_files=file_operations.refresh_available_files,
    )
