"""Generic Trame controller registrations."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from trame.app.file_upload import ClientFile

from notifications import notify

if TYPE_CHECKING:
    from paraview_backend import ParaViewBackend


def register_common_controllers(
    ctrl,
    state,
    *,
    pv_backend: ParaViewBackend,
    call_view_update,
    persist_uploaded_file,
    refresh_available_files,
    persist_uploaded_state_file,
    refresh_available_state_files,
):
    """Register controller callbacks."""

    @ctrl.add("reset_camera")
    def reset_camera():
        pv_backend.reset_camera()
        call_view_update()

    @ctrl.add("reset_view")
    def reset_view():
        pv_backend.reset_view()
        call_view_update(reset_camera=True)

    @ctrl.add("upload_dataset")
    def upload_dataset(files):
        """Handle a dataset upload from the browser file picker."""
        uploaded_files = files or []
        if not uploaded_files:
            return

        client_file = ClientFile(uploaded_files[0])
        if client_file.is_empty:
            notify(state, "Uploaded file was empty", "error")
            return

        try:
            saved_path = persist_uploaded_file(client_file)
            refresh_available_files()
            state.selected_file = saved_path
            notify(state, f"Loaded {os.path.basename(saved_path)}", "success")
        except Exception as exc:
            notify(state, f"Upload failed: {exc}", "error")

    @ctrl.add("upload_state_file")
    def upload_state_file(files):
        """Handle a state file upload from the browser file picker."""
        uploaded_files = files or []
        if not uploaded_files:
            return

        client_file = ClientFile(uploaded_files[0])
        if client_file.is_empty:
            notify(state, "Uploaded state file was empty", "error")
            return

        try:
            relative_path = persist_uploaded_state_file(client_file)
            refresh_available_state_files()
            state.state_filename = relative_path
            notify(
                state,
                f"Uploaded state file: {os.path.basename(relative_path)}",
                "success",
            )
        except Exception as exc:
            notify(state, f"Upload failed: {exc}", "error")

    @ctrl.add("open_remote_file")
    def open_remote_file(path):
        """Open a file that already exists under the remote data directory."""
        if not path:
            return

        state.remote_browser_dialog = False
        state.selected_file = path

    @ctrl.add("open_remote_browser")
    def open_remote_browser():
        """Open the remote data browser with a fresh file listing."""
        state.remote_search_term = ""
        refresh_available_files()
        state.remote_browser_dialog = True

    @ctrl.add("refresh_remote_files")
    def refresh_remote_files():
        """Force a refresh of the available remote data files."""
        refresh_available_files()

    @ctrl.add("open_remote_state_browser")
    def open_remote_state_browser():
        """Open the remote state browser with a fresh state-file listing."""
        state.state_browser_search_term = ""
        refresh_available_state_files()
        state.state_browser_dialog = True

    @ctrl.add("refresh_remote_state_files")
    def refresh_remote_state_files():
        """Force a refresh of the available remote state files."""
        refresh_available_state_files()
