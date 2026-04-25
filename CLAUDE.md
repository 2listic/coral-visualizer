# CLAUDE.md

Operational onboarding for Claude/Codex/other agents working in this repository.

## First Read

This is a Trame/Vuetify mesh visualizer with two backends:

- `vtk`: legacy local VTK rendering path.
- `paraview`: current primary path for pipeline, filters, edit sessions, selection, saving, and display/color controls.

Most recent feature work is in the ParaView backend. When reproducing user-reported UI behavior, prefer the ParaView environment and `--backend paraview` unless the user explicitly says VTK.

## Environment

### Recommended ParaView Environment

Use the conda environment `coral-paraview`. On this machine it is normally available at:

```bash
~/anaconda3/envs/coral-paraview/bin/python
~/anaconda3/envs/coral-paraview/bin/pytest
```

Create it if missing:

```bash
./tools/setup_pv_env.sh
```

This installs ParaView from `conda-forge`. Do not expect ParaView to work from the lightweight `.venv`/`uv` setup.

Run the ParaView app:

```bash
~/anaconda3/envs/coral-paraview/bin/python app.py --backend paraview --file test_data/square.vtk --data-directory test_data --host 127.0.0.1 --port 8008
```

`--devtools` is enabled by default for now. It enables Trame hot reload and
ParaView view/selection diagnostics. Use `--no-devtools` for quiet
production-like runs. The older `--dev` flag is a compatibility alias.

Or with conda:

```bash
conda run -n coral-paraview python app.py --backend paraview
```

### Lightweight VTK/Unit-Test Environment

For pure unit tests that do not import ParaView, the default Python may work if requirements are installed:

```bash
uv venv
source .venv/bin/activate
uv pip install -r setup/requirements.txt -r setup/requirements-dev.txt
```

Use this only for non-ParaView work. If a test imports `paraview` or uses Playwright e2e against the ParaView backend, use `coral-paraview`.

### Playwright

E2E tests use Chromium through Playwright. If browser binaries are missing:

```bash
~/anaconda3/envs/coral-paraview/bin/python -m playwright install chromium
```

Visible browser debugging:

```bash
~/anaconda3/envs/coral-paraview/bin/pytest tests/test_e2e_edit_selection_playwright.py --show-browser
```

Optional app log streaming during e2e:

```bash
E2E_STREAM_APP_LOGS=1 ~/anaconda3/envs/coral-paraview/bin/pytest -q tests/test_e2e_edit_selection_playwright.py
```

## Common Commands

Run unit/controller tests:

```bash
pytest -q tests/test_paraview_backend.py tests/test_paraview_runtime.py tests/test_paraview_controllers.py tests/test_state_setup.py
```

Run ParaView e2e tests:

```bash
~/anaconda3/envs/coral-paraview/bin/pytest -q tests/test_e2e_edit_selection_playwright.py
```

Run a single e2e:

```bash
~/anaconda3/envs/coral-paraview/bin/pytest -q tests/test_e2e_edit_selection_playwright.py::test_paraview_display_color_scale_visibility_survives_rescale
```

Formatting/linting, when requested:

```bash
black .
ruff check .
ruff check --fix .
```

Docker:

```bash
docker build -t coral-visualizer-standalone .
docker run -it --rm -p 8008:8080 coral-visualizer-standalone
```

## Git Conventions

- Do not add `Co-Authored-By: Claude` trailers.
- There may be untracked generated data or local env folders (`.pvenv`, `.pv-conda-bootstrap`, `data/*.vtu`, uploads). Do not add them unless the user explicitly asks.
- Commit only files relevant to the current task.

## Current Architecture

### Entry And Registration

- `app.py`: entry point and server/runtime construction.
- `app_config.py`: CLI parsing, devtools/hot-reload setup, and backend selection.
- `handler_registration.py`: wires backend-specific controllers and state handlers.
- `state_setup.py`: initializes all Trame state. If adding UI controls, add defaults here.
- `state_handlers.py`: shared `@state.change(...)` callbacks for selected file, color-by, representation, active pipeline node, interaction quality, edit mode.
- `view_controls.py`: central wrapper for Trame view update callbacks and optional ParaView diagnostics.

### ParaView Backend Path

