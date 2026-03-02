from collections import namedtuple

from vtkmodules.vtkCommonColor import vtkNamedColors, vtkColorSeries
from vtkmodules.vtkCommonCore import vtkIdList, vtkLookupTable
from vtkmodules.vtkFiltersCore import vtkExtractCells
from vtkmodules.vtkFiltersModeling import vtkOutlineFilter
from vtkmodules.vtkRenderingAnnotation import vtkScalarBarActor
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

from constants import (
    ARRAY_SOLID,
    CELL_PREFIX,
    MATERIAL_ID_ARRAY,
    POINT_PREFIX,
    REPR_POINTS,
    REPR_SURFACE,
    REPR_SURFACE_EDGES,
    REPR_WIREFRAME,
)
from file_utils import detect_and_create_reader


VisualizationResult = namedtuple(
    "VisualizationResult",
    [
        "vol_actor",
        "vol_mapper",
        "vol_dataset",
        "vol_lut",
        "bnd_actor",
        "bnd_mapper",
        "bnd_dataset",
        "bnd_lut",
        "bnd_scalar_bar",
        "full_dataset",
    ],
)


def get_available_arrays(dataset):
    """Return list of VSelect-compatible dicts for all point/cell data arrays."""
    arrays = [{"text": "Solid Color", "value": ARRAY_SOLID}]

    pd = dataset.GetPointData()
    for i in range(pd.GetNumberOfArrays()):
        arr = pd.GetArray(i)
        if arr is not None:
            arrays.append(
                {"text": f"{arr.GetName()} (Point)", "value": f"{POINT_PREFIX}{arr.GetName()}"}
            )

    cd = dataset.GetCellData()
    for i in range(cd.GetNumberOfArrays()):
        arr = cd.GetArray(i)
        if arr is not None:
            arrays.append(
                {"text": f"{arr.GetName()} (Cell)", "value": f"{CELL_PREFIX}{arr.GetName()}"}
            )

    return arrays


def split_by_dimension(dataset):
    """
    Split a mixed unstructured grid into volume and boundary sub-datasets
    based on cell dimension.

    Returns:
        vol_dataset: cells with the maximum cell dimension
        bnd_dataset: cells with dimension < max, or None if all cells share the same dimension
    """
    n = dataset.GetNumberOfCells()
    if n == 0:
        return dataset, None

    max_dim = max(dataset.GetCell(i).GetCellDimension() for i in range(n))

    vol_ids = vtkIdList()
    bnd_ids = vtkIdList()
    for i in range(n):
        dim = dataset.GetCell(i).GetCellDimension()
        if dim == max_dim:
            vol_ids.InsertNextId(i)
        else:
            bnd_ids.InsertNextId(i)

    def extract(id_list):
        ext = vtkExtractCells()
        ext.SetInputData(dataset)
        ext.SetCellList(id_list)
        ext.Update()
        return ext.GetOutput()

    vol_ds = extract(vol_ids)
    bnd_ds = extract(bnd_ids) if bnd_ids.GetNumberOfIds() > 0 else None
    return vol_ds, bnd_ds


def build_categorical_lut(unique_ids):
    """
    Build an indexed (categorical) vtkLookupTable for a list of integer IDs.

    Handles negative IDs (e.g., -1) correctly via indexed lookup — exact mapping,
    no range interpolation.

    Returns:
        lut: vtkLookupTable configured for indexed lookup with annotations
        index_map: dict mapping integer ID -> LUT table index (for future ID editing)
    """
    cs = vtkColorSeries()
    cs.SetColorScheme(vtkColorSeries.BREWER_QUALITATIVE_SET1)
    palette_size = cs.GetNumberOfColors()

    n = len(unique_ids)
    lut = vtkLookupTable()
    lut.SetNumberOfTableValues(n)
    lut.IndexedLookupOn()

    index_map = {}
    for idx, val in enumerate(unique_ids):
        c = cs.GetColor(idx % palette_size)
        lut.SetTableValue(
            idx, c.GetRed() / 255.0, c.GetGreen() / 255.0, c.GetBlue() / 255.0, 1.0
        )
        lut.SetAnnotation(float(val), str(val))
        index_map[val] = idx

    return lut, index_map


