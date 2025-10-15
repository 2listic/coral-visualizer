import argparse
import os
from trame.app import get_server
from trame.ui.vuetify import SinglePageLayout
from trame.widgets import vtk, vuetify

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


from vtkmodules.vtkIOLegacy import (
    vtkStructuredPointsReader,
    vtkUnstructuredGridReader,
    vtkPolyDataReader,
)
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

# Required for rendering initialization, not necessary for
# local rendering, but doesn't hurt to include it
import vtkmodules.vtkRenderingOpenGL2  # noqa

CURRENT_DIRECTORY = os.path.abspath(os.path.dirname(__file__))

# -----------------------------------------------------------------------------
# Command-line arguments
# -----------------------------------------------------------------------------

parser = argparse.ArgumentParser(description="Flexible VTK Visualization with Trame")
parser.add_argument(
    "--file",
    default=os.path.join(CURRENT_DIRECTORY, "data/grid-1.vtk"),
    help="Path to VTK file (default: data/grid-1.vtk)",
)
# Parse known args and let trame handle the rest (--port, --host, --debug, etc.)
args, unknown = parser.parse_known_args()

# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------


def get_vtk_files_from_data_folder():
    """Scan the data folder and return list of VTK files."""
    data_folder = os.path.join(CURRENT_DIRECTORY, "data")
    print(f"data_folder: {data_folder}")
    
    if not os.path.exists(data_folder):
        print(f"Warning: Data folder not found: {data_folder}")
        return []
    
    vtk_files = []
    for filename in os.listdir(data_folder):
        if filename.lower().endswith('.vtk'):
            full_path = os.path.join(data_folder, filename)
            vtk_files.append({
                "text": filename,
                "value": full_path
            })
    
    # Sort alphabetically
    vtk_files.sort(key=lambda x: x["text"])
    return vtk_files


def detect_and_create_reader(filename):
    """Detect VTK legacy file type and return appropriate reader."""
    ext = os.path.splitext(filename)[1].lower()

    if ext != ".vtk":
        raise ValueError(f"Only .vtk files are supported. Got: {ext}")

    # Peek at file content to determine dataset type
    with open(filename, "r") as f:
        for line in f:
            line = line.strip().upper()
            if "DATASET" in line:
                if "STRUCTURED_POINTS" in line or "IMAGE_DATA" in line:
                    return vtkStructuredPointsReader()
                elif "UNSTRUCTURED_GRID" in line:
                    return vtkUnstructuredGridReader()
                elif "POLYDATA" in line:
                    return vtkPolyDataReader()
                break

    # Default fallback
    print(f"Warning: Could not detect dataset type, trying UnstructuredGridReader")
    return vtkUnstructuredGridReader()


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
        renderer.AddActor(vectorActor)

        # Contours
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
        renderer.AddActor(isoActor)

    elif has_scalar_data(dataset):
        print("\nUsing SCALAR visualization (colored by scalar values)\n")

        # Simple visualization with scalar coloring
        mapper = vtkDataSetMapper()
        mapper.SetInputConnection(reader.GetOutputPort())
        mapper.ScalarVisibilityOn()

        scalarRange = dataset.GetPointData().GetScalars().GetRange()
        mapper.SetScalarRange(scalarRange)

        actor = vtkActor()
        actor.SetMapper(mapper)
        renderer.AddActor(actor)

    else:
        print("\nUsing BASIC visualization (wireframe/surface)\n")

        # Basic mesh visualization without data
        mapper = vtkDataSetMapper()
        mapper.SetInputConnection(reader.GetOutputPort())
        mapper.ScalarVisibilityOff()

        actor = vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(colors.GetColor3d("Tomato"))
        actor.GetProperty().SetEdgeColor(colors.GetColor3d("Black"))
        actor.GetProperty().EdgeVisibilityOn()
        renderer.AddActor(actor)

    renderer.ResetCamera()


# -----------------------------------------------------------------------------
# VTK pipeline
# -----------------------------------------------------------------------------

renderer = vtkRenderer()
renderWindow = vtkRenderWindow()
renderWindow.AddRenderer(renderer)

renderWindowInteractor = vtkRenderWindowInteractor()
renderWindowInteractor.SetRenderWindow(renderWindow)
renderWindowInteractor.GetInteractorStyle().SetCurrentStyleToTrackballCamera()

# Build initial visualization
build_visualization(args.file, renderer)
renderWindow.Render()

# -----------------------------------------------------------------------------
# GUI
# -----------------------------------------------------------------------------

server = get_server(client_type="vue2")
ctrl = server.controller
state, ctrl = server.state, server.controller

# State for file selection
available_files = get_vtk_files_from_data_folder()
state.available_files = available_files
state.selected_file = args.file if os.path.exists(args.file) else (available_files[0]["value"] if available_files else "")
state.error_message = ""


@state.change("selected_file")
def on_file_change(selected_file, **kwargs):
    """Automatically load the selected file when dropdown changes."""
    if selected_file and os.path.exists(selected_file):
        try:
            print(f"\nLoading file: {selected_file}")
            build_visualization(selected_file, renderer)
            renderWindow.Render()
            ctrl.view_update()
            state.error_message = ""
        except Exception as e:
            state.error_message = f"Error loading file: {str(e)}"
            print(f"Error: {e}")


with SinglePageLayout(server) as layout:
    layout.title.set_text("VTK Simple Viewer")
    layout.icon.hide()

    with layout.toolbar:
        vuetify.VSpacer()
        vuetify.VSelect(
            v_model=("selected_file",),
            items=("available_files",),
            label="Select VTK File",
            hide_details=True,
            dense=True,
            outlined=True,
            style="max-width: 400px;",
            classes="mr-2",
        )

    with layout.content:
        with vuetify.VContainer(
            fluid=True,
            classes="pa-0 fill-height",
            style="position: relative;",
        ):
            # Error message as overlay
            vuetify.VAlert(
                v_show=("error_message",),
                type="error",
                dense=True,
                dismissible=True,
                v_model=("error_message",),
                children=("{{ error_message }}",),
                style="position: absolute; top: 10px; left: 10px; right: 10px; z-index: 1000;",
            )

            # VTK view
            view = vtk.VtkRemoteView(
                renderWindow,
                ref="view",
                style="width: 100%; height: 100%;",
            )
            ctrl.view_update = view.update


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    # Pass any unknown arguments to trame server.start()
    # This allows using --port, --host, --debug, etc.
    server.start()