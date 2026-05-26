# Logic Flows

A walkthrough of the main execution paths in the Trame/ParaView visualizer.

## 1. Startup (`app.py`)

```
app.py
 ├── configure_app()              → parse CLI flags, devtools, hot-reload
 ├── create_runtime_context()     → instantiate ParaViewBackend, initialize_view(), EditSession
 ├── get_server()                 → Trame websocket server (Vue 2)
 ├── initialize_state()           → seed all Trame state variables with defaults
 ├── build_ui()                   → declare Vuetify layout, bind state vars and ctrl methods
 ├── ParaViewRuntime(...)         → create Trame-aware runtime wrapper (state + view_controls now available)
 └── register_app_handlers()
      ├── register_paraview_controllers()   → ctrl.add("pv_*") — user action handlers
      ├── register_state_handlers()         → @state.change("...") — reactive callbacks
      └── register_common_controllers()     → upload, refresh-files, etc.
```

Two-phase construction is intentional: `ParaViewBackend` / `EditSession` are created *before* Trame
(no `state` dependency), then `ParaViewRuntime` wraps them *after* (needs `state`).

---

## 2. File Load

Triggered when the user picks a file in the left drawer → `state.selected_file` changes.

```
state.selected_file change
 └── on_file_change()                          [state_handlers.py:24]
      └── paraview_runtime.load_file(path)     [paraview_runtime.py:327]
           ├── refresh_runtime_message(clear=True)   — reset VTK output window offset
           ├── pv_backend.load_file(path)             — ParaView Reader → pipeline node
           ├── apply_representation("Surface with Edges")
           ├── apply_coloring(__solid__)
           ├── reset_view()
           ├── update_ui_state()                     — sync all pipeline/array/display state
           └── render_and_push()
                ├── pv_backend.render()
                └── call_view_update()               — push frame to browser
```

---

## 3. UI State Sync (`update_ui_state`)

Called after almost every action. It is the "flush everything" step.

```
paraview_runtime.update_ui_state()     [paraview_runtime.py:198]
 ├── pv_backend.get_ui_state()         — collects pipeline_items, arrays, display props, time info
 ├── writes ~30 state.* variables      — pipeline_items, selected_array, color_controls_*, etc.
 ├── state.can_edit_active             — probes whether export-for-editing is possible
 └── sync_edit_session_state()         — overlays edit-mode specific state on top
```

---

## 4. Controller → Backend Pattern

Every button click in the UI calls a `ctrl.add("pv_*")` action registered in
`paraview_controllers.py`. The pattern is always:

```
UI click  →  ctrl.pv_something()          [paraview_controllers.py]
              ├── pv_backend.do_thing()      — ParaView mutation
              ├── update_paraview_ui_state() — refresh all derived state
              └── render_and_push()          — render + send frame to browser
```

Example — adding a filter:

```
ctrl.pv_add_filter(filter_key)    [paraview_controllers.py:689]
 ├── pv_backend.add_filter(filter_key)
 ├── update_paraview_ui_state()
 └── render_and_push()
```

---

## 5. Edit Session Flow