def build_scalar_bar(
    lut, title, position=(0.82, 0.05), width=0.08, height=0.35, max_labels=20
):
    """Create a positioned vtkScalarBarActor for the given LUT.

    max_labels caps the number of tick/category labels shown. For categorical
    LUTs with many IDs this prevents the bar from becoming unreadably dense.
    """
    bar = vtkScalarBarActor()
    bar.SetLookupTable(lut)
    bar.SetTitle(title)
    bar.SetOrientationToVertical()
    bar.SetTextPositionToPrecedeScalarBar()
    bar.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
    bar.GetPositionCoordinate().SetValue(position[0], position[1])
    bar.SetWidth(width)
    bar.SetHeight(height)
    bar.SetNumberOfLabels(min(lut.GetNumberOfTableValues(), max_labels))
    bar.GetTitleTextProperty().SetFontSize(10)
    bar.GetLabelTextProperty().SetFontSize(9)
    return bar


def build_visualization(filename, renderer):
    """
    Build split visualization pipeline.

    Returns a VisualizationResult namedtuple. Fields bnd_actor, bnd_mapper,
    bnd_dataset, bnd_lut, and bnd_scalar_bar are None when the file has no
    lower-dimension boundary cells (e.g., grid-1.vtk).

    Note: no scalar bar is created for volume coloring at load time — the
    dynamic _active_coloring_bar in app.py tracks the active Color by selection.
    """
    renderer.RemoveAllViewProps()

    reader = detect_and_create_reader(filename)
    reader.SetFileName(filename)
    reader.Update()

    full_ds = reader.GetOutput()
    print(f"\nDataset Info:")
    print(f"  Type: {full_ds.GetClassName()}")
    print(f"  Number of points: {full_ds.GetNumberOfPoints()}")
    print(f"  Number of cells: {full_ds.GetNumberOfCells()}")

    colors = vtkNamedColors()

    # Outline actor (bounding box of the full mesh)
    outline = vtkOutlineFilter()
    outline.SetInputConnection(reader.GetOutputPort())
    outlineMapper = vtkPolyDataMapper()
    outlineMapper.SetInputConnection(outline.GetOutputPort())
    outlineActor = vtkActor()
    outlineActor.SetMapper(outlineMapper)
    outlineActor.GetProperty().SetColor(colors.GetColor3d("White"))
    renderer.AddActor(outlineActor)

    # Split into volume and boundary sub-datasets by cell dimension
    vol_ds, bnd_ds = split_by_dimension(full_ds)
    print(f"  Volume cells: {vol_ds.GetNumberOfCells()}")
    print(f"  Boundary cells: {bnd_ds.GetNumberOfCells() if bnd_ds else 0}")

    # --- Volume actor ---
    vol_mapper = vtkDataSetMapper()
    vol_mapper.SetInputData(vol_ds)
    vol_mapper.ScalarVisibilityOff()
    vol_actor = vtkActor()
    vol_actor.SetMapper(vol_mapper)
    renderer.AddActor(vol_actor)

    # Pre-build categorical LUT for MaterialID (used by apply_coloring and the dynamic bar)
    vol_lut = None
    vol_mat_arr = vol_ds.GetCellData().GetArray(MATERIAL_ID_ARRAY)
    if vol_mat_arr is not None:
        unique_ids = sorted(
            set(
                int(vol_mat_arr.GetValue(j))
                for j in range(vol_mat_arr.GetNumberOfTuples())
            )
        )
        vol_lut, _ = build_categorical_lut(unique_ids)

    # --- Boundary actor (conditional) ---
    bnd_actor = None
    bnd_mapper = None
    bnd_lut = None
    bnd_scalar_bar = None

    if bnd_ds is not None:
        bnd_mapper = vtkDataSetMapper()
        bnd_mapper.SetInputData(bnd_ds)

        bnd_mat_arr = bnd_ds.GetCellData().GetArray(MATERIAL_ID_ARRAY)
        if bnd_mat_arr is not None:
            unique_bnd_ids = sorted(
                set(
                    int(bnd_mat_arr.GetValue(j))
                    for j in range(bnd_mat_arr.GetNumberOfTuples())
                )
            )
            bnd_lut, _ = build_categorical_lut(unique_bnd_ids)
            bnd_mapper.ScalarVisibilityOn()
            bnd_mapper.SetScalarModeToUseCellFieldData()
            bnd_mapper.SelectColorArray(MATERIAL_ID_ARRAY)
            bnd_mapper.SetLookupTable(bnd_lut)
            bnd_mapper.UseLookupTableScalarRangeOn()

            bnd_scalar_bar = build_scalar_bar(
                bnd_lut, "Boundary ID", position=(0.82, 0.45), width=0.08, height=0.35
            )
            renderer.AddActor(bnd_scalar_bar)
        else:
            bnd_mapper.ScalarVisibilityOff()

        bnd_actor = vtkActor()
        bnd_actor.SetMapper(bnd_mapper)
        bnd_actor.GetProperty().SetLineWidth(3.0)
        renderer.AddActor(bnd_actor)

    renderer.ResetCamera()

    return VisualizationResult(
        vol_actor=vol_actor,
        vol_mapper=vol_mapper,
        vol_dataset=vol_ds,
        vol_lut=vol_lut,
        bnd_actor=bnd_actor,
        bnd_mapper=bnd_mapper,
        bnd_dataset=bnd_ds,
        bnd_lut=bnd_lut,
        bnd_scalar_bar=bnd_scalar_bar,
        full_dataset=full_ds,
    )


