from vtkmodules.vtkCommonColor import vtkNamedColors
from vtkmodules.vtkCommonCore import vtkLookupTable
from vtkmodules.vtkFiltersCore import (
    vtkContourFilter,
    vtkGlyph3D,
    vtkMaskPoints,
    vtkThresholdPoints,
)
from vtkmodules.vtkFiltersModeling import vtkOutlineFilter
from vtkmodules.vtkFiltersSources import vtkConeSource
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


def has_vector_data(dataset):
    """Check if dataset has vector data at points."""
    return (
        dataset.GetPointData() is not None
        and dataset.GetPointData().GetVectors() is not None
    )


def has_scalar_data(dataset):
    """Check if dataset has scalar data at points."""
    return (
        dataset.GetPointData() is not None
        and dataset.GetPointData().GetScalars() is not None
    )


def build_visualization(filename, renderer):
    """Build visualization pipeline for the given file."""
    # Clear existing actors
    renderer.RemoveAllViewProps()

    # Read the data
    reader = detect_and_create_reader(filename)
    reader.SetFileName(filename)
    reader.Update()

    # Get the output dataset
    dataset = reader.GetOutput()
    print(f"\nDataset Info:")
    print(f"  Type: {dataset.GetClassName()}")
    print(f"  Number of points: {dataset.GetNumberOfPoints()}")
    print(f"  Number of cells: {dataset.GetNumberOfCells()}")
    print(f"  Has vectors: {has_vector_data(dataset)}")
    print(f"  Has scalars: {has_scalar_data(dataset)}")

    colors = vtkNamedColors()

    # Always add outline
    outline = vtkOutlineFilter()
    outline.SetInputConnection(reader.GetOutputPort())

    outlineMapper = vtkPolyDataMapper()
    outlineMapper.SetInputConnection(outline.GetOutputPort())

    outlineActor = vtkActor()
    outlineActor.SetMapper(outlineMapper)
    outlineActor.GetProperty().SetColor(colors.GetColor3d("White"))
    renderer.AddActor(outlineActor)

    # Build visualization based on available data
    if has_vector_data(dataset) and has_scalar_data(dataset):
        print("\nUsing FLOW visualization (vectors + contours)\n")
        _add_flow_visualization(reader, renderer, colors)

    elif has_scalar_data(dataset):
        print("\nUsing SCALAR visualization (colored by scalar values)\n")
        _add_scalar_visualization(reader, dataset, renderer)

    else:
        print("\nUsing BASIC visualization (wireframe/surface)\n")
        _add_basic_visualization(reader, renderer, colors)

    renderer.ResetCamera()


def _add_flow_visualization(reader, renderer, colors):
    """Add flow visualization with glyphs and contours."""
    # Glyphs for vector field
    threshold = vtkThresholdPoints()
    threshold.SetInputConnection(reader.GetOutputPort())
    threshold.ThresholdByUpper(200)

    mask = vtkMaskPoints()
    mask.SetInputConnection(threshold.GetOutputPort())
    mask.SetOnRatio(5)

    cone = vtkConeSource()
    cone.SetResolution(11)
    cone.SetHeight(1)
    cone.SetRadius(0.25)

    cones = vtkGlyph3D()
    cones.SetInputConnection(mask.GetOutputPort())
    cones.SetSourceConnection(cone.GetOutputPort())
    cones.SetScaleFactor(0.4)
    cones.SetScaleModeToScaleByVector()

    lut = vtkLookupTable()
    lut.SetHueRange(0.667, 0.0)
    lut.Build()

    scalarRange = [0] * 2
    cones.Update()
    scalarRange[0] = cones.GetOutput().GetPointData().GetScalars().GetRange()[0]
    scalarRange[1] = cones.GetOutput().GetPointData().GetScalars().GetRange()[1]

    vectorMapper = vtkPolyDataMapper()
    vectorMapper.SetInputConnection(cones.GetOutputPort())
    vectorMapper.SetScalarRange(scalarRange[0], scalarRange[1])
    vectorMapper.SetLookupTable(lut)

    vectorActor = vtkActor()
    vectorActor.SetMapper(vectorMapper)
    # renderer.AddActor(vectorActor)    // uncomment this to show glyphs cones

    # Contours
    colors = vtkNamedColors()

    iso = vtkContourFilter()
    iso.SetInputConnection(reader.GetOutputPort())
    iso.SetValue(0, 175)

    isoMapper = vtkPolyDataMapper()
    isoMapper.SetInputConnection(iso.GetOutputPort())
    isoMapper.ScalarVisibilityOff()

    isoActor = vtkActor()
    isoActor.SetMapper(isoMapper)
    isoActor.GetProperty().SetRepresentationToWireframe()
    isoActor.GetProperty().SetOpacity(0.25)
    isoActor.GetProperty().SetColor(colors.GetColor3d("Red"))
    isoActor.GetProperty().SetLineWidth(5.0)
    renderer.AddActor(isoActor)


def _add_scalar_visualization(reader, dataset, renderer):
    """Add scalar visualization with color mapping."""
    mapper = vtkDataSetMapper()
    mapper.SetInputConnection(reader.GetOutputPort())
    mapper.ScalarVisibilityOn()

    scalarRange = dataset.GetPointData().GetScalars().GetRange()
    mapper.SetScalarRange(scalarRange)

    actor = vtkActor()
    actor.SetMapper(mapper)
    renderer.AddActor(actor)


def _add_basic_visualization(reader, renderer, colors):
    """Add basic mesh visualization without data coloring."""
    mapper = vtkDataSetMapper()
    mapper.SetInputConnection(reader.GetOutputPort())
    mapper.ScalarVisibilityOff()

    actor = vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(colors.GetColor3d("Tomato"))
    actor.GetProperty().SetEdgeColor(colors.GetColor3d("Black"))
    actor.GetProperty().EdgeVisibilityOn()
    renderer.AddActor(actor)


def create_vtk_rendering_context():
    """Create and configure VTK rendering components."""
    renderer = vtkRenderer()
    renderWindow = vtkRenderWindow()
    renderWindow.AddRenderer(renderer)

    renderWindowInteractor = vtkRenderWindowInteractor()
    renderWindowInteractor.SetRenderWindow(renderWindow)
    renderWindowInteractor.GetInteractorStyle().SetCurrentStyleToTrackballCamera()

    return renderer, renderWindow, renderWindowInteractor
