from vtkmodules.vtkCommonColor import vtkNamedColors
from vtkmodules.vtkCommonCore import vtkIntArray, vtkLookupTable
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
    vtkCellPicker,
    vtkPolyDataMapper,
    vtkDataSetMapper,
    vtkRenderer,
    vtkRenderWindow,
    vtkRenderWindowInteractor,
)

# Required for interactor initialization
from vtkmodules.vtkInteractionStyle import (
    vtkInteractorStyleSwitch,  # noqa
    vtkInteractorStyleUser,
)

# Required for rendering initialization
import vtkmodules.vtkRenderingOpenGL2  # noqa

from file_utils import detect_and_create_reader


# Shared pipeline state — populated by create_vtk_rendering_context() and
# build_visualization(), read by handle_left_click() and on_tag_mode_change().
_pipeline_state = {
    "reader": None,          # active reader kept alive to prevent GC of dataset
    "dataset": None,         # live vtkDataSet modified in-place for tags
    "tag_actor": None,       # vtkActor colored by BoundaryID
    "tag_mapper": None,      # vtkDataSetMapper for the tag actor
    "tag_lut": None,         # discrete vtkLookupTable (index 0 = untagged gray)
    "style_navigate": None,  # vtkInteractorStyleSwitch (camera navigation)
    "style_tag": None,       # vtkInteractorStyleUser (no-op, blocks camera on click)
    "picker": None,          # vtkCellPicker — created once, reused
    "state": None,           # Trame server state (set by app.py after server init)
    "ctrl": None,            # Trame server controller (set by app.py after server init)
}


def ensure_active_arrays(dataset):
    """Promote the first available arrays to active scalar/vector if none are set."""
    pd = dataset.GetPointData()
    if pd is None:
        return
    if pd.GetScalars() is None:
        for i in range(pd.GetNumberOfArrays()):
            arr = pd.GetArray(i)
            if arr is not None and arr.GetNumberOfComponents() == 1:
                pd.SetActiveScalars(arr.GetName())
                print(f"  Active scalar set to: {arr.GetName()!r}")
                break
    if pd.GetVectors() is None:
        for i in range(pd.GetNumberOfArrays()):
            arr = pd.GetArray(i)
            if arr is not None and arr.GetNumberOfComponents() == 3:
                pd.SetActiveVectors(arr.GetName())
                print(f"  Active vector set to: {arr.GetName()!r}")
                break


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


def _initialize_boundary_id_array(dataset):
    """Create/reset the BoundaryID CellData integer array (all zeros) on the dataset."""
    n_cells = dataset.GetNumberOfCells()
    arr = vtkIntArray()
    arr.SetName("BoundaryID")
    arr.SetNumberOfTuples(n_cells)
    arr.Fill(0)
    dataset.GetCellData().AddArray(arr)  # replaces existing array of same name


def _build_discrete_lut(max_tags=16):
    """Return a discrete vtkLookupTable: index 0 = gray (untagged), 1..N = distinct colors."""
    lut = vtkLookupTable()
    lut.SetNumberOfTableValues(max_tags + 1)
    lut.SetRange(0, max_tags)
    lut.Build()

    # Index 0: untagged — medium gray
    lut.SetTableValue(0, 0.65, 0.65, 0.65, 1.0)

    # Indices 1–16: perceptually distinct colors (ColorBrewer-inspired)
    colors = [
        (0.894, 0.102, 0.110, 1.0),  # 1  red
        (0.216, 0.494, 0.722, 1.0),  # 2  blue
        (0.302, 0.686, 0.290, 1.0),  # 3  green
        (0.596, 0.306, 0.639, 1.0),  # 4  purple
        (1.000, 0.498, 0.000, 1.0),  # 5  orange
        (1.000, 1.000, 0.200, 1.0),  # 6  yellow
        (0.651, 0.337, 0.157, 1.0),  # 7  brown
        (0.969, 0.506, 0.749, 1.0),  # 8  pink
        (0.000, 0.749, 0.749, 1.0),  # 9  cyan
        (0.498, 0.498, 0.000, 1.0),  # 10 olive
        (0.000, 0.498, 0.498, 1.0),  # 11 teal
        (0.498, 0.000, 0.498, 1.0),  # 12 maroon-purple
        (0.749, 0.000, 0.000, 1.0),  # 13 dark red
        (0.000, 0.000, 0.749, 1.0),  # 14 dark blue
        (0.000, 0.749, 0.000, 1.0),  # 15 dark green
        (0.400, 0.400, 0.400, 1.0),  # 16 dark gray
    ]
    for i, rgba in enumerate(colors[:max_tags], start=1):
        lut.SetTableValue(i, *rgba)

    return lut


