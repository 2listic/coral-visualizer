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
 ├── pv_backend.export_active_dataset_for_editing()  — deep-copy dataset out of pipeline
 ├── edit_session.begin(node_id, label, filename, dataset)
 ├── pv_backend.set_edit_target_dataset(working_dataset)
 ├── state.pick_mode = True, mainViewMode = "remote"
 └── sync_edit_session_state() + render_and_push()

[Selection — click or box drag]
ctrl.pv_edit_click_selection(event) / ctrl.pv_edit_box_selection(event)
 ├── normalize_edit_selection_ids(event)  — extract screen coords or composite IDs
 ├── _pick_edit_ids_at_coords(mode, x, y) / _pick_edit_ids_in_rect(mode, ...)
 │    └── pv_backend.pick_visible_cell_ids(x, y)  — ParaView hardware pick
 └── _apply_selection_ids(picked_ids, ...)
      ├── edit_session.replace/add/subtract/flip_selection(picked_ids)
      ├── sync_edit_session_state()
      ├── sync_paraview_edit_selection_overlay()  — highlight selected cells in view
      └── render_and_push()

[Assign value]
ctrl.pv_apply_edit_field()
 └── _apply_edit_field()
      ├── _parse_field_choice()        — "cell:FieldName" → (association, name)
      ├── edit_session.assign_to_selected(field_name, association, expression)
      └── sync_edit_session_state()

[Commit]
ctrl.pv_commit_edit_session()
 └── _commit_edit_session()
      ├── save_paraview_output()            — write modified dataset to disk
      ├── edit_session.clear()
      ├── pv_backend.load_file(output_path) — add saved file back as new pipeline node
      ├── update_paraview_ui_state()
      └── render_and_push()
```

---

## 6. Filter System

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

## 7. Color / Color-Bar Logic

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
      ├── update_ui_state()                     — refreshes color_controls_* + all other state
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

**Layer 2 — controller** (`_refresh_color_controls_preserving_visibility` [paraview_controllers.py:258]):
Saves `state.color_bar_visible` before the full Trame flush and re-asserts it after.
This guards against `update_paraview_ui_state()` overwriting the Trame state with a
stale or drifted value. For preset/range/rescale this layer is redundant (layer 1
already fixed ParaView-side state), but it is the *only* guard for
`set_categorical_coloring`, which mutates the LUT but does not call
`_restore_scalar_bar_visibility` at the backend level.

```
visible = state.color_bar_visible      — save Trame state before flush
update_paraview_ui_state()             — full flush; reads _scalar_bar_visible from backend
state.color_bar_visible = visible      — re-assert (no-op for preset/range/rescale;
                                         real guard for categorical coloring)
render_and_push()
```

### Color-bar control actions

```
UI action → ctrl.pv_*()                        [paraview_controllers.py]

pv_apply_color_map_preset(preset)
 ├── pv_backend.apply_color_map_preset(preset)
 │    ├── lut.ApplyPreset(candidate, True)        — modifies LUT RGB points
 │    ├── _restore_scalar_bar_visibility()         — layer 1: re-asserts on ParaView
 │    └── render()
 └── _refresh_color_controls_preserving_visibility()  — layer 2: guards Trame state

pv_apply_color_range()
 ├── pv_backend.apply_color_range(min, max)
 │    ├── lut.RescaleTransferFunction(min, max)
 │    ├── _restore_scalar_bar_visibility()
 │    └── render()
 └── _refresh_color_controls_preserving_visibility()

pv_rescale_color_range_to_data()
 ├── pv_backend.rescale_color_range_to_data()
 │    ├── display.RescaleTransferFunctionToDataRange()  ← confirmed: hides scalar bar
 │    ├── _restore_scalar_bar_visibility()               — layer 1 fix
 │    └── render()
 └── _refresh_color_controls_preserving_visibility()

pv_rescale_color_range_over_time()
 ├── pv_backend.rescale_color_range_over_time()
 │    └── (same pattern as above)
 └── _refresh_color_controls_preserving_visibility()

pv_set_categorical_coloring(enabled)
 ├── pv_backend.set_categorical_coloring()
 │    ├── lut.InterpretValuesAsCategories / IndexedLookup = ...
 │    └── render()                               — NO _restore_scalar_bar_visibility here
 └── _refresh_color_controls_preserving_visibility()  — layer 2 is the only guard

pv_set_scalar_bar_visible(visible)
 ├── pv_backend.set_scalar_bar_visible()
 │    ├── display.SetScalarBarVisibility(view, visible)
 │    └── _scalar_bar_visible = visible           — updates the flag directly
 └── render_and_push()                            — no flush; state written before call

pv_set_orientation_axes_visible(visible)
 ├── pv_backend.set_orientation_axes_visible()    — view.OrientationAxesVisibility
 └── render_and_push()                            — no flush; state written before call
```

### `get_color_control_state` — reading color state from the backend

Called inside `get_ui_state()` on every full flush.

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
