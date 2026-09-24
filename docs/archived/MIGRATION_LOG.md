# CODEX_LOG

> **Archived 2026-09-22.** Historical record of the VTK→ParaView migration, which
> has landed. Kept for context only — no new entries. Open work is tracked in
> GitHub issues; for current architecture see [CLAUDE.md](../../CLAUDE.md).
> Statements below were accurate when written and have not been revised.

## Goal

Evolve the current VTK/trame viewer toward a ParaView-backed application while keeping the existing project aesthetic. The VTK→ParaView migration is complete. For current architecture see [CLAUDE.md](../../CLAUDE.md); for active work see [TODO.md](TODO.md).

## Done

- UI restructure, centralized notifications, save dialog, and categorical LUT fixes (PR #32):
  - moved edit-panel controls into the right inspector Edit tab; added `docs/ui_structure.md`
  - replaced 9 scattered alert state pairs with a single `VSnackbar` driven by `notifications.py`
  - replaced inline filename field with an explicit save/commit dialog; `save_paraview_output` / `resolve_paraview_output_path` take explicit `filename` kwarg
  - categorical LUT annotations re-applied on array/range/preset changes and on pipeline node switches; extracted shared `_refresh_categorical_annotations()` helper
  - added `_wait_for_stable_viewport` and `_wait_for_foreground(narrower_than=...)` e2e helpers; fixed several CI timing flakiness issues

- Refactored surface selection helper; replaced `ExtractSurface` with `GeometryFilter`; surface keys always use coordinate lookup.
  - `vtkExtractSurface` does not expose `PassThroughPointIds` / `PassThroughCellIds` in VTK 6.1 at either the ParaView proxy
    or raw VTK level — the original fast-path in `_surface_keys_from_selected_dataset` was always dead code.
  - `vtkGeometryFilter` is the correct filter for boundary-surface extraction from unstructured grids (`ExtractSurface`
    targets point-cloud surface reconstruction) and is available as `simple.GeometryFilter`.
  - `PassThroughPointIds = 1` was evaluated but does **not** produce reliable source point IDs through ParaView 6.1's
    proxy/server-fetch round-trip: `servermanager.Fetch()` returns an identity mapping for `vtkOriginalPointIds` even on
    meshes with interior points (e.g. 5×5×5 cube: 125 pts, 98 boundary, 27 interior). The identity mapping caused
    surface keys to mismatch the edit session's boundary map on any mesh with interior points, silently producing
    empty assignments and an e2e test timeout.
  - `_surface_keys_from_selected_dataset` now always uses coordinate-based lookup: builds a spatial index from source
    dataset point coordinates and maps each selected cell's XYZ corners back to source point IDs. This is correct
    regardless of point renumbering between the GeometryFilter output and the source dataset.
  - Removed `source_boundary` / `boundary_point_to_keys` / `key_matches_source_boundary` logic (existed only to validate
    unreliable IDs from `ExtractSurface`).
  - Removed `FakeSelectedSurfaceDataset` test helper; updated its two callers to `FakeSurfaceDataset`.
  - Pinned `paraview=6.1` in `tools/setup_pv_env.sh` to match `setup/environment-docker.yml` (Docker was already pinned;
    conda-forge carries only 6.1).
  - Added `EditSessionSource` TypedDict and type annotations to `edit_session.begin()`.
  - All 165 unit tests pass; 12 e2e tests pass.

- Removed multi-backend `getattr` guards (follow-up from VTK backend removal):
  - replaced all `getattr(pv_backend, "method", None)` + callable-check patterns in `paraview_controllers.py` with direct calls
  - replaced all `getattr(self, "_attr", default)` patterns in `paraview_backend.py` with direct attribute access (all attrs initialized in `__init__`)
  - replaced `getattr(state, ...)` and `getattr(edit_session, ...)` guards that wrapped attrs guaranteed by `state_setup.py` and `EditSession.__init__`
  - updated test mocks in `test_paraview_backend.py` and `test_paraview_controllers.py` to reflect the now-required (non-optional) backend interface

- Introduced app factory and integration tests; slimmed `app.py` to a 16-line entry point:
  - extracted `create_app()` into `factory.py`; wires server, state, runtime, and handlers without calling `server.start()`, eliminating module-level side effects
  - added `AppComponents` dataclass exposing all wired objects for tests
  - moved `make_download_handler` to `factory.py`
  - added `tests/test_factory.py` (15 tests) covering structure, wiring consistency, state defaults from the real backend, and direct `ParaViewRuntime`/backend integration via `load_file` — fills the gap between unit mocks and e2e

- Reduced indirection in the ParaView runtime layer:
  - refactored `register_state_handlers` to accept `paraview_runtime: ParaViewRuntime` directly instead of 7 individual callables
  - refactored `register_app_handlers` to directly accept `paraview_runtime: ParaViewRuntime` instead of `runtime: RuntimeContext`
  - `ParaViewRuntime` is now constructed directly in `app.py` after Trame setup

- Removed VTK backend entirely, leaving ParaView as the only rendering path:
  - deleted `vtk_runtime.py`, `vtk_controllers.py`, `vtk_pipeline.py`, `mesh_edit.py`, `interactor.py`, `scalar_bars.py` and their test files
  - removed `--backend` CLI flag and all `is_paraview_backend` / `is_vtk_backend` dispatch closures
  - collapsed `_noop` sentinel and all ternary `if x else _noop` patterns to direct calls
  - removed `EditOperations` dataclass and all VTK-only parameters from `register_app_handlers`, `register_state_handlers`, `register_common_controllers`
  - simplified `RuntimeContext` from 14 fields to 6; removed `| None` unions that existed only for the dual-backend duality
  - removed `backend` / `backend_message` state vars and the `_build_vtk_edit_panel` UI function
  - retained `vtk_metadata.py` (shared utility used by `edit_session.py` and `paraview_backend.py`)
  - updated README, CLAUDE.md, CODEX_LOG.md, and TODO.md to reflect the single-backend state
  - added type annotations to `runtime_setup.py`, `file_operations.py`, `state_handlers.py`, `common_controllers.py`
  - all 143 unit tests pass after the refactor

- Fixed recurring `vtkSMColorMapEditorHelper` LUT warning on file load:
  - added `[view-debug]` trace logs inside `load_file` and `_disable_scalar_coloring` to pinpoint the exact call where the warning was emitted
  - root cause: `_disable_scalar_coloring` unconditionally called `SetScalarBarVisibility(False)` on the display before checking whether a LUT was actually bound; when `had_lookup_table=False` (fresh display from `Show()` with ParaView-internal auto-coloring, or already-cleared display) the call caused `vtkSMColorMapEditorHelper` to traverse its LUT-resolution path and fail with "Failed to determine the LookupTable being used"
  - fix: gate `SetScalarBarVisibility` / `HideUnusedScalarBars` calls strictly on `had_lookup_table=True`; when the display has no explicitly bound LUT, only clear `ColorArrayName` and `LookupTable` directly, then call `ColorBy(display, None)`
  - imported `debug_log` from `diagnostics` into `paraview_backend` for the trace lines
  - verified with full unit + Playwright e2e suite: `94 passed`, `8 passed`
- Added "Load State" remote browser dialog, "Upload State File" button, and fix for VectorProperty JSON serialization error on Save State:
  - "Load State" button now opens a searchable remote file browser (state_browser_dialog) listing all `.coral.state.json` files under --data-directory, matching the pattern of the existing "Open Remote" dataset browser
  - added "Upload State File" button with a hidden file input that accepts `.json` files, uploads them via `upload_state_file` controller, deduplicates filename, and selects the uploaded file automatically
  - new state vars: `state_browser_dialog`, `state_browser_search_term`, `filtered_state_files`; new handler `on_state_browser_search_change`; new controller `upload_state_file`; new `persist_uploaded_state_file` in `FileOperationService`
  - `pv_load_state` now closes the state browser dialog on success
  - fixed `VectorProperty is not JSON serializable` error on Save State: `_normalize_property_value` in `paraview_property_inspector.py` now handles non-list VectorProperty objects defensively; `save_paraview_state` in `file_operations.py` adds a `_json_default` fallback encoder to `json.dumps` to catch any remaining non-serializable proxy values
  - updated all affected test mocks in `test_common_controllers.py` and `test_handler_registration.py`
  - verified: 114 unit tests pass

- Fixed ParaView save/viewport regressions introduced around overwrite confirmation and face-only display:
  - preserved the active camera/view state while creating ParaView cell/face extract displays so `Show cells` off / `Show faces` on no longer shifts the viewport on explicit boundary-only datasets
  - flushed save feedback state after successful ParaView saves so save status updates are pushed to the client reliably
  - changed ParaView save actions to consume the live `Output filename` value from the toolbar at click time, avoiding races where a stale default filename could trigger the new overwrite dialog unexpectedly
  - added controller/file-operation/backend regression coverage for camera preservation, save feedback flushing, and explicit client-provided save filenames
  - verified with targeted tests and Playwright e2e: `91 passed`, `2 passed`
- Fixed ParaView surface-edit and face-only display regressions:
  - mapped invalid native ParaView surface-pick point IDs back to source boundary keys by coordinate, so surface selections on `cube.vtk` can be assigned successfully
  - preserved existing `CellData` values when materializing new face/edge cells by copying tuples from the owning top-dimensional cell, including multi-component arrays
  - removed the internal `CellCenters` helper array before save and regenerated it only when needed for calculator evaluation
  - added the ParaView `Quad` -> `Quadrilateral` cell-type alias so `Show cells` off / `Show faces` on displays explicit quad faces from `cube_with_boundary_id.vtk`
  - verified with targeted tests and Playwright e2e: `99 passed`, `7 passed`
- Added Playwright e2e coverage for explicit face-only display:
  - added `test_data/square_with_boundary.vtk` with 2D quad cells plus standalone 1D boundary cells on the left edge
  - added an e2e that turns `Show cells` off and `Show faces` on, then verifies the viewport shows only the explicit left boundary cells
  - preserved solid-color styling on generated cell/face extract displays so face-only extracts remain visible against the white background
  - verified with targeted ParaView tests and the full edit-selection Playwright file: `83 passed`, `6 passed`
- Made ParaView cell/face display controls dimension-aware:
  - renamed the UI/state controls to `Show cells` / `Show faces`
  - documented the app semantics: cells are the highest explicit intrinsic cell dimension present, faces are explicit cells one dimension lower
  - changed ParaView display filtering so `Show faces` never generates faces from higher-dimensional cells and only shows face-dimensional CELL_TYPES present in the source
  - added multiblock dimension discovery and regression coverage for 2D cells, standalone 1D faces, and composite sources
  - verified with targeted unit/runtime/controller tests and Playwright e2e: `83 passed`, `5 passed`
- Fixed ParaView test regressions and stabilized selection/edit internals:
  - restored `_surface_selection_helper_for(...)` after an accidental method-body regression that broke edit-session initialization in e2e flows
  - added defensive boundary-cache handling for lightweight backend instances used by tests (lazy init + safe clear path)
  - aligned scalar-bar transition behavior in `apply_coloring(...)` with expected hide/show sequencing in backend tests
  - made surface edit selection accept native ParaView surface-key payloads when strict topology remapping does not resolve, preventing false-empty selections in surface-mode e2e tests
  - verified with full suite: `157 passed`
- Sanitized fragile VTK XML metadata:
  - Removed `L2_NORM_RANGE` / `L2_NORM_FINITE_RANGE` array information keys before `.vtu` writes.
  - Added temporary XML sanitization on ParaView load for existing files that still contain those metadata blocks.
  - Added unit coverage for metadata cleanup.
- Refined ParaView pipeline reload and display-state preservation:
  - Added a reload button beside `Pipeline Browser` for the selected pipeline item.
  - Reload now preserves selected color array, representation, color controls, source/display properties, and scalar-bar state.
  - Hardened color-map preset restore across ParaView preset-name differences such as `Viridis (matplotlib)` vs `Viridis`.
  - Fixed stale scalar bars when switching `Color by` arrays by hiding unused scalar bars and binding the active display LUT explicitly.
  - Made `Rescale Data` force the active color range to the current data range instead of only extending it.
  - Populated categorical color annotations and indexed colors from unique scalar values when `Interpret values as categories` is enabled.
- Improved `Information` panel cell counts:
  - Detailed cell stats now count concrete cells by intrinsic cell dimension via `GetCellDimension()`.
  - The breakdown reports volume, surface, edge, and vertex cells for mixed-dimensional datasets.
- Stabilized ParaView time-dependent UX and compatibility:
  - fixed `.pvd` timestep coercion for non-`list/tuple` ParaView timestep containers
  - synced time state propagation (`time_values`, `time_index`, `current_time`, `is_time_dependent`) between backend/runtime/UI
  - added complete time toolbar controls (first/prev/play-next/last/loop) and fixed duplicated icon rendering in Vuetify buttons
  - ensured slider/time label stay in sync during animation by explicitly flushing time state updates each animation tick
  - added compatibility fallback for `Rescale over Time` when `simple.RescaleTransferFunctionToDataRangeOverTime` is unavailable
- Hardened tests around time-dependent behavior:
  - added backend unit coverage for non-list timestep containers and over-time rescale fallbacks
  - made e2e animation assertions rely on rendered toolbar state instead of internal `window.trame.state` structure
  - made non-edit rotation e2e use a non-degenerate dataset (`cube.vtk`) for stable screenshot-diff detection
- Improved backend test resilience:
  - `get_time_state()` now safely returns default time metadata when animation scene APIs are unavailable in fakes/mocks
- Fixed volumetric edit-selection ID mapping regressions:
  - strengthened fallback mapping from selected surface fragments back to source volumetric cell IDs via boundary-face ownership
  - added triangulation-tolerant subset matching so `touch` rectangle picks map correctly even when picked faces are triangles and source faces are polygons
  - added backend regression coverage for face-to-volume ID mapping
- Fixed edit-selection `touch` behavior on `test_data/cube.vtk`:
  - stopped discarding valid volumetric picks with a centroid-depth visibility pass after ParaView already selected visible surface cells
  - validated native surface keys against the editable boundary map and fell back to geometric surface picking when ParaView returns non-editable keys
  - added e2e coverage for center box selection in exposed edit modes: volume, surface, and point
  - removed edge mode from the exposed edit-mode options until it is implemented reliably

- Added support for `.pvd` files and time-dependent simulations:
  - Enabled `.pvd` extension in file discovery.
  - Added time animation controls (play/pause, next/prev step, time slider) to the top toolbar, visible for time-dependent datasets.
  - Implemented background animation task with looping support.
  - Added "Rescale over Time" option to the Color Bar panel with a confirmation warning for slow operations.
- Separated cell information by type in the `Information` panel:
  - Added recursive counting of cells by dimension (Volumetric, Surface, Edge, Vertex) for single and composite (Multi-block) datasets.
  - Integrated detailed breakdown into the `Information` tab UI.
- Fixed ParaView edit field creation and replace-selection behavior:
  - removed the separate `Create New Field` button and open the dialog from `Select field -> Create new...`
  - made field-selection changes pass the selected value explicitly to the controller
  - made replace-mode picking ignore native toggled selection payload IDs when coordinates are available
  - clear ParaView native selection state and transient edit-selection overlays before pick queries
  - added e2e coverage for `Select field -> Create new... -> Point data array -> TestField` followed by overlapping replace box selections
- Added ParaView Display color-bar controls under `Advanced Display Controls`:
  - color-map preset selection, manual min/max range, and data-range rescale
  - toggles for color scale, orientation axes, and categorical color interpretation
  - preserved color-scale visibility across range/preset/category updates
  - added e2e coverage for color-scale visibility through `Rescale Data`
- Added backend selection in `app.py`: `--backend auto|vtk|paraview`.
- Added ParaView backend adapter in `paraview_backend.py`.
- Added conda-based ParaView environment bootstrap script in `tools/setup_pv_env.sh`.
- Integrated ParaView remote rendering through trame.
- Preserved the existing VTK backend and mesh editing path.
- Reworked the ParaView path layout into:
  - left pipeline browser
  - center render view
  - right inspector
- Reverted the dark ParaView-style theme and restored a lighter Vuetify-aligned aesthetic.
- Added generated source/display property introspection from ParaView proxies.
- Added first editable generated property types:
  - `StringListProperty`
  - `ArrayListProperty`
  - scalar `VectorProperty`
- Added `Apply` / `Reset` behavior for generated property edits.
- Added lightweight multi-source pipeline state:
  - loading a file appends a source
  - active pipeline selection drives inspector and display state
  - active source can be hidden/shown
  - active source can be deleted
- Removed top-toolbar duplication for the ParaView backend:
  - `Color by` and `Representation` remain in the right `Display` panel
  - top toolbar now keeps global actions
- Split data access into two explicit flows:
  - `Upload`: browser-local file upload to the server, then load
  - `Open Remote`: browse files already present under `--data-directory`
- Added a top-toolbar `Interaction quality` control for remote rendering.
  - Presets tune interactive image quality and scale factor during rotate/pan/zoom.
- Moved `Interaction quality` into the right-side `Display` panel and kept `Apply/Cancel` global to the inspector.
- Replaced the fragile Vuetify tab widget in the right inspector with a fixed three-button selector.
- Added first-class filter nodes to the ParaView pipeline:
  - `Calculator`
  - `Clip`
  - `Contour`
  - `Glyph`
  - `Reflect`
  - `Slice`
  - `Streamline`
  - `Threshold`
  - `Transform`
  - `Tube`
  - `Warp by Scalar`
  - `Warp by Vector`
- Added `Add Filter` action on the active pipeline node.
- Added programmatic discovery of additional ParaView filters and exposed them under an `Experimental` section in the filter menu.
- Added heuristic icon assignment for experimentally discovered filters.
- Added `--hide-experimental-filters` to hide the experimental section entirely.
- Added saving of the active ParaView pipeline result to a new file from the `Source` panel.
- Extended ParaView-side saving so the same `Save Result` flow now saves either:
  - the active pipeline result, or
  - the current `EditSession` working dataset
- Reworked ParaView edit-field workflow in edit mode:
  - replaced free-text `Field name` with field selection (`cell:*`, `point:*`) plus `Create new...`
  - added `Create New Field` dialog with array type (`cell`/`point`) and default value on creation
  - renamed apply action to `Assign to Selected` and switched assignment semantics to selected entities only
  - linked geometry mode options to selected field association (`point` => `point` mode only, `cell` => `volume/surface/edge`)
- Added point-selection plumbing for ParaView edit sessions:
  - point selection state and selection ops in `EditSession`
  - point picking paths in `paraview_backend.py` and controller routing
- Fixed assignment errors when target arrays are integer-typed by updating scalar tuples with `SetComponent` instead of `SetValue`.
- Improved edit-state sync stability so selected field choice is preserved across UI sync when still valid.
- Hardened grow-selection e2e coverage and diagnostics:
  - deterministic grow-box defaults and optional env override (`E2E_SURFACE_GROW_BOX`)
  - manual mode for interactive confirmation (`E2E_SURFACE_GROW_MANUAL=1`)
  - richer attempt logging (`[grow-e2e] ...`) and optional app log streaming (`E2E_STREAM_APP_LOGS=1`)
  - backend selection-coordinate logging via `[selection-record] ...` for click/box inputs
- Fixed ParaView edit-selection regression introduced by the field workflow rewrite:
  - scaled `VtkRemoteLocalView` box-selection rectangles into ParaView `ViewSize` coordinates before picking
  - routed zero-area box-selection events through the click picker
  - made the Playwright selection-count helper ignore hidden/stale counters and wait for UI updates
- Added initial `EditSession` scaffolding for the ParaView backend:
  - fetch active pipeline output as local VTK data
  - start/discard an edit session from the `Source` panel
  - suggest an `_edited.vtu` filename for edit-session saves
- Added `Add Edited Result To Pipeline` for ParaView edit sessions.
  - The edited working copy is saved under `--data-directory`
  - then appended back as a new source in the active pipeline session
- Added calculator-specific context in the `Properties` panel:
  - active Calculator association (`Point Data` / `Cell Data`)
  - available input-array variable names
  - explicit coordinate symbols (`coordsX`, `coordsY`, `coordsZ`)
- Added ParaView/VTK runtime alert surfacing in the UI.
  - Runtime parser/filter errors are now captured from VTK output and shown as an in-app alert.
- Added the first ParaView-side `Edit mode` authoring form in the `Source` panel:
  - `Geometry mode`
  - `Field name`
  - `Calculator`
  - `Default value`
  - `Apply Edit`
- Added a dedicated `Edit` tab in the right inspector for ParaView edit sessions:
  - `Pick` / `Rotate`
  - `Grow selection`
  - `Grow angle`
  - `Select All`
  - `Clear All`
  - live selection status/event preview
- Implemented the first working slice of the new edit architecture:
  - `Volume` mode on the local `EditSession` dataset
  - automatic `CellCenters` cell-data generation
  - scalar field creation/update from calculator expressions on cell data
  - cell selection state stored on the edit-session dataset
  - `Apply Edit` now writes on selected cells and uses `Default value` elsewhere
  - contiguous grow-selection support for `Volume` mode
- Added generated-editor support for `ArraySelectionProperty`, which is needed by several ParaView filters.
- Fixed several ParaView/trame integration issues encountered during iteration:
  - wrong array metadata access
  - stale `Tbody`/`Tr`/`Td` wrappers
  - `Representation` returned as ParaView property object instead of string
  - pipeline selection reset to first node on every sync
  - development launcher used `--dev`, but this trame version requires `--hot-reload`
- Reworked Docker support so the container now runs the ParaView backend by default.
  - Replaced the old `kitware/trame:uv` image path with a `micromamba`-based container.
  - Added a dedicated conda environment spec in `setup/environment-docker.yml`.
  - Verified that the container can import `paraview`, import `trame.widgets.paraview`, select `BACKEND=paraview`, and render offscreen screenshots.
  - Documented the remaining non-fatal EGL/X startup warnings in the README.
- Fixed a legacy `.vtk` reader bug in `file_utils.py`.
  - Files without a detectable `DATASET` header no longer raise `UnboundLocalError`.
  - Added a regression test for the fallback reader path.
- Started refactoring `app.py` into smaller modules.
  - Moved ParaView controller registrations to `paraview_controllers.py`.
  - Moved VTK edit controller/state registrations to `vtk_controllers.py`.
  - Moved shared state callbacks to `state_handlers.py`.
  - Moved backend-agnostic button handlers to `common_controllers.py`.
  - Moved upload/save file operations to `file_operations.py`.
  - Moved VTK scene orchestration to `vtk_runtime.py`.
  - Moved ParaView UI/runtime synchronization to `paraview_runtime.py`.
  - Moved Trame state initialization defaults to `state_setup.py`.
  - Moved controller/state registration wiring to `handler_registration.py`.
  - Renamed `pv_backend.py` to `paraview_backend.py`.
  - Extracted ParaView filter catalog/discovery into `paraview_filter_catalog.py`.
  - Extracted ParaView generated-property inspection/editing into `paraview_property_inspector.py`.
  - Removed unused local-view helper functions that were no longer on the active path.
  - Centralized interaction-quality presets in `constants.py`.
  - Added overwrite confirmation before replacing existing save targets.
    - ParaView `Save Result` and `Save And Add To Pipeline` now open a confirmation dialog when the destination file already exists.
    - VTK `.vtu` saves now use the same confirmation flow instead of silently overwriting files.
    - Centralized overwrite guards in `file_operations.py` and added controller/UI regression coverage.
- Added broad unit-test coverage for the refactored support modules.
  - Added dedicated tests for `state_setup.py`, `file_operations.py`, `handler_registration.py`,
    `paraview_filter_catalog.py`, and `paraview_property_inspector.py`.
  - The new tests cover state defaults, file/save flows, handler wiring, filter discovery,
    property inspection, and property-value coercion.
- Extended unit coverage to callback/controller registration layers.
  - Added dedicated tests for `state_handlers.py`, `common_controllers.py`,
    and `paraview_controllers.py`.
  - The new tests cover callback registration, state transitions, upload/save error handling,
    visibility toggles, and filter/property controller behavior.
- Added direct unit coverage for `paraview_backend.py` without requiring a live ParaView session.
  - The tests exercise array discovery, output naming, relative-path handling, pipeline hierarchy,
    UI-state synthesis, representation/coloring logic, delete behavior, and pick-coordinate helpers
    using fake ParaView objects.
- Added direct unit coverage for `vtk_controllers.py`.
  - The tests cover edit-mode transitions, target switching, selection clearing/filling,
    ID assignment, save guards, and save error handling.
- Added direct unit coverage for `paraview_runtime.py`.
  - The tests cover runtime-message parsing, edit-session state sync, picking payload normalization,
    overlay synchronization, UI-state propagation, and backend-driven load/color/representation flows.
- Added direct unit coverage for `vtk_runtime.py`.
  - The tests cover scalar-bar policy, edit-mode coloring, scene representation/coloring updates,
    VTK load flow, and camera reset/view reset behavior.
- Fixed a regex bug in `tests/test_e2e_edit_selection_playwright.py` that caused selection count parsing to fail.
- Fixed a bug where camera rotation was blocked in non-edit mode.
  - Re-enabled rotation by default and made `pick_mode` False by default.
  - Updated state management in `state_handlers.py` to correctly handle interaction modes.
  - Added E2E test `tests/test_e2e_non_edit_rotation.py` to verify rotation behavior.
- Fixed rotation lock E2E test failure caused by state setup changes.
- Fixed a ParaView UI-state crash after deleting the last pipeline node.
  - `paraview_backend.get_ui_state()` now returns a complete default schema even with no active source.
  - `paraview_runtime.update_ui_state()` now merges backend payloads with defensive defaults.
  - Added regression tests for backend-default UI state and runtime tolerance to partial UI payloads.
- Fixed reload behavior when re-opening the same file after deleting the last pipeline node.
  - `pv_delete_active` now clears `selected_file` when the pipeline becomes empty.
  - Re-opening the same `.vtk`/`.vtu` path now reliably triggers a new load.
  - Removed temporary same-path reload workarounds from common controllers.
  - Added regression coverage in `tests/test_paraview_controllers.py`.
- Added overwrite confirmation flow for ParaView `Apply Edit` when the target cell field already exists.
  - `Apply Edit` now opens a warning dialog instead of failing immediately.
  - Confirming overwrite removes the existing field and recreates it with generated values.
  - Added edit-session overwrite handling to avoid scalar-type mismatch failures (`SetValue` float vs int array).
  - Added regression coverage in `tests/test_edit_session.py` and `tests/test_paraview_controllers.py`.
- Implemented first working `Surface` edit mode flow in ParaView edit sessions.
  - Surface-mode selection now tracks codimension-one boundary entities (faces in 3D, edges in 2D).
  - `Apply Edit` in `Surface` mode now materializes selected missing boundary entities into the dataset.
  - Existing codimension-one entities are detected and not duplicated.
  - Surface-mode save now materializes pending selected entities before writing output.
  - Added regression coverage for surface materialization semantics in `tests/test_edit_session.py`
    and controller behavior in `tests/test_paraview_controllers.py`.
- Added a Playwright E2E test for the surface-mode boundary workflow.
  - New test enters edit mode, switches to `Surface`, selects the left boundary side, applies,
    sets field `BoundaryID` and value `1`, then saves output.
  - Test file: `tests/test_e2e_edit_selection_playwright.py`.
- Fixed Surface-mode stability and overlay compatibility issues discovered during live runs.
  - `edit_geometry_mode` now stays aligned with `edit_session.geometry_mode` during selection callbacks,
    preventing silent fallback back to `Volume`.
  - Added controller regression coverage to ensure Surface mode remains active after selection sync.
  - Fixed ParaView overlay rendering crash in some builds where `ColorBy(display, None)` raised
    `invalid association string 'NONE'` for transient producers.
  - Added a backend regression test that simulates the `ColorBy(None)` failure and verifies
    overlay update continues without aborting edit mode.
- Fixed Surface-mode touched-entity selection and save consistency.
  - Surface picking now resolves touched codimension-one entities (faces in 3D, edges in 2D)
    instead of selecting every boundary face/edge of a touched top-dimensional cell.
  - Save/Add-to-pipeline now uses robust scalar-coloring disable fallback even when ParaView rejects
    `ColorBy(..., None)` with `invalid association string 'NONE'`.
  - After appending new surface cells, all existing `CellData` arrays are resized to the new cell count
    (with default initialization for new tuples), preventing invalid files that load as empty datasets.
  - Added regressions in `tests/test_edit_session.py`, `tests/test_paraview_backend.py`,
    and `tests/test_paraview_controllers.py`.
- Fixed Surface-mode field visibility and overwrite UX.
  - Surface apply now writes default values on all non-selected cells and expression values on selected surface entities.
  - Overwrite-confirmation dialog now appears consistently in both `Volume` and `Surface` modes.
  - Removed the non-informative `Last selection event` textarea from the Edit panel.
- Fixed and hardened Surface grow-selection behavior.
  - Grow now uses angular threshold propagation (`angle_threshold`) through adjacent codim-1 entities.
  - In 2D, grow with `angle_threshold = 0` now propagates along the whole collinear boundary chain.
  - Added regressions in unit tests and a dedicated Playwright E2E scenario for left-edge grow.
- Fixed selection/rotation mode switching in ParaView Edit mode.
  - Replaced client-only `pick_mode` assignments with explicit server handlers (`pv_set_pick_mode` / `pv_set_rotate_mode`)
    to keep interaction mode, box selection gating, and camera rotation synchronized.
  - Added controller regression coverage and validated browser-driven rotation lock/unlock E2E paths.
- Improved Edit Tools responsiveness.
  - `Select All` / `Clear All` buttons now wrap correctly on narrow panels and no longer overflow.
  - `Grow angle` now shows the live numeric value next to the slider.
- Hardened dataset inspection tooling.
  - `tools/inspect_vtu.py` now supports both XML (`.vtu`) and legacy (`.vtk`) inputs with automatic reader selection.
  - Added robust handling for malformed/partial files with fallback metadata summaries.
- Optimized large-mesh surface selection.
  - Added a native ParaView/VTK fast path for surface-key box picking using `ExtractSurface` + `SelectSurfaceCells`.
  - Native path maps selected surface cells back to original point-id face keys and falls back to the previous geometric method
    only when native metadata is unavailable.
- Fixed ParaView save behavior for legacy `.vtk` output.
  - Active pipeline saves with `.vtk` now use `vtkDataSetWriter` on fetched VTK datasets instead of generic `SaveData`,
    avoiding XML/extension mismatches that produced unreadable `.vtk` files.
  - Added regression tests for legacy-writer path and fallback behavior.
- Fixed surface-field application so the edited field is always visible in Surface mode.
  - Added `EditSession.apply_surface_field(...)` and shared scalar-field assignment logic.
  - Surface apply now materializes selected codim-1 entities, writes the expression only on selected
    surface entities, and writes the default value on all non-selected cells.
  - Updated controller messaging and selection labels to use `surface element(s)` in Surface mode.
  - Added regression coverage for default-on-unselected behavior and controller surface apply flow.
- Removed the non-informative `Last selection event` textarea from the ParaView Edit inspector.