```
[Begin]
ctrl.pv_begin_edit_session()
 ├── pv_backend.export_active_dataset_for_editing()
 │    ├── creates a real edit pipeline node (kind="edit", label="✏ Editing: {original}")
 │    │    root reader → OpenDataFile(same backing file)   — no temp file write
 │    │    filter node → write temp VTU, then OpenDataFile — avoids MPI-collapsing Fetch
 │    ├── hides all existing pipeline nodes (Visibility=0)
 │    └── Fetch(edit_source) → one local vtkUnstructuredGrid passed back as "dataset"
 ├── edit_session.begin(node_id, label, filename, dataset)  — DeepCopy into working_dataset, reset all session state, precompute CellCenters array
 ├── pv_backend.set_edit_target_dataset(working_dataset)  — stores ref so surface picks can use it as source_dataset for coordinate mapping
 ├── update_paraview_ui_state()                            — sync pipeline panel to show the edit node
 ├── state.pick_mode = True, mainViewMode = "remote"       — enables hardware picking; forces server-side rendering
 └── sync_edit_session_state() + render_and_push()         — flush edit state to UI and send first frame

[Selection — click or box drag]
ctrl.pv_edit_click_selection(event) / ctrl.pv_edit_box_selection(event)  — entry point for click and box drag gestures
 ├── normalize_edit_selection_ids(event)  — extract screen coords or composite IDs
 ├── _pick_edit_ids_at_coords(mode, x, y) / _pick_edit_ids_in_rect(mode, ...)  — dispatch to click or rect pick
 │    └── pv_backend.pick_visible_cell_ids(x, y)  — ParaView hardware pick
 └── _apply_selection_ids(picked_ids, ...)  — apply selection mode (replace/add/subtract/flip) and update overlay
      ├── edit_session.replace/add/subtract/flip_selection(picked_ids)  — mutate selected_cell_ids / surface_keys / point_ids
      ├── sync_edit_session_state()         — update selection count and field readiness in Trame state
      ├── sync_paraview_edit_selection_overlay()  — highlight selected cells in view
      └── render_and_push()                 — send updated frame to browser

[Assign value]
ctrl.pv_apply_edit_field()  — triggered by "Apply" button in Edit Tools panel
 └── _apply_edit_field()    — resolves field, runs expression, writes values into working_dataset
      ├── _parse_field_choice()        — "cell:FieldName" → (association, name)
      ├── edit_session.assign_to_selected(field_name, association, expression)  — evaluate expression via vtkArrayCalculator and write results to selected cells/points
      └── sync_edit_session_state()    — refresh dirty flag and field state in UI

[Commit]
ctrl.pv_commit_edit_session()  — opens save dialog; actual write happens in _commit_edit_session
 └── _commit_edit_session()    — save, tear down session, reload result as new pipeline node
      ├── save_paraview_output()            — write modified dataset to disk
      ├── edit_session.clear()              — reset all session state and release working_dataset
      ├── pv_backend.load_file(output_path) — add saved file back as new pipeline node
      ├── update_paraview_ui_state()        — full state flush: arrays, display, pipeline tree
      └── render_and_push()                 — send final frame showing new node
```

### 5a. Data movement, process model, and bottlenecks

The diagram below tracks what happens to the mesh data across the same four phases
as section 5. Read section 5 to trace function calls; read this to understand data
ownership, copies, and where the performance costs land.

The app is **single-process** (one Python process hosts Trame, ParaView pipeline, and
edit logic). VTK C++ filter work uses multi-thread internally via `vtkMultiThreader`;
Python orchestration is single-threaded. There is no MPI: all data lives in one process.
If a pvserver were connected via `simple.Connect()`, `servermanager.Fetch()` would
still collapse all distributed ranks into this one process at the points marked below.

