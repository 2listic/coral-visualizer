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

The app is a [Trame](https://trame.readthedocs.io/) web application that serves an interactive 3D VTK visualization in a browser. It uses Vue2 + Vuetify for the UI and VTK for rendering. The primary use case is visualizing deal.II finite element meshes.

**Data flow:**
1. On startup, `app.py` scans `data/` for `.vtk`/`.vtu` files and builds an initial VTK rendering context.
2. The Trame server exposes reactive state to the Vue2 frontend. Key state variables:
   - `available_files` / `selected_file` — file picker
   - `available_arrays` / `selected_array` — color-by picker; array values use the format `"__solid__"`, `"point:ArrayName"`, or `"cell:ArrayName"`
   - `representation` — one of `"Surface"`, `"Surface with Edges"`, `"Wireframe"`, `"Points"`
   - `has_boundary` — controls visibility of the Edit Mode button; true when boundary cells are available
   - `edit_mode` — toggles the edit mode side panel and picking interactor
   - `edit_target` — `"boundary"` or `"volume"` (which cell type the edit actions target)
   - `pick_mode` — `True` = left-click picks cells; `False` = left-click rotates camera
   - `group_select` / `angle_threshold` — flood-fill group selection toggle and angle cutoff (degrees)
   - `selection_count` — number of currently selected cells (display only)
   - `assign_id_value` — integer value to assign to selected cells
   - `save_filename` / `save_status` / `save_status_type` — .vtu save filename and status feedback
   - `error_message` — shown as an overlay alert
3. Each `@state.change(...)` callback in `app.py` calls the appropriate `vtk_pipeline` function and then `ctrl.view_update()` to push the new render to the browser.

**Module responsibilities:**
- `app.py` — entry point, argument parsing, Trame server init, state management, `@state.change` callbacks
- `vtk_pipeline.py` — VTK rendering logic (actor/mapper creation, coloring, representation, LUT building)
- `mesh_edit.py` — mesh cell editing: boundary extraction, interactive cell selection (boundary and volume), BoundaryID/MaterialID assignment, save as .vtu. ManifoldID values are preserved but not edited.
- `scalar_bars.py` — `ScalarBarManager`: owns the two scalar bar actors (active coloring + boundary ID) and their renderer lifecycle
- `interactor.py` — `PickInteractorManager`: owns the `LeftButton` observer lifecycle for cell-picking in edit mode
- `file_utils.py` — format detection and `data/` folder scanning
- `ui.py` — Trame/Vuetify layout (toolbar, VTK viewport, edit mode drawer, error overlay)
- `constants.py` — string sentinels/prefixes, representation mode names, known array names, deal.II default ID values

**VTK pipeline (`vtk_pipeline.py`):**

`build_visualization(filename, renderer)` — clears the renderer, reads the file, splits the dataset by cell dimension into volume and boundary sub-datasets, builds actors for each, and pre-builds categorical LUTs. Returns a `VisualizationResult` namedtuple with fields: `vol_actor`, `vol_mapper`, `vol_dataset`, `vol_luts`, `bnd_actor`, `bnd_mapper`, `bnd_dataset`, `bnd_luts`, `full_dataset`. The `bnd_*` fields are `None`/empty when no lower-dimension cells exist. Coloring is applied by the caller (`app.py`) after this returns.

`split_by_dimension(dataset)` — splits a mixed unstructured grid into volume cells (max dimension) and boundary cells (lower dimension) using `vtkExtractCells`. Returns `(vol_dataset, bnd_dataset)` where `bnd_dataset` may be `None`.

`apply_coloring(actor, mapper, dataset, array_value, luts=None)` — sets mapper to solid color (`Tomato`) or enables scalar coloring. For arrays in `CATEGORICAL_CELL_ARRAYS` uses the pre-built categorical LUT; for all other arrays builds a continuous `vtkLookupTable`. Returns the active LUT (or `None` for solid color).

`apply_representation(vol_actor, bnd_actor, representation)` — sets surface/wireframe/points mode; boundary cells always render as surface/lines except in Points mode.

`get_max_cell_dimension(dataset)` — returns the maximum cell dimension present in a dataset. Shared helper used by `split_by_dimension` and `mesh_edit.py`.

`build_categorical_lut(unique_ids)` — builds an indexed `vtkLookupTable` with `BREWER_QUALITATIVE_SET1` palette for categorical integer data (handles negative IDs via indexed lookup). Returns `(lut, index_map)`.

`apply_categorical_coloring(mapper, dataset, array_name)` — builds a categorical LUT from the unique IDs in `array_name` and wires `mapper`. Returns `(lut, index_map)`, or `(None, None)` if the array is absent.

**Boundary editing (`mesh_edit.py`):**

`BoundaryEditState` — dataclass holding all mutable edit state: full/vol/bnd datasets, actors, mappers, pickers, selection sets, adjacency graph, cell normals, and observer tags.

`extract_all_boundary_subcells(full_dataset)` — finds exterior boundary sub-cells by iterating volume cell edges (2D) or faces (3D) and selecting those shared by exactly one volume cell. Also classifies cells in the file as volume vs boundary by dimension (same logic as `split_by_dimension` but returns index lists instead of extracted datasets).

`build_merged_boundary_dataset(full_dataset, file_bnd_indices, extracted_subcells)` — builds a `vtkUnstructuredGrid` containing all boundary cells (exterior sub-cells + interior file boundary markers), with `MaterialID` and `ManifoldID` arrays. Exterior sub-cells that match file boundary cells inherit their IDs; others get defaults.

`build_adjacency_graph(bnd_dataset)` / `compute_cell_normals(bnd_dataset)` — precomputed adjacency and normal data used by `flood_select` for group selection.

`flood_select(start_cell, adjacency, normals, angle_threshold_deg)` — BFS flood-fill that selects connected cells whose normals are within `angle_threshold_deg` of the seed cell's normal (uses `abs(dot)` to handle winding inconsistencies).

`save_as_vtu(edit_state, output_path)` — reconstructs the full mesh (volume cells + edited boundary cells) and writes `.vtu`.

In edit mode, left-click picks boundary or volume cells via `vtkCellPicker`. The default interactor style's `LeftButtonPressEvent` observers are removed to prevent camera rotation on left-click; middle/right-click camera controls remain. `pick_mode=False` re-enables left-click camera rotation by forwarding to the interactor style.

**Important VTK patterns:**
- When modifying VTK array values directly (e.g. `arr.SetValue()`), call `dataset.Modified()` afterward to bump the MTime so downstream mappers re-render.
- State changes inside VTK observer callbacks (outside Trame's request cycle) require `state.flush()` to push updates to the browser.

**File format detection (`file_utils.py`):**

`.vtu` → `vtkXMLUnstructuredGridReader`. `.vtk` (legacy) → reads first 500 bytes to detect dataset type, selects appropriate reader. Falls back to `vtkUnstructuredGridReader`.

**Adding a new VTK format:** add the extension to `supported_extensions` in `file_utils.py` and add reader selection logic in `detect_and_create_reader()`.
