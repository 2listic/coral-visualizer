import os

import pytest

from edit_session import EditSession
from vtkmodules.vtkCommonCore import vtkDoubleArray, vtkIntArray, vtkPoints
from vtkmodules.vtkCommonDataModel import (
    vtkTetra,
    vtkTriangle,
    vtkUnstructuredGrid,
    vtkVertex,
)
from vtkmodules.vtkIOLegacy import vtkUnstructuredGridReader
from vtkmodules.vtkIOXML import vtkXMLUnstructuredGridReader


def _single_cell_grid():
    points = vtkPoints()
    points.InsertNextPoint(0.0, 0.0, 0.0)

    grid = vtkUnstructuredGrid()
    grid.SetPoints(points)

    vertex = vtkVertex()
    vertex.GetPointIds().SetId(0, 0)
    grid.InsertNextCell(vertex.GetCellType(), vertex.GetPointIds())
    return grid


def _single_tetra_grid():
    points = vtkPoints()
    points.InsertNextPoint(0.0, 0.0, 0.0)
    points.InsertNextPoint(1.0, 0.0, 0.0)
    points.InsertNextPoint(0.0, 1.0, 0.0)
    points.InsertNextPoint(0.0, 0.0, 1.0)

    grid = vtkUnstructuredGrid()
    grid.SetPoints(points)

    tetra = vtkTetra()
    tetra.GetPointIds().SetId(0, 0)
    tetra.GetPointIds().SetId(1, 1)
    tetra.GetPointIds().SetId(2, 2)
    tetra.GetPointIds().SetId(3, 3)
    grid.InsertNextCell(tetra.GetCellType(), tetra.GetPointIds())
    return grid


def test_edit_session_save_supports_vtu_and_vtk(tmp_path):
    session = EditSession()
    session.begin("node-1", "source", "/tmp/mesh.vtu", _single_cell_grid())

    vtu_path = tmp_path / "edited.vtu"
    vtk_path = tmp_path / "edited.vtk"

    session.save(str(vtu_path))
    session.save(str(vtk_path))

    assert vtu_path.exists() and vtu_path.stat().st_size > 0
    assert vtk_path.exists() and vtk_path.stat().st_size > 0


def test_edit_session_save_rejects_unsupported_extension(tmp_path):
    session = EditSession()
    session.begin("node-1", "source", "/tmp/mesh.vtu", _single_cell_grid())

    with pytest.raises(ValueError, match="Use .vtu or .vtk"):
        session.save(str(tmp_path / "edited.foo"))


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root ignores directory permissions",
)
@pytest.mark.parametrize(
    "filename, message",
    [
        # vtkXMLUnstructuredGridWriter.Write() returns 1 without creating the file.
        ("edited.vtu", "reported success but no file was created"),
        # vtkUnstructuredGridWriter.Write() returns 0.
        ("edited.vtk", "Failed to write edited dataset"),
    ],
)
def test_edit_session_save_raises_when_directory_is_read_only(
    tmp_path, filename, message
):
    session = EditSession()
    session.begin("node-1", "source", "/tmp/mesh.vtu", _single_cell_grid())
    read_only_dir = tmp_path / "read_only"
    read_only_dir.mkdir()
    read_only_dir.chmod(0o555)
    try:
        with pytest.raises(RuntimeError, match=message):
            session.save(str(read_only_dir / filename))
    finally:
        read_only_dir.chmod(0o755)


def test_surface_mode_materialize_adds_missing_boundary_faces_once():
    session = EditSession()
    session.begin("node-1", "source", "/tmp/mesh.vtu", _single_tetra_grid())
    session.geometry_mode = "surface"

    assert session.replace_selection([0]) == 4
    assert session.materialize_surface_selection() == 4
    assert session.working_dataset.GetNumberOfCells() == 5
    assert session.materialize_surface_selection() == 0


def test_surface_mode_materialize_skips_existing_codim_one_cells():
    session = EditSession()
    session.begin("node-1", "source", "/tmp/mesh.vtu", _single_tetra_grid())
    session.geometry_mode = "surface"

    triangle = vtkTriangle()
    triangle.GetPointIds().SetId(0, 0)
    triangle.GetPointIds().SetId(1, 1)
    triangle.GetPointIds().SetId(2, 2)
    session.working_dataset.InsertNextCell(
        triangle.GetCellType(), triangle.GetPointIds()
    )
    session.working_dataset.Modified()

    assert session.replace_selection([1]) == 1
    assert session.replace_selection([0]) == 4
    assert session.materialize_surface_selection() == 3


def test_surface_mode_materialize_copies_cell_data_from_owner_cell():
    session = EditSession()
    session.begin("node-1", "source", "/tmp/mesh.vtu", _single_tetra_grid())
    session.geometry_mode = "surface"

    material_id = vtkIntArray()
    material_id.SetName("MaterialID")
    material_id.SetNumberOfComponents(1)
    material_id.SetNumberOfTuples(1)
    material_id.SetValue(0, 7)
    session.working_dataset.GetCellData().AddArray(material_id)

    vector_field = vtkDoubleArray()
    vector_field.SetName("VectorField")
    vector_field.SetNumberOfComponents(3)
    vector_field.SetNumberOfTuples(1)
    vector_field.SetTuple3(0, 1.0, 2.0, 3.0)
    session.working_dataset.GetCellData().AddArray(vector_field)

    assert session.replace_selection([(0, 1, 2)]) == 1
    assert session.materialize_surface_selection() == 1

    copied_material = session.working_dataset.GetCellData().GetArray("MaterialID")
    copied_vector = session.working_dataset.GetCellData().GetArray("VectorField")

    assert copied_material.GetTuple1(1) == pytest.approx(7.0)
    assert copied_vector.GetTuple3(1) == pytest.approx((1.0, 2.0, 3.0))