```
─── SESSION BEGIN ──────────────────────────────────────────────────────────────────
  [paraview_controllers.py pv_begin_edit_session]
  [paraview_backend.py     export_active_dataset_for_editing]
  [edit_session.py         EditSession.begin]

  export_active_dataset_for_editing():
    ├── All existing pipeline nodes hidden (Visibility=0)
    ├── Edit source created (kind="edit" pipeline node):
    │     root reader → OpenDataFile(same backing file)  — zero extra I/O
    │     filter node → XMLUnstructuredGridWriter → temp .vtu → OpenDataFile
    │                   ⚠ BOTTLENECK (filter case): entire filter output written to disk
    └── servermanager.Fetch(edit_source)
              ⚠ BOTTLENECK: entire mesh transferred into one Python vtkUnstructuredGrid.
                In MPI mode all ranks would be merged here.
         │
         ▼
  vtkUnstructuredGrid (local Python, discarded after begin)
         │
         ▼  DeepCopy()
         │  ⚠ full mesh copy — all points, all cells, all point/cell data arrays
         ▼
  edit_session.working_dataset             independent mutable copy; field assignments,
                                           selections, and expressions operate only here

  set_edit_target_dataset(working_dataset):
    stores reference to working_dataset so surface picks (_pick_surface_keys_native)
    can use it as source_dataset for coordinate mapping without a second Fetch.

  _ensure_cell_centers_array() [edit_session.py]:
    adds CellCenters cell-data array (XYZ per cell centroid) so
    vtkArrayCalculator can reference spatial coordinates in expressions.

─── DURING SESSION ─────────────────────────────────────────────────────────────────

  Edit node IS the active pipeline source.
  Picks (SelectSurfaceCells) run against the edit source.
  The edit source reads the same file as the original node (or the temp VTU written
  from filter output), so pick cell IDs already index working_dataset directly —
  no coordinate-based remapping is needed.

  ParaView side (edit_source proxy)        Edit session side (working_dataset)
  ────────────────────────────────         ──────────────────────────────────────
  renders in viewport                      holds all mutations (assigned field values)
  target of SelectSurfaceCells()           tracks selected_cell_ids / surface_keys /
                                           selected_point_ids

  cell IDs from hardware pick
         │ (same IDs, same geometry)
         ▼
  working_dataset cell IDs                 no remapping step

  CellCenters array (cell data)            GetPoint() calls (raw mesh geometry)
  └─ vtkArrayCalculator reads it           └─ _ensure_surface_element_vectors()
     when evaluating user expressions         computes unit normals/tangents for
     (e.g. "CellCenters[0] > 2.5")           dihedral angle filter during grow.
     Stripped from output on save.            Never stored as an array.

─── COMMIT ─────────────────────────────────────────────────────────────────────────
  [paraview_controllers.py _commit_edit_session]

  edit_session.working_dataset
         │
         ├── _remove_internal_edit_arrays()   strips CellCenters before write
         ▼
  vtkXMLUnstructuredGridWriter.Write()     ⚠ full mesh write to disk
         │
         ▼
  pv_backend.clear_edit_target_dataset()   deletes edit node, restores pre-edit node
         │
         ▼
  pv_backend.load_file(output_path)        ⚠ full mesh re-read into ParaView pipeline
         │                                   ParaView owns it again as a new node.
         ▼
  new pipeline node — normal visualization resumes, edit bridge torn down
```

Key constraints that follow from this model:

- **Edit mode cannot be distributed**: `Fetch()` collapses all data to one process.
  For very large meshes the `Fetch` + `DeepCopy` at session begin is the dominant cost.
- **No per-pick remapping**: because the edit source reads the same backing data as the
  original node, pick cell IDs directly index `working_dataset` — no coordinate maps are
  built or maintained during the session.
- **Commit writes the whole mesh**: there is no delta/patch write — the full working
  dataset is serialized even if only a handful of cell values changed.
- **Normal visualization (no edit) is unaffected**: filters run in ParaView's proxy
  layer with multithread VTK SMP parallelism; only `Fetch()` calls (rare, for metadata)
  touch the single-process ceiling.

---

### 5b. Dataset naming conventions

The edit-session code uses several "dataset" variables with similar names.
This is the reference for what each one is, who owns it, how long it lives, and why it exists.

