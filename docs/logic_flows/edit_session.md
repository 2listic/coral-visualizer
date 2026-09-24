# Edit Session Flow

## 5. Edit Session Lifecycle

### 5a. High-level call flow

```
[Begin]
ctrl.pv_begin_edit_session()
 ├── pv_backend.export_active_dataset_for_editing()
 │    ├── creates a real edit pipeline node (kind="edit", label="✏ Editing: {original}")
 │    │    root reader → OpenDataFile(same backing file)   — no temp file write
 │    │    filter node → write temp VTU, then OpenDataFile — avoids MPI-collapsing Fetch
 │    ├── hides all existing pipeline nodes (Visibility=0)
 │    └── Fetch(edit_source) → one local vtkUnstructuredGrid passed back as "dataset"
 ├── edit_session.begin(node_id, label, filename, dataset)
 │    — DeepCopy into working_dataset, reset all session state,
 │      pre-compute CellCenters array for expression evaluation
 ├── pv_backend.set_edit_target_dataset(working_dataset)
 │    — stores reference so surface picks use working_dataset as source_dataset
 │      without a redundant Fetch; also builds two session-scoped geometry caches:
 │        _edit_source_point_indexes  — coordinate index over all source points (#34 B5 fix)
 │        _edit_boundary_elements    — boundary codim-1 face map over all cells  (B5b fix)
 ├── update_paraview_ui_state()   — sync pipeline panel to show the edit node
 ├── state.pick_mode = True, mainViewMode = "remote"
 │    — enables hardware picking; forces server-side rendering
 └── sync_edit_session_state() + render_and_push()

[Selection — click or box drag]
ctrl.pv_edit_click_selection(event) / ctrl.pv_edit_box_selection(event)
 ├── normalize_edit_selection_ids(event)   — extract screen coords or composite IDs
 ├── _pick_edit_ids_at_coords / _pick_edit_ids_in_rect   — dispatch to click or rect pick
 │    └── pv_backend.pick_visible_cell_ids(...)          — ParaView hardware pick
 └── _apply_selection_ids(picked_ids, ...)
      ├── edit_session.replace/add/subtract/flip_selection(ids)
      ├── sync_edit_session_state()         — update selection count and field readiness
      ├── sync_paraview_edit_selection_overlay()  — highlight selected cells in view
      └── render_and_push()

[Assign value]
ctrl.pv_apply_edit_field()                               [paraview_controllers.py]
 └── pv_apply_edit_field() → _apply_edit_field()
      ├── _parse_field_choice()            — "cell:FieldName" → (association, field_name)
      ├── _apply_geometry_options_for_association(association)
      │    — sets edit_session.geometry_mode; forces "point" for point fields
      ├── edit_session.assign_to_selected(field_name, association, expression)
      │    — see §5d for full detail
      └── sync_edit_session_state()        — refresh dirty flag and field state in UI

[Commit]
ctrl.pv_commit_edit_session()
 └── opens save dialog (state.save_dialog = True, save_dialog_action = "commit")

User confirms in dialog → _commit_edit_session(filename, overwrite)
 ├── save_paraview_output(filename, overwrite)     [file_operations.py]
 │    ├── resolve_paraview_output_path()           — path-safe, confines to data_directory
 │    ├── edit_session.save(output_path)           — see §5e for full detail
 │    └── refresh_available_files()                — update file browser
 ├── edit_session.clear()
 ├── pv_backend.clear_edit_target_dataset()
 │    — deletes edit node proxy, restores pre-edit node visibility,
 │      clears _edit_source_point_indexes, _edit_boundary_elements, _edit_target_dataset
 ├── pv_backend.load_file(output_path)    — add saved file as new pipeline node
 ├── update_paraview_ui_state()           — full flush: new node visible in pipeline
 └── render_and_push()

[Discard]
ctrl.pv_discard_edit_session()                           [paraview_controllers.py]
 ├── edit_session.clear()              — reset all session state, release working_dataset
 ├── pv_backend.clear_edit_target_dataset()
 │    — deletes edit node, restores pre-edit node, clears geometry caches
 ├── update_paraview_ui_state()        — full state flush: back to pre-edit pipeline
 ├── sync_edit_session_state()         — edit_session_active = False, etc.
 ├── sync_paraview_edit_selection_overlay()   — remove gold overlay
 ├── state resets (save_filename, selection_count, inspector_tab, edit_selection_event)
 └── call_view_update(reset_camera=True) + render_and_push()
```

