import pytest

from edit_session import EditSession
from vtkmodules.vtkCommonCore import vtkIntArray, vtkPoints
from vtkmodules.vtkCommonDataModel import vtkUnstructuredGrid, vtkVertex


def _single_cell_grid():
    points = vtkPoints()
    points.InsertNextPoint(0.0, 0.0, 0.0)

    grid = vtkUnstructuredGrid()
    grid.SetPoints(points)

    vertex = vtkVertex()
    vertex.GetPointIds().SetId(0, 0)
    grid.InsertNextCell(vertex.GetCellType(), vertex.GetPointIds())
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
