# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Setup:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r setup/requirements.txt
```

**Run the app:**
```bash
source .venv/bin/activate
python3 app.py
# With options:
python3 app.py --file data/grid-1.vtk --port 1234
```

**Format code:**
```bash
black app.py  # or any other file
```

**Docker:**
```bash
docker build -t trame-simple-visualizer .
docker run -it --rm -p 8008:80 trame-simple-visualizer
```

There are no automated tests in this project.

## Architecture

The app is a [Trame](https://trame.readthedocs.io/) web application that serves an interactive 3D VTK visualization in a browser. It uses Vue2 + Vuetify for the UI and VTK for rendering.

**Data flow:**
1. On startup, `app.py` scans `data/` for `.vtk`/`.vtu` files and builds an initial VTK rendering context.
2. The Trame server exposes reactive state to the Vue2 frontend. Key state variables:
   - `available_files` / `selected_file` — file picker
   - `available_arrays` / `selected_array` — color-by picker; array values use the format `"__solid__"`, `"point:ArrayName"`, or `"cell:ArrayName"`
   - `representation` — one of `"Surface"`, `"Surface with Edges"`, `"Wireframe"`, `"Points"`
   - `show_boundary` — toggle visibility of boundary cells actor and its scalar bar
   - `show_scalar_bars` — toggle all scalar bar legend visibility
   - `has_boundary` — whether the loaded file has lower-dimension boundary cells (drives UI)
   - `error_message` — shown as an overlay alert
3. Each `@state.change(...)` callback in `app.py` calls the appropriate `vtk_pipeline` function and then `ctrl.view_update()` to push the new render to the browser.

**VTK pipeline (`vtk_pipeline.py`):**

`create_vtk_rendering_context()` — creates `(renderer, renderWindow, renderWindowInteractor)` with trackball camera style.

`build_visualization(filename, renderer)` — clears the renderer, reads the file, splits the dataset by cell dimension into volume and boundary sub-datasets, builds actors for each, and pre-builds categorical LUTs for `MaterialID`. Returns a `VisualizationResult` namedtuple with fields: `vol_actor`, `vol_mapper`, `vol_dataset`, `vol_lut`, `bnd_actor`, `bnd_mapper`, `bnd_dataset`, `bnd_lut`, `bnd_scalar_bar`, `full_dataset`. The `bnd_*` fields are `None` when no lower-dimension cells exist.

`split_by_dimension(dataset)` — splits a mixed unstructured grid into volume cells (max dimension) and boundary cells (lower dimension). Returns `(vol_dataset, bnd_dataset)` where `bnd_dataset` may be `None`.

`get_available_arrays(dataset)` — introspects point and cell data arrays on the full dataset; returns `{"text": ..., "value": ...}` dicts for populating the "Color by" dropdown.

`apply_coloring(actor, mapper, dataset, array_value, lut=None)` — sets mapper to solid color (`Tomato`) or enables scalar coloring. For `cell:MaterialID` uses the pre-built categorical LUT passed in; for all other arrays builds a continuous `vtkLookupTable`. Returns the active LUT (or `None` for solid color) so the caller can build the scalar bar.

`apply_representation(vol_actor, bnd_actor, representation)` — sets surface/wireframe/points mode; boundary cells always render as surface/lines except in Points mode.

`build_categorical_lut(unique_ids)` — builds an indexed `vtkLookupTable` with `vtkColorSeries.BREWER_QUALITATIVE_SET1` palette for categorical integer data (handles negative IDs correctly via indexed lookup).

`build_scalar_bar(lut, title, ...)` — creates a positioned `vtkScalarBarActor`.

**File format detection (`file_utils.py`):**

`.vtu` → `vtkXMLUnstructuredGridReader` directly.

`.vtk` (legacy) → reads first 500 bytes, finds the `DATASET` line, and selects among `vtkStructuredPointsReader`, `vtkUnstructuredGridReader`, or `vtkPolyDataReader`. Falls back to `vtkUnstructuredGridReader` if type cannot be determined.

**Module responsibilities:**
- [app.py](app.py) — entry point, argument parsing, Trame server init, state management, `@state.change` callbacks, scalar bar lifecycle (`_active_coloring_bar`)
- [vtk_pipeline.py](vtk_pipeline.py) — all VTK rendering logic
- [file_utils.py](file_utils.py) — format detection and `data/` folder scanning
- [ui.py](ui.py) — Trame/Vuetify layout (toolbar dropdowns, VTK viewport, error overlay)
- [constants.py](constants.py) — string sentinels/prefixes (`ARRAY_SOLID`, `POINT_PREFIX`, `CELL_PREFIX`, `MATERIAL_ID_ARRAY`) and representation mode names

**Adding a new VTK format:** add the extension to `supported_extensions` in `file_utils.py` and add reader selection logic in `detect_and_create_reader()`.
