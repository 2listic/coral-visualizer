# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Trame/Vuetify mesh visualizer and editor built on ParaView (the only rendering backend — VTK standalone was removed). Supports pipeline construction, filters, edit sessions (volume/surface/point), selection, saving, and advanced display/color controls. Deployment target: HPC server with browser-only thin client.

## Environment

Use the conda environment `coral-paraview`. Create it if missing:

```bash
./tools/setup_pv_env.sh
```

This installs ParaView from `conda-forge`, pip-installs all Python dev dependencies, and installs the Playwright Chromium browser.

Use `conda run -n coral-paraview <command>` or find the env root with `conda info --envs` to get the full path.

Run the app:

```bash
conda run -n coral-paraview python app.py --data-directory test_data --host 127.0.0.1 --port 8008
```

`--devtools` is enabled by default. It enables Trame hot reload and ParaView view/selection diagnostics. Use `--no-devtools` for quiet production-like runs. The older `--dev` flag is a compatibility alias.

### Playwright

E2E tests use Chromium through Playwright. The browser is installed automatically
by `./tools/setup_pv_env.sh`. If it needs to be reinstalled:

```bash
conda run -n coral-paraview python -m playwright install chromium
```

Visible browser debugging:

```bash
conda run -n coral-paraview pytest tests/test_e2e_edit_selection_playwright.py --show-browser
```

Add `--slow-mo <ms>` to insert a delay between Playwright actions:

```bash
conda run -n coral-paraview pytest tests/test_e2e_edit_selection_playwright.py --show-browser --slow-mo 500
```

Optional app log streaming during e2e:

```bash
E2E_STREAM_APP_LOGS=1 conda run -n coral-paraview pytest -q tests/test_e2e_edit_selection_playwright.py
```

## Common Commands

Run unit tests (excludes e2e):

```bash
conda run -n coral-paraview pytest -q tests/ --ignore-glob=tests/test_e2e*.py
```

Run all tests (unit + e2e):

```bash
conda run -n coral-paraview pytest -q
```

Run a single e2e test:

```bash
conda run -n coral-paraview pytest -q tests/test_e2e_edit_selection_playwright.py::test_paraview_display_color_scale_visibility_survives_rescale
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

### Pre-commit

On every `git commit`, pre-commit runs formatting (`black`), linting (`ruff`),
and unit tests (`pytest`). E2E tests are excluded from the hook — run them
manually with the conda env.

The pytest hook uses `language: unsupported`, which means it picks up whatever
`pytest` is on `$PATH`. The `coral-paraview` conda env must be active before
committing, or use:

```bash
conda run -n coral-paraview git commit
```

## Git and PR Conventions

- Do not add `Co-Authored-By: Claude` trailers.
- There may be untracked generated data or local env folders (`.pvenv`, `.pv-conda-bootstrap`, `data/*.vtu`, uploads). Do not add them unless the user explicitly asks.
- Commit only files relevant to the current task.

### PR body format

```
## Overview
<narrative context — why this change, what problem it solves>

## Summary
<bullet points of what changed>

## Test plan
<markdown checklist>
```

See PRs #27, #28, #29 for examples.

### Base branch

If the current branch was cut from a feature branch (not from `main`), open the PR against that feature branch as the base so reviewers see only the unique diff. Add a note at the top of the Overview:

> **Note:** this PR targets `<base-branch>` rather than `main` because `<current-branch>` was branched from it.

Open work is tracked in GitHub issues. Before opening a PR, check for related open issues to reference or close.

[docs/archived/MIGRATION_LOG.md](docs/archived/MIGRATION_LOG.md) is a historical record of the VTK→ParaView migration, which has landed. Do not add entries to it.

[docs/TODO.md](docs/TODO.md) is an untriaged backlog awaiting conversion into issues — read it for context, but do not treat it as the list of active work.

Check and update [docs/logic_flows.md](docs/logic_flows.md) if any execution paths changed.

## Current Architecture

### Entry And Registration

- `app.py`: thin entry point — calls `create_app()`, registers the download route, starts the server.
- `factory.py`: `create_app()` wires server, state, runtime, handlers, and UI without calling `server.start()`; `AppComponents` dataclass holds all wired objects; `make_download_handler()` builds the file-download HTTP handler.
- `app_config.py`: CLI parsing and devtools/hot-reload setup.
- `runtime_setup.py`: `RuntimeContext` dataclass and `create_runtime_context()` — ParaView objects created before Trame is available. `ParaViewRuntime` is constructed in `factory.py` once `state` and `view_controls` exist.
- `handler_registration.py`: wires controllers and state handlers.
- `state_setup.py`: initializes all Trame state. If adding UI controls, add defaults here.
- `state_handlers.py`: shared `@state.change(...)` callbacks for selected file, color-by, representation, active pipeline node, interaction quality, edit mode.
- `view_controls.py`: central wrapper for Trame view update callbacks and optional ParaView diagnostics.

### ParaView Backend Path

- `paraview_backend.py`: owns ParaView sources/displays, pipeline nodes, filters, coloring, display controls, picking, selection overlays, saving/export.
- `paraview_runtime.py`: synchronizes backend state into Trame state, handles render pushes, edit-session overlay sync. Forwards event normalization calls to `paraview_event_utils.py`.
- `paraview_event_utils.py`: pure helpers for normalizing ParaView picking event payloads (`normalize_edit_selection_ids`, `summarize_edit_event`, coordinate mapping). No Trame dependency.
- `paraview_controllers.py`: user actions from the UI: pipeline actions, filters, edit sessions, selection, field creation, display/color controls.
- `paraview_property_inspector.py`: collects editable ParaView proxy properties for Source/Display tabs.
- `selection_debug.py`: builds and emits optional edit-selection debug payloads.
- `edit_session.py`: domain logic for the edit session — geometry modes (volume/surface/point), adjacency growth, flood-fill, expression evaluation via `vtkArrayCalculator`, surface boundary materialization. Independent of Trame.
- `common_controllers.py`: file upload (`upload_dataset`, `upload_state_file`) and remote file refresh controllers. Wraps `ClientFile` errors into UI feedback.
- `file_operations.py`: path-safe save helpers — `resolve_output_path()` and `resolve_state_path()` strip absolute prefixes and reject `..` paths to confine writes to `--data-directory`. State files use `.coral.state.json`.
- `vtk_metadata.py`: strips `InformationKey` blocks from VTU XML before save (they can break rereads). `sanitized_vtk_xml_path()` creates a cleaned temporary copy.
- `constants.py`: array sentinels (`__solid__`), `point:`/`cell:` prefixes, representation names, categorical arrays (`MaterialID`, `ManifoldID`), interaction quality presets.
- `paraview_filter_catalog.py`: `SUPPORTED_FILTERS` hard-coded list and `FILTER_DISCOVERY_KEYWORDS`/`FILTER_DISCOVERY_EXCLUDE_SUBSTRINGS` for auto-discovery filtering.
- `diagnostics.py`: `debug_log()` prints only when devtools mode is active.

Important ParaView UI state:

- `available_arrays` / `selected_array`: color-by selector. Values are `__solid__`, `point:ArrayName`, or `cell:ArrayName`.
- `representation`: `Surface`, `Surface with Edges`, `Wireframe`, `Points`.
- `pipeline_items` / `active_pipeline_item`: left pipeline tree and active node.
- `source_properties` / `display_properties`: generated editable proxy properties.
- `color_controls_*`: dedicated color-bar controls under Display -> Advanced Display Controls.
- `edit_session_active`, `edit_geometry_mode`, `edit_field_choice`, `edit_selection_mode`, `selection_count`: edit workflow.

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

### EditSession Geometry Modes

`edit_session.py` supports three modes selected per-field:

- **volume**: 3D cells; adjacency by shared faces/edges.
- **surface**: codim-1 boundary faces/edges; builds boundary maps tracking which faces appear exactly once across all top cells. When the edit session commits, `materialize_surface_selection()` appends any missing codim-1 cells to the dataset.
- **point**: point picking; selecting a point field in the UI forces this mode automatically.

Adjacency grows use angle thresholds: surface neighbors are filtered by dihedral angle; volume neighbors use face/edge sharing. `CellCenters` array is auto-added for expression evaluation and stripped on save.

### Display Color Controls

Display -> Advanced Display Controls -> Color Bar contains:

- color map preset.
- manual min/max and rescale to data.
- show/hide color scale.
- show/hide orientation axes.
- interpret values as categories.

The color-scale visibility is user state. Range/preset/category updates must preserve it and reapply it after touching the lookup table.

## Test Organization

Unit tests (`tests/test_*.py`, excluding `test_e2e_*`): logic isolated from Trame — `test_edit_session.py`, `test_file_operations.py`, `test_paraview_backend.py`, `test_paraview_controllers.py`, `test_paraview_runtime.py`, `test_state_handlers.py`, and others.

E2E tests (Playwright, require browser):
- `test_e2e_edit_selection_playwright.py`: edit session, selection modes, color bar controls.
- `test_e2e_edit_selection_cube_modes_playwright.py`: cube mesh geometry mode variations.
- `test_e2e_non_edit_rotation.py`, `test_e2e_rotation_lock.py`: camera interaction.
- `test_e2e_pvd_animation.py`: PVD timeseries animation with time slider.

`tests/conftest.py` provides `shared_browser` (session-scoped Playwright, headless unless `--show-browser`) and `tmp_renderer` (bare `vtkRenderer` for non-windowed unit tests).

## Tests To Prefer

For field creation and replace selection:

```bash
conda run -n coral-paraview pytest -q tests/test_e2e_edit_selection_playwright.py::test_paraview_point_field_replace_box_selection_does_not_toggle_overlap
```

For color bar controls:

```bash
conda run -n coral-paraview pytest -q tests/test_e2e_edit_selection_playwright.py::test_paraview_display_color_scale_visibility_survives_rescale
```

For backend/controller coverage:

```bash
conda run -n coral-paraview pytest -q tests/ --ignore-glob=tests/test_e2e*.py
```

## Debugging Notes

- `docs/logic_flows.md` has detailed flow diagrams.
- If `pytest` or `python` resolves to the wrong environment (ParaView unavailable): a stale virtualenv may be active and its `PATH` entry wins. Run `deactivate` if a venv is active (`deactivate` is only defined while a venv is sourced — if not found, no venv is active), then `conda activate coral-paraview`.
- E2E test meshes live in `test_data/`; use them instead of writing into `data/` unless needed.
- `tests/test_e2e_edit_selection_playwright.py` has helpers for normalized box drags and switch state checks.
- Selection e2e logs can include `[selection-record] ...`; use `E2E_STREAM_APP_LOGS=1` to see app output live.
- `tools/inspect_vtu.py` can inspect binary/compressed VTU output:

```bash
conda run -n coral-paraview python tools/inspect_vtu.py test_data/output.vtu            # print to console
conda run -n coral-paraview python tools/inspect_vtu.py test_data/output.vtu -o out.txt # write to file
```

## File Format Notes

`file_utils.py` detects `.vtk`, `.vtu`, `.vtp`, and related supported mesh formats. Add new extensions there and in relevant tests.

`--data-directory` controls both scanned input files and save destinations for exported/edit-session results.
