# CODEX_LOG

## Goal

Evolve the current VTK/trame viewer toward a ParaView-backed application while keeping the existing project aesthetic.

## Done

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
  - `Clear Selection`
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
  - `Select All` / `Clear Selection` buttons now wrap correctly on narrow panels and no longer overflow.
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

## Current Behavior

- ParaView backend starts and renders.
- Multiple sources can be loaded and selected from the pipeline browser.
- Filters can be added on top of the active pipeline node and appear as selectable pipeline items.
- The right inspector updates from the selected source.
- Source/display generated properties are visible.
- A subset of generated properties is editable and applied back to ParaView.
- The VTK backend still supports mesh editing.
- The ParaView backend can now initialize an edit session from compatible outputs (`vtkUnstructuredGrid`) and save that working copy as a new file.
- A saved edit-session result can now be materialized back into the ParaView pipeline as a new source node.
- Calculator guidance is now exposed in the inspector instead of relying on the user to inspect array names manually in `Information`.
- Volume edit operations can now create a new scalar cell field on the edit-session dataset before saving or re-adding it to the pipeline.
- ParaView edit sessions now keep a live cell-selection set for `Volume` mode and can apply scalar authoring only to those selected cells.
- The Docker image now starts with the ParaView backend by default and listens on port `8080` inside the container.
- Dockerized ParaView runs with offscreen rendering and can save screenshots, although some hosts still emit non-fatal EGL/X warnings during startup.
- `app.py` is now mostly reduced to startup, state/runtime construction, view helpers, and top-level handler wiring.
- Refactored helper modules now have direct unit coverage without needing a live Trame browser session.
- `paraview_backend.py` now has targeted coverage for its internal logic, while the remaining gaps are
  mostly in live runtime integration and server-side ParaView interaction.

## Known Limitations

- The generated properties panel is only partially editable.
  - More ParaView property classes still need support.
- Coverage is still strongest on pure Python helpers and wiring.
  - Browser-driven flows, full Trame callbacks, and live ParaView interaction still need higher-level tests.
- Filter support is currently limited to the first supported set:
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
- Filter hierarchy is represented as a lightweight indented flat list.
  - There is no true collapsible pipeline tree yet.
- No pipeline grouping/tree hierarchy yet.
  - Current browser is a flat list of sources.
- ParaView edit mode is still partial.
  - Session creation, saving, re-import, scalar `Volume` field writing, and basic click/box selection plumbing exist.
  - Visual highlighting of the current edit-session selection in the render view is not integrated yet.
  - `Surface` / `Edge` / `Point` authoring and mixed-dimensional append are not integrated yet.
- ParaView runtime alerts currently surface the latest captured warning/error block.
  - There is not yet a persistent log/history panel.
- File upload flow has not yet been end-to-end validated by Codex in a live browser session.
  - The implementation is in place, but it still needs user verification.
- Source visibility is reflected through the left-panel button and icon only.
  - There is no dedicated eye-toggle control inside each row yet.
- Trame hot reload only reloads Python callback functions.
  - Structural UI changes and some ParaView-side state/setup changes may still require a manual restart.
- Dockerized ParaView still emits graphics-stack warnings on some hosts:
  - `bad X server connection`
  - `Could not initialize a device`
  - `Failed to initialize OpenGL functions`
  - In the current setup those warnings do not prevent startup or offscreen screenshots, but the graphics path is not fully clean yet.
- `app.py` still owns backend-selection wiring and a few inline dependency adapters for file operations.
  - The heavy VTK/ParaView operational paths, state defaults, and handler registration logic now live outside the file.

## Backlog

### Next Functional Work

- Add filter creation to the pipeline.
- Expand generated property editing support.
- Support more ParaView filter/property classes, including proxy/input sub-properties like `ClipType`, `GlyphType`, and `SeedType`.
- Add better visibility toggles directly in pipeline rows.
- Add duplicate / rename / remove-all pipeline actions.
- Add persistence for session state.
- Integrate the existing VTK editing tools (`mesh_edit.py`, `interactor.py`) against the new `EditSession`.
- Add richer helper panels for other filters with non-obvious symbols or inputs (`Streamline`, `Glyph`, `Threshold`).
- Optionally add click-to-insert variable names for Calculator expressions.
- Implement `Surface` mode by appending selected 2D cells to the unstructured grid.
- Implement `Edge` mode by appending selected 1D cells to the unstructured grid.
- Implement `Point` mode and decide whether its output should be 0D cells, point data, or both.
- Materialize ParaView-side selection feedback visually in the render view for edit sessions.

### UX / UI Follow-up

- Refine spacing and density in the pipeline browser.
- Improve discoverability of source actions.
- Reduce repeated controls between generated display properties and custom display controls where appropriate.
- Add loading/progress feedback during uploads and heavy source loads.

## Open Issues To Verify

- Verify browser file picker upload works end-to-end for `.vtk`, `.vtu`, and `.pvtu`.
- Verify `Open Remote` behaves correctly with grouped files and nested folders under `--data-directory`.
- Verify switching between multiple uploaded sources keeps `Color by` and `Representation` in sync.
- Verify `Apply` / `Reset` for generated source properties on a few representative datasets.
- Verify each supported filter can be created from the UI and that the key generated properties are editable in practice.
- Verify browser-side interaction quality and remote rendering responsiveness with the new Docker ParaView image on a couple of hosts.
- Continue shrinking `app.py` by reducing remaining backend-selection wiring and replacing inline dependency lambdas with more explicit objects or dataclasses.