| Name | Type | Owner | Lifetime | Role |
|---|---|---|---|---|
| `source` | ParaView proxy (`vtkSMProxy`) | `ParaViewBackend` (property) | permanent | During an edit session this is the **edit node** proxy (kind="edit"). Used for hardware picks (`SelectSurfaceCells`) and `Fetch` calls. Never mutated. |
| `source_dataset` | `vtkUnstructuredGrid` | local var (caller) | per call | Result of `servermanager.Fetch(source)`. A read-only local copy used for coordinate mapping in surface picks. Fetched on demand; not stored between calls. |
| `working_dataset` | `vtkUnstructuredGrid` | `EditSession` | session | `DeepCopy` of the dataset fetched from the edit source at session begin. The **mutation target**: field assignments, expression results, and selection tracking all land here. |
| `_edit_target_dataset` | reference to `working_dataset` | `ParaViewBackend` | session | Registered via `set_edit_target_dataset()`. Used by `_pick_surface_keys_native` as `source_dataset` for coordinate mapping, avoiding a redundant `Fetch(source)`. Same Python object as `working_dataset` — not a copy. |
| `_edit_node_id` | `str` | `ParaViewBackend` | session | ID of the edit pipeline node. Used to locate and delete the node on session end. |
| `_edit_pre_node_id` | `str` | `ParaViewBackend` | session | ID of the original node that was active before the session began. Restored to visible on discard/commit. |
| `_edit_temp_file` | `str \| None` | `ParaViewBackend` | session | Path to the temp `.vtu` written for filter-node edit sources. Deleted on session end. `None` for root-reader sessions. |
| `edit_dataset` | alias (local var) | `_pick_surface_keys_native` | per call | Convenience alias within that one method: equals `_edit_target_dataset` when a session is active, falls back to a fresh `Fetch(source)` otherwise. Read-only. |
| `selected_dataset` | `vtkUnstructuredGrid` | pick methods (local var) | per pick | Result of `ExtractSelection` + `Fetch` after a hardware pick. A small subset of source/GeometryFilter cells that ParaView determined were hit. Deleted after each pick. |

**Identity chain:**

```
edit_source  (proxy — reads same backing file as original node)
  │  servermanager.Fetch()          ← one transfer at session begin
  ▼
fetched_dataset  (vtkUG, read-only, local temp)
  │  DeepCopy() in edit_session.begin()
  ▼
working_dataset  (vtkUG, mutable)   ← also referenced as _edit_target_dataset
```

Because `edit_source` reads the same backing data as the original node, pick cell IDs
returned by `SelectSurfaceCells` already index `working_dataset` directly — no
coordinate-based remapping is needed.

---

## 6. Selection / Picking Flow

The full path from a user gesture to a list of selected cell (or surface) IDs.
Picking always runs inside an active edit session; the results feed back into
`edit_session` and update the gold overlay in the view.

### 6a. Click pick — cell or point mode

```
UI click event
 └── ctrl.pv_edit_click_selection(event)            [paraview_controllers.py]
      ├── normalize_edit_selection_ids(event)        [paraview_runtime.py]
      │    — extracts (x, y) screen coords from the raw Trame event payload,
      │      preferring repicked coords over composite toggle IDs
      └── _pick_edit_ids_at_coords(mode, x, y)
           └── pv_backend.pick_visible_cell_ids(x, y, radius=1)
                │                                    [paraview_backend.py:1764]
                ├── _candidate_pick_positions(x, y)
                │    — generates 2–4 candidate pixel coords to handle Y-axis
                │      convention differences between Trame events and ParaView
                │      display space (raw, inverted, normalized variants)
                │
                ├── clear_edit_selection_overlay()
                │    — removes the gold overlay proxy before picking so it
                │      cannot interfere with ParaView's hardware pick query
                │
                ├── for each candidate (px, py):     ← tries until non-empty result
                │    ├── _clear_selection_state(source)
                │    ├── simple.SelectSurfaceCells(Rectangle=[px±r, py±r], View=view)
                │    │    — fires ParaView's hardware selection on the rendered surface
                │    └── _fetch_selected_original_cell_ids(source)
                │         ├── simple.ExtractSelection(Input=source)
                │         ├── servermanager.Fetch(extract)       — transfer to client
                │         ├── cell_data.GetArray("vtkOriginalCellIds")   — happy path
                │         └── _source_cell_ids_from_selected_dataset()   — geometry fallback
                │              — matches selected cells back to source by point coordinates
                │                when the original-IDs array is absent (e.g. after a filter)
                │
                └── _clear_selection_state(source) + render()
                     — clears ParaView's purple selection highlight before returning
                     — returned IDs already index working_dataset (edit source reads
                       the same backing file; no remapping needed)
```