---

### 5b. Data movement, process model, and bottlenecks

The diagram below tracks what happens to the mesh data across the same phases as §5a.
Read §5a to trace function calls; read this to understand data ownership, copies, and
where the performance costs land.

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
    ├── stores reference to working_dataset so surface picks (_pick_surface_keys_native)
    │    can use it as source_dataset for coordinate mapping without a second Fetch.
    ├── _edit_source_point_indexes = _point_coordinate_indexes(working_dataset)
    │    — O(n_points) scan built once; avoids per-pick rebuild (B5 fix)
    └── _edit_boundary_elements = _boundary_codim_elements(working_dataset)
         — O(n_cells × faces) scan built once; avoids per-pick rebuild (B5b fix)

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
         ├── materialize_surface_selection()  — insert missing boundary face cells (surface mode)
         ├── _remove_internal_edit_arrays()   — strips CellCenters before write
         ▼
  vtkXMLUnstructuredGridWriter.Write()     ⚠ full mesh write to disk
         │
         ▼
  pv_backend.clear_edit_target_dataset()   deletes edit node, restores pre-edit node,
         │                                 clears geometry caches
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

### 5c. Dataset naming conventions

The edit-session code uses several "dataset" variables with similar names.
This is the reference for what each one is, who owns it, how long it lives, and why it exists.

| Name | Type | Owner | Lifetime | Role |
|---|---|---|---|---|
| `source` | ParaView proxy (`vtkSMProxy`) | `ParaViewBackend` (property) | permanent | During an edit session this is the **edit node** proxy (kind="edit"). Used for hardware picks (`SelectSurfaceCells`) and `Fetch` calls. Never mutated. |
| `source_dataset` | `vtkUnstructuredGrid` | local var (caller) | per call | Result of `servermanager.Fetch(source)`. A read-only local copy used for coordinate mapping in surface picks. Fetched on demand; not stored between calls. |
| `working_dataset` | `vtkUnstructuredGrid` | `EditSession` | session | `DeepCopy` of the dataset fetched from the edit source at session begin. The **mutation target**: field assignments, expression results, and selection tracking all land here. |
| `_edit_target_dataset` | reference to `working_dataset` | `ParaViewBackend` | session | Registered via `set_edit_target_dataset()`. Used by `_pick_surface_keys_native` as `source_dataset` for coordinate mapping, avoiding a redundant `Fetch(source)`. Same Python object as `working_dataset` — not a copy. |
| `_edit_source_point_indexes` | `list[dict]` | `ParaViewBackend` | session | Pre-built at session begin by `set_edit_target_dataset()`. Coordinate index over all source points; passed to `_surface_keys_from_selected_dataset` to avoid O(n_points) rebuild per pick (B5 fix). |
| `_edit_boundary_elements` | `dict` | `ParaViewBackend` | session | Pre-built at session begin by `set_edit_target_dataset()`. Boundary codim-1 face map over all cells; passed to `_normalize_surface_keys_to_source_boundary` to avoid O(n_cells×faces) rebuild per pick (B5b fix). |
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

### 5d. Assign value — full detail