def apply_coloring(actor, mapper, dataset, array_value, lut=None):
    """
    Update volume actor coloring based on the selected array value.

    Returns the vtkLookupTable used for scalar coloring, or None for solid color.
    The caller uses the returned LUT to build/update the active scalar bar.

    When array_value is "cell:MaterialID" and a pre-built categorical lut is
    provided, that lut is used (and returned). For all other arrays an explicit
    continuous vtkLookupTable is created so the scalar bar and mapper share the
    same LUT instance.
    """
    colors = vtkNamedColors()

    if array_value == ARRAY_SOLID or array_value is None:
        mapper.ScalarVisibilityOff()
        actor.GetProperty().SetColor(colors.GetColor3d("Tomato"))
        return None

    if array_value == f"{CELL_PREFIX}{MATERIAL_ID_ARRAY}" and lut is not None:
        mapper.ScalarVisibilityOn()
        mapper.SetScalarModeToUseCellFieldData()
        mapper.SelectColorArray(MATERIAL_ID_ARRAY)
        mapper.SetLookupTable(lut)
        mapper.UseLookupTableScalarRangeOn()
        return lut

    if array_value.startswith(POINT_PREFIX):
        name = array_value[len(POINT_PREFIX):]
        arr = dataset.GetPointData().GetArray(name)
        if arr is not None:
            continuous_lut = vtkLookupTable()
            continuous_lut.SetTableRange(arr.GetRange())
            continuous_lut.Build()
            mapper.ScalarVisibilityOn()
            mapper.SetScalarModeToUsePointFieldData()
            mapper.SelectColorArray(name)
            mapper.SetLookupTable(continuous_lut)
            mapper.UseLookupTableScalarRangeOn()
            return continuous_lut

    if array_value.startswith(CELL_PREFIX):
        name = array_value[len(CELL_PREFIX):]
        arr = dataset.GetCellData().GetArray(name)
        if arr is not None:
            continuous_lut = vtkLookupTable()
            continuous_lut.SetTableRange(arr.GetRange())
            continuous_lut.Build()
            mapper.ScalarVisibilityOn()
            mapper.SetScalarModeToUseCellFieldData()
            mapper.SelectColorArray(name)
            mapper.SetLookupTable(continuous_lut)
            mapper.UseLookupTableScalarRangeOn()
            return continuous_lut

    return None


def apply_representation(vol_actor, bnd_actor, representation):
    """
    Update representation for volume and (optionally) boundary actors.

    Boundary cells (lines in 2D, surface quads in 3D) are always rendered as
    surface/lines. Only "Points" mode propagates to the boundary actor.
    """
    prop = vol_actor.GetProperty()
    colors = vtkNamedColors()

    if representation == REPR_SURFACE:
        prop.SetRepresentationToSurface()
        prop.EdgeVisibilityOff()
    elif representation == REPR_SURFACE_EDGES:
        prop.SetRepresentationToSurface()
        prop.EdgeVisibilityOn()
        prop.SetEdgeColor(colors.GetColor3d("Black"))
    elif representation == REPR_WIREFRAME:
        prop.SetRepresentationToWireframe()
        prop.EdgeVisibilityOff()
    elif representation == REPR_POINTS:
        prop.SetRepresentationToPoints()
        prop.SetPointSize(5)

    if bnd_actor is not None:
        bnd_prop = bnd_actor.GetProperty()
        if representation == REPR_POINTS:
            bnd_prop.SetRepresentationToPoints()
            bnd_prop.SetPointSize(5)
        else:
            bnd_prop.SetRepresentationToSurface()
            bnd_prop.EdgeVisibilityOff()


def create_vtk_rendering_context():
    """Create and configure VTK rendering components."""
    renderer = vtkRenderer()
    renderWindow = vtkRenderWindow()
    renderWindow.AddRenderer(renderer)

    renderWindowInteractor = vtkRenderWindowInteractor()
    renderWindowInteractor.SetRenderWindow(renderWindow)
    renderWindowInteractor.GetInteractorStyle().SetCurrentStyleToTrackballCamera()

    return renderer, renderWindow, renderWindowInteractor