### 6b. Box drag pick — cell or point mode

```
UI box drag event
 └── ctrl.pv_edit_box_selection(event)              [paraview_controllers.py]
      └── _pick_edit_ids_in_rect(mode, x0, y0, x1, y1, behavior)
           └── pv_backend.pick_visible_cell_ids_in_rect(x0, y0, x1, y1, behavior)
                ├── clear_edit_selection_overlay()
                ├── simple.SelectSurfaceCells(Rectangle=[x0,y0,x1,y1], View=view)
                ├── _fetch_selected_original_cell_ids(source)   (same as click path)
                ├── _clear_selection_state(source) + render()
                │    — IDs already index working_dataset; no remapping step
                └── if behavior == "inside":
                     _filter_cell_ids_inside_rect(source, picked, rect)
                      — projects each candidate cell's vertices to display space
                        and keeps only cells fully contained in the drag rectangle
```

### 6c. Surface key pick (boundary face mode)

Used when the selected field is a surface/boundary field. The pick target is
a visible boundary face (a codimension-1 entity), not a volumetric cell.

```
pv_backend.pick_visible_surface_keys(x, y, radius=2)
 └── _pick_surface_keys_in_rect(rect)               [paraview_backend.py:1967]
      │
      ├── [native path — 3D meshes only]
      │    _pick_surface_keys_native(rect)
      │     ├── _surface_selection_helper_for(source)
      │     │    — creates (or reuses) a cached GeometryFilter proxy, which
      │     │      extracts boundary PolyData and is a valid SelectSurfaceCells
      │     │      target; kept hidden in the view, shown only during the pick
      │     ├── hide original display, show surface helper temporarily
      │     ├── simple.SelectSurfaceCells(rect, on temp_source)
      │     ├── simple.ExtractSelection(Input=temp_source) + servermanager.Fetch()
      │     ├── _surface_keys_from_selected_dataset(selected, source_dataset)
      │     │    ├── _iter_leaf_datasets()           — flatten composite blocks
      │     │    ├── coordinate index: lazy-built per call from source_dataset
      │     │    │    (source_dataset = _edit_target_dataset = working_dataset, so no
      │     │    │     extra Fetch; neither PassThroughPointIds nor PassThroughCellIds
      │     │    │     is used: in ParaView 6.1 both produce output-geometry indices
      │     │    │     through the proxy/Fetch round-trip — see PR #31, issue #34)
      │     │    └── _normalize_surface_keys_to_source_boundary()
      │     │         — ParaView may triangulate quads; resolves partial triangle keys
      │     │           back to the canonical quad key in the source boundary map
      │     └── returned keys already index working_dataset — no remapping step
      │          (edit source and working_dataset share the same backing geometry)
      │
      └── [fallback path — 2D meshes, or if native path returns None]
           ├── servermanager.Fetch(source)
           ├── _cached_boundary_elements(dataset)
           │    — finds codimension-1 entities (faces for 3D, edges for 2D) that
           │      appear exactly once: these are the visible boundary elements
           ├── for each boundary element:
           │    ├── _surface_element_is_visible()   — depth-buffer check at centroid
           │    ├── _project_points_to_display()    — world → pixel coords via renderer
           │    └── _polyline_intersects_rect() or all-inside check
           └── returned keys already index working_dataset — no remapping step
```

### 6d. Overlay update (after any successful pick)

```
_apply_selection_ids(picked_ids, mode, behavior)    [paraview_controllers.py]
 ├── edit_session.replace/add/subtract_selection(ids)
 ├── sync_edit_session_state()                       — update count, field readiness
 └── sync_paraview_edit_selection_overlay()
      └── pv_backend.update_edit_selection_overlay(selected_dataset)
                                                    [paraview_backend.py:1717]
           ├── clear_edit_selection_overlay()        — delete stale TrivialProducer proxy
           ├── simple.TrivialProducer("__edit_selection__")
           │    — lightweight proxy that wraps a local vtkDataSet without a reader
           ├── overlay.GetClientSideObject().SetOutput(selected_cells_dataset)
           ├── simple.Show(overlay, view)
           ├── style: gold fill, black edges, Pickable=0, LineWidth=4, PointSize=10
           │    RelativeCoincidentTopologyPolygonOffsetParameters=[-2,-2]  — always on top
           └── render()
```