```
edit_session.assign_to_selected(field_name, association, expression)
                                                         [edit_session.py]
 ├── guards: session active, field exists, is scalar
 ├── _selected_ids_for_association(association)
 │    ├── [point mode]   sorted(selected_point_ids)
 │    ├── [surface mode]
 │    │    ├── materialize_surface_selection()            — see §5e
 │    │    └── _selected_surface_cell_ids()
 │    │         — scans ALL codim-1 cells in working_dataset (pre-existing + newly inserted),
 │    │           builds key→cell_id map, returns IDs matching selected_surface_keys.
 │    │           Pre-existing boundary cells are found here too, so skipping them in
 │    │           materialize_surface_selection never causes them to miss the assignment.
 │    └── [volume mode]  sorted(selected_cell_ids)
 ├── _evaluate_expression(association, expression)
 │    ├── [cell] _ensure_cell_centers_array()   — adds CellCenters to cell data if absent
 │    ├── vtkArrayCalculator(working_dataset)
 │    │    — registers all scalar/vector arrays by name so they can appear in expression
 │    │    — evaluates expression; result stored as temporary "__edit_result__" array
 │    │    — supports spatial coordinates via CellCenters (cell) or coords (point)
 │    └── reads result array → returns list[float], one value per cell or point
 └── for each selected_id:
      existing.SetComponent(idx, 0, computed[idx])
      — writes scalar value directly into working_dataset's field array
      target_data.SetActiveScalars(field_name)
      working_dataset.Modified()
      self.dirty = True
```

---

### 5e. Surface materialization — full detail

`materialize_surface_selection()` makes selected boundary faces *physical* — writes them
as real cells in `working_dataset` so they can carry field data and be serialized.

Called from `_selected_ids_for_association` before resolving cell IDs (surface mode),
and from `EditSession.save()` before writing to disk.

```
materialize_surface_selection()                          [edit_session.py]
 │
 ├── guards: active, dataset not None, geometry_mode == "surface",
 │           selected_surface_keys not empty, top_dim >= 2
 │
 ├── _remove_internal_edit_arrays()
 │    — strips CellCenters and other scratch arrays before modifying dataset structure
 │
 ├── _surface_boundary_map_for_top_cells()   (cached)
 │    — iterates all top-dimensional cells (e.g. tetras), enumerates every face/edge,
 │      keeps only faces appearing exactly once across all cells (true boundary).
 │    — returns {sorted_point_ids_tuple: (cell_type, ordered_point_ids, owner_cell_id)}
 │
 ├── _existing_codim_keys(top_dim - 1)       (cached)
 │    — scans working_dataset for cells already at codim-1 dimension (e.g. triangles
 │      for a tet mesh), builds their key set to avoid double-insertion.
 │
 ├── missing_keys = [k for k in sorted(selected_surface_keys)
 │                   if k in boundary_map and k not in existing]
 │    — only faces that are: selected AND confirmed boundary AND not yet physical cells.
 │      Sorted for deterministic insertion order; idempotent on repeated calls.
 │    → returns 0 early if no faces need inserting
 │
 ├── for each missing key:
 │    ├── retrieve (cell_type, point_ids, owner_cell_id) from boundary_map
 │    ├── dataset.InsertNextCell(cell_type, id_list)
 │    └── record new_cell_id → owner_cell_id in owner_cell_ids map
 │
 ├── _extend_cell_data_for_new_cells(dataset, old_cell_count, owner_cell_ids)
 │    — for every cell data array, appends a tuple copied from the owner volume cell's row,
 │      keeping array lengths consistent with the new cell count and giving the new face
 │      the same field values as its parent
 │
 ├── dataset.Modified()
 ├── self.dirty = True
 ├── _invalidate_geometry_caches()   — dataset shape changed; boundary/adjacency caches stale
 └── return len(missing_keys)
```

**Why pre-existing faces are handled correctly:**
`materialize_surface_selection` skips faces already in `existing` (no duplicate insertion),
but `_selected_surface_cell_ids` (called right after) scans *all* codim-1 cells and
returns IDs for every selected key regardless of when the cell was inserted.
So a pre-existing face still receives the field assignment — `existing` only guards structural integrity.
