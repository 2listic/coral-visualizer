"""File and save helpers shared by Trame controllers."""

from __future__ import annotations

import errno
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from file_utils import get_vtk_files_from_data_folder

if TYPE_CHECKING:
    from trame_server.state import State

    from edit_session import EditSession
    from paraview_backend import ParaViewBackend

STATE_FILE_EXTENSION = ".coral.state.json"
DEFAULT_STATE_FILENAME = f"session{STATE_FILE_EXTENSION}"


@dataclass
class FileOperationService:
    """Stateful file operations used by Trame controller wiring."""

    state: State
    data_directory: str
    pv_backend: ParaViewBackend
    edit_session: EditSession

    def refresh_available_files(self):
        refresh_available_files(self.state, self.data_directory)

    def refresh_available_state_files(self):
        refresh_available_state_files(self.state, self.data_directory)

    def persist_uploaded_file(self, client_file):
        return persist_uploaded_file(self.data_directory, client_file)

    def persist_uploaded_state_file(self, client_file):
        return persist_uploaded_state_file(self.data_directory, client_file)

    def save_paraview_output(self, overwrite=False):
        return save_paraview_output(
            state=self.state,
            data_directory=self.data_directory,
            pv_backend=self.pv_backend,
            edit_session=self.edit_session,
            overwrite=overwrite,
        )

    def save_paraview_state(self, overwrite=False):
        return save_paraview_state(
            state=self.state,
            data_directory=self.data_directory,
            pv_backend=self.pv_backend,
            overwrite=overwrite,
        )

    def load_paraview_state(self):
        return load_paraview_state(
            state=self.state,
            data_directory=self.data_directory,
        )


def refresh_available_files(state, data_directory):
    """Refresh the file list exposed to the UI."""
    state.available_files = get_vtk_files_from_data_folder(data_directory)


def get_state_files_from_data_folder(data_directory):
    """Return saved application state files from the data directory."""
    root = Path(data_directory)
    if not root.exists():
        return []

    items = []
    for candidate in sorted(root.rglob(f"*{STATE_FILE_EXTENSION}")):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(root).as_posix()
        items.append({"text": relative, "value": relative})
    return items


def refresh_available_state_files(state, data_directory):
    """Refresh the saved-state file list exposed to the UI."""
    state.state_files = get_state_files_from_data_folder(data_directory)


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


def resolve_state_path(data_directory, filename, fallback_name=DEFAULT_STATE_FILENAME):
    """Resolve a saved application-state path inside ``data_directory``."""
    output_path = resolve_output_path(data_directory, filename, fallback_name)
    if not output_path.endswith(STATE_FILE_EXTENSION):
        output_path += STATE_FILE_EXTENSION
    return output_path


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


def persist_uploaded_state_file(data_directory, client_file):
    """Persist an uploaded state JSON file into the data directory and return its relative path."""
    uploads_dir = Path(data_directory) / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    original_name = Path(client_file.name or f"upload{STATE_FILE_EXTENSION}").name
    if not original_name.endswith(STATE_FILE_EXTENSION):
        original_name = Path(original_name).stem + STATE_FILE_EXTENSION
    stem = original_name[: -len(STATE_FILE_EXTENSION)]
    candidate = uploads_dir / original_name
    counter = 1
    while candidate.exists():
        candidate = uploads_dir / f"{stem}_{counter}{STATE_FILE_EXTENSION}"
        counter += 1

    candidate.write_bytes(client_file.content)
    return os.path.relpath(str(candidate), data_directory)


def _flush_save_feedback(state):
    """Best-effort push of save feedback state to the client."""
    dirty = getattr(state, "dirty", None)
    if callable(dirty):
        for key in (
            "save_filename",
            "save_status",
            "save_status_type",
            "available_files",
        ):
            try:
                dirty(key)
            except Exception:
                pass

    flush = getattr(state, "flush", None)
    if callable(flush):
        try:
            flush()
        except Exception:
            pass


def resolve_paraview_output_path(*, state, data_directory, pv_backend, edit_session):
    """Resolve the active ParaView save target and classify the output kind."""
    if pv_backend.source is None and not edit_session.active:
        raise RuntimeError("No active pipeline item to save")

    if edit_session.active:
        fallback_name = edit_session.default_output_filename()
        output_path = resolve_output_path(
            data_directory, state.save_filename, fallback_name
        )
        suffix = os.path.splitext(output_path)[1].lower()
        if not suffix:
            output_path += ".vtu"
        elif suffix not in {".vtu", ".vtk"}:
            raise ValueError(
                "Unsupported edit output format. Use .vtu or .vtk for edit-session saves."
            )
        saved_kind = "edited dataset"
    else:
        fallback_name = pv_backend.default_output_filename()
        output_path = resolve_output_path(
            data_directory, state.save_filename, fallback_name
        )
        if not os.path.splitext(output_path)[1]:
            output_path += pv_backend.default_output_extension()
        saved_kind = "pipeline result"

    return output_path, saved_kind


def save_paraview_output(
    *, state, data_directory, pv_backend, edit_session, overwrite=False
):
    """Save the active ParaView output or edit-session dataset and return its path."""
    output_path, saved_kind = resolve_paraview_output_path(
        state=state,
        data_directory=data_directory,
        pv_backend=pv_backend,
        edit_session=edit_session,
    )
    relative_output = os.path.relpath(output_path, data_directory)

    if os.path.exists(output_path) and not overwrite:
        raise FileExistsError(
            errno.EEXIST,
            "Output file already exists",
            relative_output,
        )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    if edit_session.active:
        edit_session.save(output_path)
    else:
        pv_backend.save_active_data(output_path)

    refresh_available_files(state, data_directory)
    state.save_filename = relative_output
    state.save_status = f"Saved {saved_kind} to {relative_output}"
    state.save_status_type = "success"
    _flush_save_feedback(state)
    return output_path


def save_paraview_state(*, state, data_directory, pv_backend, overwrite=False):
    """Serialize and save the current ParaView application state to disk."""
    exporter = getattr(pv_backend, "export_app_state", None)
    if not callable(exporter):
        raise RuntimeError("Current backend does not support saving application state")

    output_path = resolve_state_path(
        data_directory, getattr(state, "state_filename", "")
    )
    relative_output = os.path.relpath(output_path, data_directory)

    if os.path.exists(output_path) and not overwrite:
        raise FileExistsError(
            errno.EEXIST,
            "State file already exists",
            relative_output,
        )

    snapshot = exporter() or {}
    snapshot.setdefault("version", 1)
    snapshot.setdefault("selected_file", getattr(state, "selected_file", "") or "")

    def _json_default(obj):
        """Fallback serializer: convert any non-JSON-serializable value to its string form."""
        try:
            return str(obj)
        except Exception:
            return None

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    Path(output_path).write_text(
        json.dumps(snapshot, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )

    refresh_available_state_files(state, data_directory)
    state.state_filename = relative_output
    state.state_status = f"Saved application state to {relative_output}"
    state.state_status_type = "success"
    _flush_save_feedback(state)
    return output_path


def load_paraview_state(*, state, data_directory):
    """Load a previously saved ParaView application state snapshot from disk."""
    input_path = resolve_state_path(
        data_directory, getattr(state, "state_filename", "")
    )
    if not os.path.exists(input_path):
        raise FileNotFoundError(
            errno.ENOENT,
            "State file not found",
            os.path.relpath(input_path, data_directory),
        )

    snapshot = json.loads(Path(input_path).read_text(encoding="utf-8"))
    state.state_filename = os.path.relpath(input_path, data_directory)
    refresh_available_state_files(state, data_directory)
    return snapshot, input_path