---

## 7. Filter System

Filters are defined in `paraview_filter_catalog.py` and wired through
`paraview_controllers.py` → `paraview_backend.py`.

### Add-filter flow

```
UI "Filter" menu → ctrl.pv_add_filter(filter_key)    [paraview_controllers.py:689]
 └── pv_backend.add_filter(filter_key)               [paraview_backend.py:~270]
      ├── resolve spec from SUPPORTED_FILTERS or experimental catalog
      ├── getattr(simple, spec["factory"])(Input=source)  — create ParaView proxy
      ├── simple.Show(filter_proxy, view)
      ├── inherit parent visibility, representation, selected_array
      ├── hide parent display
      ├── append new node to pipeline_nodes
      └── apply_coloring() + render()
```

All filters use the same `Input=source` pattern — no special per-filter setup in the controller.

### Supported filters (all fully working, no extra setup required)

| Key | Label | ParaView factory |
|---|---|---|
| `calculator` | Calculator | `Calculator` |
| `cell_centers` | Cell Centers | `CellCenters` |
| `clip` | Clip | `Clip` |
| `contour` | Contour | `Contour` |
| `coordinates` | Coordinates | `Coordinates` |
| `glyph` | Glyph | `Glyph` |
| `reflect` | Reflect | `Reflect` |
| `slice` | Slice | `Slice` |
| `stream_tracer` | Streamline | `StreamTracer` |
| `threshold` | Threshold | `Threshold` |
| `transform` | Transform | `Transform` |
| `tube` | Tube | `Tube` |
| `warp_by_scalar` | Warp by Scalar | `WarpByScalar` |
| `warp_by_vector` | Warp by Vector | `WarpByVector` |

### Experimental filters

When `--show-experimental-filters` is passed, `ParaViewFilterCatalog` scans
`paraview.simple` at startup for any callable matching a discovery keyword list
(clip, contour, glyph, threshold, warp, etc.) and not in an exclusion list
(readers, extractors, ghost, selection, source…). Their keys are prefixed
`factory:{FactoryName}`. They appear in a separate "Experimental" section of the
filter menu and go through the same `add_filter` code path as curated filters.

---

## 8. Color / Color-Bar Logic

### Color-by change

Triggered when the user picks an array in the "Color by" selector.

```
state.selected_array change
 └── on_array_change()                         [state_handlers.py:39]
      ├── pv_backend.apply_coloring(value)
      │    ├── ColorBy(display, (assoc, name))  — binds array to display
      │    ├── _ensure_display_lookup_table()   — creates LUT if missing
      │    ├── _restore_scalar_bar_visibility() — reapplies user visibility flag
      │    └── render()
      ├── update_color_state()                  — targeted 6-key color flush
      └── call_view_update()
```

### Representation change

Triggered when the user picks a display mode (Surface, Wireframe, Points, …).

```
state.representation change
 └── on_representation_change()                [state_handlers.py:46]
      ├── pv_backend.apply_representation(value)
      │    ├── display.SetRepresentationType() — switches ParaView display mode
      │    ├── _apply_representation_to_extract_displays()
      │    └── render()
      ├── update_ui_state()                     — full flush: display_properties vary by mode
      └── call_view_update()
```

### Scalar bar visibility — two-layer preservation

Scalar bar visibility is tracked in two places that must stay in sync:

- `pv_backend._scalar_bar_visible` — Python flag, the authoritative user intent
- `state.color_bar_visible` — Trame state, what the UI toggle reflects

