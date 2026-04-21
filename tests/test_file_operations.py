from pathlib import Path
from types import SimpleNamespace

import pytest

import file_operations


class FakeClientFile:
    def __init__(self, name, content):
        self.name = name
        self.content = content


class FakeEditSession:
    def __init__(self, active, default_name="edited_result", default_extension=".vtu"):
        self.active = active
        self._default_name = default_name
        self._default_extension = default_extension
        self.saved_paths = []

    def default_output_filename(self):
        return self._default_name

    def save(self, output_path):
        Path(output_path).write_bytes(b"edited")
        self.saved_paths.append(output_path)


class FakeParaViewBackend:
    def __init__(self, *, source="active-source", default_name="pipeline_result", extension=".pvd"):
        self.source = source
        self._default_name = default_name
        self._extension = extension
        self.saved_paths = []

    def default_output_filename(self):
        return self._default_name

    def default_output_extension(self):
        return self._extension

    def save_active_data(self, output_path):
        Path(output_path).write_bytes(b"pipeline")
        self.saved_paths.append(output_path)


def test_refresh_available_files_delegates_to_file_utils(monkeypatch):
    state = SimpleNamespace(available_files=[])
    expected = [{"text": "a", "value": "a.vtu"}]

    monkeypatch.setattr(file_operations, "get_vtk_files_from_data_folder", lambda _: expected)

    file_operations.refresh_available_files(state, "/tmp/data")

    assert state.available_files == expected


def test_resolve_output_path_rejects_parent_escape(tmp_path):
    with pytest.raises(ValueError, match="inside --data-directory"):
        file_operations.resolve_output_path(str(tmp_path), "../escape/out.vtu", "fallback")


def test_resolve_output_path_normalizes_absolute_names_inside_data_directory(tmp_path):
    resolved = file_operations.resolve_output_path(
        str(tmp_path),
        "/nested/result",
        "fallback",
    )

    assert resolved == str(tmp_path / "nested" / "result")


def test_persist_uploaded_file_deduplicates_names(tmp_path):
    first = FakeClientFile("mesh.vtu", b"first")
    second = FakeClientFile("mesh.vtu", b"second")

    first_path = file_operations.persist_uploaded_file(str(tmp_path), first)
    second_path = file_operations.persist_uploaded_file(str(tmp_path), second)

    assert Path(first_path).name == "mesh.vtu"
    assert Path(second_path).name == "mesh_1.vtu"
    assert Path(first_path).read_bytes() == b"first"
    assert Path(second_path).read_bytes() == b"second"


def test_save_paraview_output_saves_edit_session_and_updates_state(tmp_path, monkeypatch):
    state = SimpleNamespace(
        save_filename="results/edited_mesh",
        save_status="",
        save_status_type="info",
        available_files=[],
    )
    edit_session = FakeEditSession(active=True)
    pv_backend = FakeParaViewBackend()

    monkeypatch.setattr(
        file_operations,
        "get_vtk_files_from_data_folder",
        lambda directory: [{"text": "edited", "value": "results/edited_mesh.vtu"}],
    )

    output_path = file_operations.save_paraview_output(
        state=state,
        data_directory=str(tmp_path),
        pv_backend=pv_backend,
        edit_session=edit_session,
    )

    assert output_path == str(tmp_path / "results" / "edited_mesh.vtu")
    assert edit_session.saved_paths == [output_path]
    assert pv_backend.saved_paths == []
    assert state.save_filename == "results/edited_mesh.vtu"
    assert state.save_status == "Saved edited dataset to results/edited_mesh.vtu"
    assert state.save_status_type == "success"
    assert state.available_files == [{"text": "edited", "value": "results/edited_mesh.vtu"}]


def test_save_paraview_output_saves_pipeline_result_with_backend_extension(tmp_path, monkeypatch):
    state = SimpleNamespace(
        save_filename="exports/final",
        save_status="",
        save_status_type="info",
        available_files=[],
    )
    edit_session = FakeEditSession(active=False)
    pv_backend = FakeParaViewBackend(extension=".vtu")

    monkeypatch.setattr(
        file_operations,
        "get_vtk_files_from_data_folder",
        lambda directory: [{"text": "saved", "value": "exports/final.vtu"}],
    )

    output_path = file_operations.save_paraview_output(
        state=state,
        data_directory=str(tmp_path),
        pv_backend=pv_backend,
        edit_session=edit_session,
    )

    assert output_path == str(tmp_path / "exports" / "final.vtu")
    assert pv_backend.saved_paths == [output_path]
    assert state.save_status == "Saved pipeline result to exports/final.vtu"
    assert state.available_files == [{"text": "saved", "value": "exports/final.vtu"}]


def test_save_paraview_output_requires_active_source_or_edit_session(tmp_path):
    state = SimpleNamespace(save_filename="", save_status="", save_status_type="info")
    edit_session = FakeEditSession(active=False)
    pv_backend = FakeParaViewBackend(source=None)

    with pytest.raises(RuntimeError, match="No active pipeline item to save"):
        file_operations.save_paraview_output(
            state=state,
            data_directory=str(tmp_path),
            pv_backend=pv_backend,
            edit_session=edit_session,
        )
