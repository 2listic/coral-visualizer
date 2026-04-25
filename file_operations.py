"""File and save helpers shared by Trame controllers."""

import os
from dataclasses import dataclass
from pathlib import Path

from file_utils import get_vtk_files_from_data_folder


@dataclass
class FileOperationService:
    """Stateful file operations used by Trame controller wiring."""

    state: object
    data_directory: str
    pv_backend: object | None = None
    edit_session: object | None = None

    def refresh_available_files(self):
        refresh_available_files(self.state, self.data_directory)

    def persist_uploaded_file(self, client_file):
        return persist_uploaded_file(self.data_directory, client_file)

    def save_paraview_output(self):
        return save_paraview_output(
            state=self.state,
            data_directory=self.data_directory,
            pv_backend=self.pv_backend,
            edit_session=self.edit_session,
        )


def refresh_available_files(state, data_directory):
    """Refresh the file list exposed to the UI."""
    state.available_files = get_vtk_files_from_data_folder(data_directory)


def resolve_output_path(data_directory, filename, fallback_name):
    """Resolve a save target strictly inside ``data_directory``."""
    raw_name = (filename or "").strip() or fallback_name
    candidate = Path(raw_name)
    relative_candidate = (
        Path(*candidate.parts[1:]) if candidate.is_absolute() else candidate
    )
    normalized = Path(os.path.normpath(str(relative_candidate)))
    if str(normalized).startswith(".."):
        raise ValueError("Output path must stay inside --data-directory")
    return os.path.join(data_directory, str(normalized))


def persist_uploaded_file(data_directory, client_file):
    """Persist an uploaded client-side dataset into the data directory."""
    uploads_dir = Path(data_directory) / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    original_name = Path(client_file.name or "upload.vtu").name
    stem = Path(original_name).stem
    suffix = Path(original_name).suffix or ".vtu"
    candidate = uploads_dir / original_name
    counter = 1
    while candidate.exists():
        candidate = uploads_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    candidate.write_bytes(client_file.content)
    return str(candidate)


def save_paraview_output(*, state, data_directory, pv_backend, edit_session):
    """Save the active ParaView output or edit-session dataset and return its path."""
    if pv_backend.source is None and not edit_session.active:
        raise RuntimeError("No active pipeline item to save")

    if edit_session.active:
        fallback_name = edit_session.default_output_filename()
        output_path = resolve_output_path(data_directory, state.save_filename, fallback_name)
        suffix = os.path.splitext(output_path)[1].lower()
        if not suffix:
            output_path += ".vtu"
        elif suffix not in {".vtu", ".vtk"}:
            raise ValueError(
                "Unsupported edit output format. Use .vtu or .vtk for edit-session saves."
            )
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        edit_session.save(output_path)
        saved_kind = "edited dataset"
    else:
        fallback_name = pv_backend.default_output_filename()
        output_path = resolve_output_path(data_directory, state.save_filename, fallback_name)
        if not os.path.splitext(output_path)[1]:
            output_path += pv_backend.default_output_extension()
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        pv_backend.save_active_data(output_path)
        saved_kind = "pipeline result"

    refresh_available_files(state, data_directory)
    relative_output = os.path.relpath(output_path, data_directory)
    state.save_filename = relative_output
    state.save_status = f"Saved {saved_kind} to {relative_output}"
    state.save_status_type = "success"
    return output_path