def test_surface_mode_accepts_explicit_surface_key_tuples():
    session = EditSession()
    session.begin("node-1", "source", "/tmp/mesh.vtu", _single_tetra_grid())
    session.geometry_mode = "surface"

    assert session.replace_selection([(0, 1, 2)]) == 1


def test_surface_mode_explicit_boundary_keys_do_not_scan_existing_codim_cells():
    session = EditSession()
    session.begin("node-1", "source", "/tmp/mesh.vtu", _single_tetra_grid())
    session.geometry_mode = "surface"
    session._surface_boundary_map_for_top_cells()
    session._existing_codim_keys = lambda _dimension: (_ for _ in ()).throw(
        AssertionError("boundary keys should not require existing codim scan")
    )

    assert session.replace_selection([(0, 1, 2)]) == 1


def test_surface_mode_grow_selection_expands_across_adjacent_faces():
    session = EditSession()
    session.begin("node-1", "source", "/tmp/mesh.vtu", _single_tetra_grid())
    session.geometry_mode = "surface"

    assert session.replace_selection([(0, 1, 2)], grow=False) == 1
    assert session.replace_selection([(0, 1, 2)], grow=True, angle_threshold=180) == 4


def test_surface_mode_grow_selection_respects_angle_threshold():
    session = EditSession()
    session.begin("node-1", "source", "/tmp/mesh.vtu", _single_tetra_grid())
    session.geometry_mode = "surface"

    # 0 degrees should keep only the seed face (no adjacent face is coplanar).
    assert session.replace_selection([(0, 1, 2)], grow=True, angle_threshold=0) == 1
    # Wide threshold should include one-ring adjacent faces.
    assert session.replace_selection([(0, 1, 2)], grow=True, angle_threshold=180) == 4


def test_surface_mode_grow_selection_is_transitive_when_angles_allow():
    session = EditSession()
    session.begin("node-1", "source", "/tmp/mesh.vtu", _single_tetra_grid())
    session.geometry_mode = "surface"
    session._ensure_surface_adjacency = lambda: {
        ("A",): {("B",)},
        ("B",): {("A",), ("C",)},
        ("C",): {("B",)},
    }
    session._surface_neighbor_angle_degrees = lambda a, b: 0.0

    grown = session._grow_surface_selection({("A",)}, angle_threshold=0)
    assert grown == {("A",), ("B",), ("C",)}


def test_surface_mode_save_keeps_cell_data_lengths_consistent(tmp_path):
    session = EditSession()
    session.begin("node-1", "source", "/tmp/mesh.vtu", _single_tetra_grid())
    session.geometry_mode = "surface"
    session.create_field("BoundaryID", "cell", "1", overwrite=True)
    session.geometry_mode = "surface"
    session.replace_selection([0])
    assert session.materialize_surface_selection() == 4

    output_path = tmp_path / "surface_saved.vtu"
    session.save(str(output_path))

    reader = vtkXMLUnstructuredGridReader()
    reader.SetFileName(str(output_path))
    reader.Update()
    loaded = reader.GetOutput()

    assert loaded.GetNumberOfPoints() == 4
    assert loaded.GetNumberOfCells() == 5
    assert loaded.GetCellData().GetArray("BoundaryID") is not None


def test_surface_mode_save_legacy_vtk_omits_internal_cell_centers(tmp_path):
    session = EditSession()
    session.begin("node-1", "source", "/tmp/mesh.vtu", _single_tetra_grid())
    session.geometry_mode = "surface"

    material_id = vtkIntArray()
    material_id.SetName("MaterialID")
    material_id.SetNumberOfComponents(1)
    material_id.SetNumberOfTuples(1)
    material_id.SetValue(0, 42)
    session.working_dataset.GetCellData().AddArray(material_id)

    session.create_field("BoundaryID", "cell", "0", overwrite=True)
    session.replace_selection([(0, 1, 2)])
    session.assign_to_selected("BoundaryID", "cell", "1")

    output_path = tmp_path / "surface_saved.vtk"
    session.save(str(output_path))

    reader = vtkUnstructuredGridReader()
    reader.SetFileName(str(output_path))
    reader.Update()
    loaded = reader.GetOutput()

    assert loaded.GetNumberOfPoints() == 4
    assert loaded.GetNumberOfCells() == 2
    assert loaded.GetCellData().GetArray("BoundaryID") is not None
    assert loaded.GetCellData().GetArray("MaterialID").GetTuple1(1) == pytest.approx(
        42.0
    )
    assert loaded.GetCellData().GetArray("CellCenters") is None


def test_is_supported_dataset_type_accepts_only_unstructured_grid():
    assert EditSession.is_supported_dataset_type("vtkUnstructuredGrid") is True
    assert EditSession.is_supported_dataset_type("vtkPolyData") is False
    assert EditSession.is_supported_dataset_type("vtkStructuredGrid") is False
    assert EditSession.is_supported_dataset_type("") is False
    assert EditSession.is_supported_dataset_type("vtkUnstructuredGridBase") is False