**Why preservation is needed at all:** ParaView's `RescaleTransferFunctionToDataRange`
internally calls `UpdateScalarBars` as a side effect, which hides the scalar bar.
This is the confirmed case from the CODEX_LOG. `ApplyPreset` and
`RescaleTransferFunction` are treated the same way defensively.

**Layer 1 — backend** (`_restore_scalar_bar_visibility` [paraview_backend.py:961]):
Called at the end of `apply_color_map_preset`, `apply_color_range`, and
`rescale_color_range_to_data`. Immediately re-asserts `_scalar_bar_visible`
back onto the display via `SetScalarBarVisibility` after the ParaView call.
By the time the backend method returns, ParaView-side visibility is already correct.

**Layer 2 — controller** (`_refresh_color_state` [paraview_controllers.py]):
Calls `update_color_state()` (a targeted 6-key Trame flush) then `render_and_push()`.
`update_color_state()` reads `_scalar_bar_visible` from the backend — since layer 1
already corrected it before returning, this always writes the right value.
The old save/restore of `state.color_bar_visible` was removed because it was always
a no-op once layer 1 was present for all LUT-mutating operations.

```
update_color_state()    — reads _scalar_bar_visible → writes 6 color state keys
render_and_push()
```

### Color-bar control actions

```
UI action → ctrl.pv_*()                        [paraview_controllers.py]

pv_apply_color_map_preset(preset)
 ├── pv_backend.apply_color_map_preset(preset)
 │    ├── lut.ApplyPreset(candidate, True)        — modifies LUT RGB points
 │    ├── _restore_scalar_bar_visibility()         — layer 1
 │    └── render()
 └── _refresh_color_state()                        — layer 2: targeted color flush

pv_apply_color_range()
 ├── pv_backend.apply_color_range(min, max)
 │    ├── lut.RescaleTransferFunction(min, max)
 │    ├── _restore_scalar_bar_visibility()
 │    └── render()
 └── _refresh_color_state()

pv_rescale_color_range_to_data()
 ├── pv_backend.rescale_color_range_to_data()
 │    ├── display.RescaleTransferFunctionToDataRange()  ← confirmed: hides scalar bar
 │    ├── _restore_scalar_bar_visibility()               — layer 1 fix
 │    └── render()
 └── _refresh_color_state()

pv_rescale_color_range_over_time()
 ├── pv_backend.rescale_color_range_over_time()
 │    └── (same pattern as above)
 └── _refresh_color_state()

pv_set_categorical_coloring(enabled)
 ├── pv_backend.set_categorical_coloring()
 │    ├── lut.InterpretValuesAsCategories / IndexedLookup = ...
 │    ├── _restore_scalar_bar_visibility()         — layer 1 (added to match other ops)
 │    └── render()
 └── _refresh_color_state()

pv_set_scalar_bar_visible(visible)
 ├── pv_backend.set_scalar_bar_visible()
 │    ├── display.SetScalarBarVisibility(view, visible)
 │    └── _scalar_bar_visible = visible           — updates the flag directly
 └── render_and_push()                            — no color flush needed; state written before call

pv_set_orientation_axes_visible(visible)
 ├── pv_backend.set_orientation_axes_visible()    — view.OrientationAxesVisibility
 └── render_and_push()                            — no color flush needed; state written before call
```

### `get_color_control_state` — reading color state from the backend

Called inside both `get_ui_state()` (full flush) and `update_color_state()` (targeted flush).

```
pv_backend.get_color_control_state()           [paraview_backend.py:773]
 ├── _get_selected_array()              — check if a non-solid array is active
 ├── _active_lookup_table()             [paraview_backend.py:1003]
 │    └── GetColorTransferFunction(array_name) on active display
 ├── _lookup_table_range(lut)           — lut.RGBPoints[0] and lut.RGBPoints[-4]
 ├── _lookup_table_categorical(lut)     — lut.Annotations != []
 └── returns {
          color_controls_enabled,      — False when solid color or no display
          color_range_min/max,          — empty strings when disabled
          color_bar_visible,            — _scalar_bar_visible instance flag
          orientation_axes_visible,     — view.OrientationAxesVisibility
          categorical_coloring          — bool
     }
```

