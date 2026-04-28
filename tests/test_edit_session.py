import pytest

from edit_session import EditSession
from vtkmodules.vtkCommonCore import vtkIntArray, vtkPoints
from vtkmodules.vtkCommonDataModel import vtkTetra, vtkTriangle, vtkUnstructuredGrid, vtkVertex
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


def test_apply_volume_field_requires_overwrite_for_existing_field():
    session = EditSession()
    session.begin("node-1", "source", "/tmp/mesh.vtu", _single_cell_grid())

    original = vtkIntArray()
    original.SetName("A field")
    original.SetNumberOfComponents(1)
    original.SetNumberOfTuples(1)
    original.SetValue(0, 1)
    session.working_dataset.GetCellData().AddArray(original)

    assert session.has_cell_field("A field") is True

    with pytest.raises(RuntimeError, match="already exists"):
        session.apply_volume_field("A field", "", "2.5")

    session.apply_volume_field("A field", "", "2.5", overwrite=True)
    replaced = session.working_dataset.GetCellData().GetArray("A field")

    assert replaced.GetClassName() == "vtkDoubleArray"
    assert replaced.GetTuple1(0) == pytest.approx(2.5)


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
    session.working_dataset.InsertNextCell(triangle.GetCellType(), triangle.GetPointIds())
    session.working_dataset.Modified()

    assert session.replace_selection([1]) == 1
    assert session.replace_selection([0]) == 4
    assert session.materialize_surface_selection() == 3


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
    session.apply_volume_field("BoundaryID", "", "1", overwrite=True)
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


def test_apply_surface_field_sets_default_on_all_cells_and_expression_on_selected_surface():
    session = EditSession()
    session.begin("node-1", "source", "/tmp/mesh.vtu", _single_tetra_grid())
    session.geometry_mode = "surface"
    session.replace_selection([(0, 1, 2)])

    session.apply_surface_field("BoundaryID", "1", "0", overwrite=True)
    field = session.working_dataset.GetCellData().GetArray("BoundaryID")

    assert field is not None
    assert session.working_dataset.GetNumberOfCells() == 2
    assert field.GetTuple1(0) == pytest.approx(0.0)
    assert field.GetTuple1(1) == pytest.approx(1.0)
