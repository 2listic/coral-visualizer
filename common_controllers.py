"""Generic Trame controller registrations shared across backends."""

import os

from trame.app.file_upload import ClientFile


def register_common_controllers(
    ctrl,
    state,
    *,
    is_paraview_backend,
    pv_backend,
    call_view_update,
    reset_vtk_camera,
    reset_vtk_view,
    persist_uploaded_file,
    refresh_available_files,
):
    """Register backend-agnostic controller callbacks."""

    @ctrl.add("reset_camera")
    def reset_camera():
        """Reset the active camera for the selected backend."""
        if is_paraview_backend():
            pv_backend.reset_camera()
            call_view_update()
            return

        reset_vtk_camera()

    @ctrl.add("reset_view")
    def reset_view():
        """Restore a canonical XYZ view and reset the camera framing."""
        if is_paraview_backend():
            pv_backend.reset_view()
            call_view_update(reset_camera=True)
            return

        reset_vtk_view()

    @ctrl.add("upload_dataset")
    def upload_dataset(files):
        """Handle a dataset upload from the browser file picker."""
        uploaded_files = files or []
        if not uploaded_files:
            return

        client_file = ClientFile(uploaded_files[0])
        if client_file.is_empty:
            state.upload_status = "Uploaded file was empty"
            state.upload_status_type = "error"
            return

        try:
            saved_path = persist_uploaded_file(client_file)
            refresh_available_files()
            state.selected_file = saved_path
            state.upload_status = f"Loaded {os.path.basename(saved_path)}"
            state.upload_status_type = "success"
        except Exception as exc:
            state.upload_status = f"Upload failed: {exc}"
            state.upload_status_type = "error"

    @ctrl.add("open_remote_file")
    def open_remote_file(path):
        """Open a file that already exists under the remote data directory."""
        if not path:
            return

        state.remote_browser_dialog = False
        state.selected_file = path