## 9. Rendering Pipeline and Deployment

### How Trame renders to the browser

Trame does not render natively inside the browser. The user sees a **live screenshot
stream** of a server-side ParaView render window pushed over a WebSocket:

```
vtkRenderWindow  (server-side)
     │
     │  render() — GPU draws the scene into the window framebuffer
     ▼
pixel readback → JPEG/PNG compression
     │
     ▼
WebSocket push → browser <img> element updated
```

There is one `vtkRenderWindow` for the whole application lifetime. Multiple pipeline
sources share it: each `Show(source, view)` call registers a display actor in the
single render view. `Visibility = 0` removes an actor from the draw list but keeps
it in the scene graph (bounds, picking eligibility, actor traversal overhead remain).

### The visible server-side window

On a workstation with an X11 or Wayland display, the `vtkRenderWindow` opens as a
**real desktop window** — the familiar grey ParaView viewport. This is the "second
window" visible on the server desktop while the user works through the browser.

On a headless HPC node, the window is an offscreen framebuffer with no display
system involvement (EGL or OSMesa — see below).

### Why hiding the server window causes slowdown

When the X11/Wayland window is occluded (covered by another application) or
minimised, the compositor marks its framebuffer region as not needing repaint.
GPU drivers use this signal to:

- Defer `glFlush()` / `glFinish()` completion
- Reduce framebuffer sync priority
- In Wayland compositors with damage tracking: refuse to composite the hidden
  surface until it becomes visible again

The result: `render()` returns on the Python side, but the GPU has not finished
writing the framebuffer. When Trame reads pixels back for the JPEG, it either
gets a stale frame or blocks waiting for GPU sync — causing round-trip latency
to spike and the browser viewport to stall.

**This is not a bug in Trame or ParaView.** It is standard compositor behaviour
for on-screen OpenGL windows.

### EGL vs X11/OSMesa — deployment modes

```
X11 path (workstation dev):
  vtkRenderWindow (on-screen X11)
       │  compositor can throttle GPU sync for hidden windows
       ▼
  pixel readback → JPEG → WebSocket

EGL path (production HPC, recommended):
  vtkRenderWindow (offscreen GPU FBO, no window system)
       │  no compositor; GPU always flushes on render()
       ▼
  pixel readback → JPEG → WebSocket

OSMesa path (no GPU / CI):
  vtkRenderWindow (CPU Mesa software rasteriser)
       │  always synchronous; slower but portable
       ▼
  pixel readback → JPEG → WebSocket
```

Production `pvserver` deployments should use EGL
(`pvserver --force-offscreen-rendering` or a build with `-DVTK_USE_X=OFF
-DVTK_OPENGL_HAS_EGL=ON`). With EGL, window visibility has zero effect on
rendering throughput.

### Scene graph overhead from multiple proxies

Every `Show(source, view)` call registers a display actor in the render view.
Actors with `Visibility = 0` are skipped during the draw pass but still
traversed during:

- Actor bounds computation (used by `ResetCamera`)
- Picking pass setup
- Render pass state machine

Sources that add invisible actors during normal operation:

| Source | When present | Visibility |
|--------|-------------|-----------|
| Edit node display (`edit_source`) | During edit session | 1 (sole visible source) |
| All other pipeline node displays | During edit session | 0 (hidden at begin; not restored on discard) |
| GeometryFilter helper | During surface pick setup | 0 → 1 → 0 (toggled per pick) |
| `__edit_selection__` overlay | When selection is non-empty | 1 |
| `ExtractCellsByType` extracts | When cell-dimension visibility is split | 0 or 1 |

On EGL this overhead is negligible. On the X11 path it compounds with the
compositor throttling described above.