- `paraview_backend.py`: owns ParaView sources/displays, pipeline nodes, filters, coloring, display controls, picking, selection overlays, saving/export.
- `paraview_runtime.py`: synchronizes backend state into Trame state, handles render pushes, edit-session overlay sync, event normalization.
- `paraview_controllers.py`: user actions from the UI: pipeline actions, filters, edit sessions, selection, field creation, display/color controls.
- `paraview_property_inspector.py`: collects editable ParaView proxy properties for Source/Display tabs.
- `selection_debug.py`: builds and emits optional edit-selection debug payloads.

Important ParaView UI state:

- `available_arrays` / `selected_array`: color-by selector. Values are `__solid__`, `point:ArrayName`, or `cell:ArrayName`.
- `representation`: `Surface`, `Surface with Edges`, `Wireframe`, `Points`.
- `pipeline_items` / `active_pipeline_item`: left pipeline tree and active node.
- `source_properties` / `display_properties`: generated editable proxy properties.
- `color_controls_*`: dedicated color-bar controls under Display -> Advanced Display Controls.
- `edit_session_active`, `edit_geometry_mode`, `edit_field_choice`, `edit_selection_mode`, `selection_count`: edit workflow.

### VTK Legacy Path

- `vtk_runtime.py`, `vtk_controllers.py`, `vtk_pipeline.py`, `mesh_edit.py`, `interactor.py`, `scalar_bars.py`.
- Keep this path working, but do not model new ParaView features after it unless the user asks for VTK parity.

### UI

- `ui.py`: all Trame/Vuetify layout.
- ParaView main areas:
  - top toolbar: global actions.
  - left drawer: pipeline browser and file actions.
  - right inspector tabs: Display, Properties, Information, Edit Tools.
- Avoid bringing back removed controls. For example, edit-field creation is via `Select field -> Create new...`, not a separate `Create New Field` button.

## Important Current Behaviors

### Edit Field Creation

In ParaView edit mode, field creation is:

`Select field -> Create new... -> dialog`

The dialog supports Cell data and Point data arrays. Selecting a point field forces point edit mode; selecting a cell field uses volume/surface/edge modes.

### Replace Selection

`Selection mode = Replace` means:

- empty new pick: do not change selection.
- non-empty new pick: replace the previous edit selection entirely.

Do not implement replace as a toggle. ParaView native payloads can contain toggled selection IDs, so `paraview_runtime.normalize_edit_selection_ids()` prefers event coordinates when available and the backend repicks cleanly.

Selection overlays can interfere with native picking. `paraview_backend.py` clears transient edit-selection overlays before pick queries.

### Display Color Controls

Display -> Advanced Display Controls -> Color Bar contains:

- color map preset.
- manual min/max and rescale to data.
- show/hide color scale.
- show/hide orientation axes.
- interpret values as categories.

The color-scale visibility is user state. Range/preset/category updates must preserve it and reapply it after touching the lookup table.

## Tests To Prefer

For field creation and replace selection:

```bash
~/anaconda3/envs/coral-paraview/bin/pytest -q tests/test_e2e_edit_selection_playwright.py::test_paraview_point_field_replace_box_selection_does_not_toggle_overlap
```

For color bar controls:

```bash
~/anaconda3/envs/coral-paraview/bin/pytest -q tests/test_e2e_edit_selection_playwright.py::test_paraview_display_color_scale_visibility_survives_rescale
```

For backend/controller coverage:

```bash
pytest -q tests/test_paraview_backend.py tests/test_paraview_runtime.py tests/test_paraview_controllers.py tests/test_state_setup.py
```

## Debugging Notes

- E2E test meshes live in `test_data/`; use them instead of writing into `data/` unless needed.
- `tests/test_e2e_edit_selection_playwright.py` has helpers for normalized box drags and switch state checks.
- Selection e2e logs can include `[selection-record] ...`; use `E2E_STREAM_APP_LOGS=1` to see app output live.
- `tools/inspect_vtu.py` can inspect binary/compressed VTU output:

```bash
~/anaconda3/envs/coral-paraview/bin/python tools/inspect_vtu.py test_data/output.vtu
```

## File Format Notes

`file_utils.py` detects `.vtk`, `.vtu`, `.vtp`, and related supported mesh formats. Add new extensions there and in relevant tests.

`--data-directory` controls both scanned input files and save destinations for exported/edit-session results.