def _add_tag_visualization(dataset, renderer):
    """Add a BoundaryID-colored actor (hidden by default) to the renderer."""
    lut = _build_discrete_lut()
    _pipeline_state["tag_lut"] = lut

    mapper = vtkDataSetMapper()
    mapper.SetInputData(dataset)
    mapper.SetScalarModeToUseCellFieldData()
    mapper.SelectColorArray("BoundaryID")
    mapper.SetScalarRange(0, 16)
    mapper.SetLookupTable(lut)
    mapper.ScalarVisibilityOn()
    mapper.UseLookupTableScalarRangeOn()
    # Offset this surface slightly in front to avoid z-fighting with the main actor
    mapper.SetResolveCoincidentTopologyToPolygonOffset()
    mapper.SetResolveCoincidentTopologyPolygonOffsetParameters(-1.0, -1.0)
    _pipeline_state["tag_mapper"] = mapper

    actor = vtkActor()
    actor.SetMapper(mapper)
    actor.VisibilityOff()  # hidden until tag mode is activated
    _pipeline_state["tag_actor"] = actor

    renderer.AddActor(actor)


def _update_tag_actor():
    """Signal the tag mapper to re-read the BoundaryID array after a cell was tagged."""
    mapper = _pipeline_state.get("tag_mapper")
    if mapper is not None:
        mapper.Update()


def handle_left_click(interactor, _event):
    """
    VTK observer callback (priority 1.0 > style default 0.0).
    Only acts when tag_mode is True; otherwise lets the camera style handle the event.
    The interactor style is already swapped to vtkInteractorStyleUser in tag mode,
    so no AbortFlagOn() is needed to block camera rotation.
    """
    state = _pipeline_state.get("state")
    ctrl = _pipeline_state.get("ctrl")
    if state is None or not state.tag_mode:
        return

    x, y = interactor.GetEventPosition()
    renderer = interactor.GetRenderWindow().GetRenderers().GetFirstRenderer()
    picker = _pipeline_state["picker"]

    if picker.Pick(x, y, 0, renderer):
        cell_id = picker.GetCellId()
        if cell_id >= 0:
            dataset = _pipeline_state.get("dataset")
            if dataset is not None:
                arr = dataset.GetCellData().GetArray("BoundaryID")
                if arr is not None:
                    arr.SetValue(cell_id, int(state.active_tag_id))
                    dataset.GetCellData().Modified()
                    dataset.Modified()
                    _update_tag_actor()
                    interactor.GetRenderWindow().Render()
                    if ctrl is not None:
                        ctrl.view_update()


def build_visualization(filename, renderer):
    """Build visualization pipeline for the given file."""
    # Clear existing actors
    renderer.RemoveAllViewProps()

    # Read the data
    reader = detect_and_create_reader(filename)
    reader.SetFileName(filename)
    reader.Update()

    # Get the output dataset and ensure active arrays are marked
    dataset = reader.GetOutput()
    ensure_active_arrays(dataset)
    print(f"\nDataset Info:")
    print(f"  Type: {dataset.GetClassName()}")
    print(f"  Number of points: {dataset.GetNumberOfPoints()}")
    print(f"  Number of cells: {dataset.GetNumberOfCells()}")
    print(f"  Has vectors: {has_vector_data(dataset)}")
    print(f"  Has scalars: {has_scalar_data(dataset)}")

    # Store pipeline references and reset tag state
    _pipeline_state["reader"] = reader
    _pipeline_state["dataset"] = dataset
    _pipeline_state["tag_actor"] = None
    _pipeline_state["tag_mapper"] = None
    _pipeline_state["tag_lut"] = None

    # Initialize BoundaryID array (resets tags on every file load)
    _initialize_boundary_id_array(dataset)

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

    # Always add the tag visualization layer (hidden by default)
    _add_tag_visualization(dataset, renderer)

    # If tag mode was already active, make the new tag actor visible immediately
    state = _pipeline_state.get("state")
    if state is not None and state.tag_mode and _pipeline_state["tag_actor"] is not None:
        _pipeline_state["tag_actor"].VisibilityOn()

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

    # Store styles so app.py can swap between them on tag_mode change
    _pipeline_state["style_navigate"] = renderWindowInteractor.GetInteractorStyle()
    _pipeline_state["style_tag"] = vtkInteractorStyleUser()

    # Create the cell picker once — it will be reused for every click in tag mode
    picker = vtkCellPicker()
    picker.SetTolerance(0.005)
    _pipeline_state["picker"] = picker

    return renderer, renderWindow, renderWindowInteractor
