# CODEX_LOG

## Goal

Evolve the current VTK/trame viewer toward a ParaView-backed application while keeping the existing project aesthetic.

## Done

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
- Fixed a major bug where the grid would rotate during box selection in ParaView pick mode.
  - Updated `paraview_backend.py` to disable all server-side camera manipulators (3D and 2D) when picking is active.
  - Updated `paraview_runtime.py` to clear client-side interactor settings in pick mode, preventing all client-side camera interaction.
  - Added state change handlers in `state_handlers.py` to restore rotation when exiting edit mode or switching to rotate mode.
  - Added a new E2E test `tests/test_e2e_rotation_lock.py` that uses screenshot comparison to verify the fix.
  - Added a unique CSS class `coral-main-viewport` to the 3D view in `ui.py` for reliable E2E test locators.

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
