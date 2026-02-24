from vtkmodules.vtkCommonColor import vtkNamedColors
from vtkmodules.vtkFiltersModeling import vtkOutlineFilter
from vtkmodules.vtkRenderingCore import (
    vtkActor,
    vtkPolyDataMapper,
    vtkDataSetMapper,
    vtkRenderer,
    vtkRenderWindow,
    vtkRenderWindowInteractor,
)

# Required for interactor initialization
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleSwitch  # noqa

# Required for rendering initialization
import vtkmodules.vtkRenderingOpenGL2  # noqa

from file_utils import detect_and_create_reader


def get_available_arrays(dataset):
    """Return list of VSelect-compatible dicts for all point/cell data arrays."""
    arrays = [{"text": "Solid Color", "value": "__solid__"}]

    pd = dataset.GetPointData()
    for i in range(pd.GetNumberOfArrays()):
        arr = pd.GetArray(i)
        if arr is not None:
            arrays.append(
                {"text": f"{arr.GetName()} (Point)", "value": f"point:{arr.GetName()}"}
            )

    cd = dataset.GetCellData()
    for i in range(cd.GetNumberOfArrays()):
        arr = cd.GetArray(i)
        if arr is not None:
            arrays.append(
                {"text": f"{arr.GetName()} (Cell)", "value": f"cell:{arr.GetName()}"}
            )

    return arrays


def build_visualization(filename, renderer):
    """Build visualization pipeline. Returns (actor, mapper, dataset)."""
    renderer.RemoveAllViewProps()

    reader = detect_and_create_reader(filename)
    reader.SetFileName(filename)
    reader.Update()

    dataset = reader.GetOutput()
    print(f"\nDataset Info:")
    print(f"  Type: {dataset.GetClassName()}")
    print(f"  Number of points: {dataset.GetNumberOfPoints()}")
    print(f"  Number of cells: {dataset.GetNumberOfCells()}")

    colors = vtkNamedColors()

    # Outline actor (always present)
    outline = vtkOutlineFilter()
    outline.SetInputConnection(reader.GetOutputPort())

    outlineMapper = vtkPolyDataMapper()
    outlineMapper.SetInputConnection(outline.GetOutputPort())

    outlineActor = vtkActor()
    outlineActor.SetMapper(outlineMapper)
    outlineActor.GetProperty().SetColor(colors.GetColor3d("White"))
    renderer.AddActor(outlineActor)

    # Main dataset actor — solid color by default
    mapper = vtkDataSetMapper()
    mapper.SetInputConnection(reader.GetOutputPort())
    mapper.ScalarVisibilityOff()

    actor = vtkActor()
    actor.SetMapper(mapper)
    renderer.AddActor(actor)

    renderer.ResetCamera()

    return actor, mapper, dataset


def apply_coloring(actor, mapper, dataset, array_value):
    """Update mapper coloring based on the selected array value."""
    colors = vtkNamedColors()

    if array_value == "__solid__" or array_value is None:
        mapper.ScalarVisibilityOff()
        actor.GetProperty().SetColor(colors.GetColor3d("Tomato"))
    elif array_value.startswith("point:"):
        name = array_value[len("point:") :]
        arr = dataset.GetPointData().GetArray(name)
        if arr is not None:
            mapper.ScalarVisibilityOn()
            mapper.SetScalarModeToUsePointFieldData()
            mapper.SelectColorArray(name)
            mapper.SetScalarRange(arr.GetRange())
    elif array_value.startswith("cell:"):
        name = array_value[len("cell:") :]
        arr = dataset.GetCellData().GetArray(name)
        if arr is not None:
            mapper.ScalarVisibilityOn()
            mapper.SetScalarModeToUseCellFieldData()
            mapper.SelectColorArray(name)
            mapper.SetScalarRange(arr.GetRange())


def apply_representation(actor, representation):
    """Update actor property to match the chosen representation mode."""
    prop = actor.GetProperty()
    colors = vtkNamedColors()

    if representation == "Surface":
        prop.SetRepresentationToSurface()
        prop.EdgeVisibilityOff()
    elif representation == "Surface with Edges":
        prop.SetRepresentationToSurface()
        prop.EdgeVisibilityOn()
        prop.SetEdgeColor(colors.GetColor3d("Black"))
    elif representation == "Wireframe":
        prop.SetRepresentationToWireframe()
        prop.EdgeVisibilityOff()
    elif representation == "Points":
        prop.SetRepresentationToPoints()
        prop.SetPointSize(5)


def create_vtk_rendering_context():
    """Create and configure VTK rendering components."""
    renderer = vtkRenderer()
    renderWindow = vtkRenderWindow()
    renderWindow.AddRenderer(renderer)

    renderWindowInteractor = vtkRenderWindowInteractor()
    renderWindowInteractor.SetRenderWindow(renderWindow)
    renderWindowInteractor.GetInteractorStyle().SetCurrentStyleToTrackballCamera()

    return renderer, renderWindow, renderWindowInteractor
