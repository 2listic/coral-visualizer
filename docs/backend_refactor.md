# Backend Refactor Plan

Breaking `paraview_backend.py` (~3900 lines) into focused sub-modules under `backend/`.

## Current Structure — The Monolith

All ParaView logic currently lives in a single class inside `paraview_backend.py`.
Every caller (`paraview_runtime.py`, `paraview_controllers.py`, tests) holds a
reference to one `ParaViewBackend` instance.

```
paraview_backend.py  (ParaViewBackend class)
 │
 ├── Shared state on self
 │    ├── simple / servermanager      — ParaView API handles
 │    ├── view                        — the single RenderView proxy
 │    ├── pipeline_nodes              — list of PipelineNode dicts (source + display + metadata)
 │    ├── active_node_id              — which node is selected in the pipeline tree
 │    ├── state                       — Trame state ref (for time sync during load)
 │    └── _scalar_bar_visible         — user-intent flag for the scalar bar
 │
 ├── Pipeline management             load_file, add_filter, set_active_node,
 │                                   reload_node_file, delete_node, clear_pipeline,
 │                                   set_visibility, get_visibility
 │
 ├── State I/O                       export_app_state, import_app_state
 │
 ├── Array / display                 get_available_arrays, get_ui_state,
 │                                   apply_representation, apply_property_changes
 │
 ├── Coloring                        apply_coloring, get_color_control_state,
 │                                   apply_color_map_preset, apply_color_range,
 │                                   rescale_color_range_to_data, set_scalar_bar_visible,
 │                                   set_categorical_coloring, _restore_scalar_bar_visibility,
 │                                   _active_lookup_table, _ensure_display_lookup_table, ...
 │
 ├── Cell dimension visibility       set_cell_face_visibility,
 │                                   _apply_cell_dimension_visibility,
 │                                   _ensure_cell_dimension_extract,      ← creates ExtractCellsByType proxies
 │                                   _delete_cell_dimension_extracts, ...
 │
 ├── Selection / picking             pick_visible_cell_ids, pick_visible_cell_ids_in_rect,
 │                                   pick_visible_point_ids, pick_visible_point_ids_in_rect,
 │                                   pick_visible_surface_keys[_in_rect],
 │                                   _pick_surface_keys_native, _pick_surface_keys_in_rect,
 │                                   _fetch_selected_original_cell_ids, ...
 │
 ├── Edit-selection overlays         update_edit_selection_overlay,
 │                                   clear_edit_selection_overlay,
 │                                   set_edit_target_dataset, set_interactor_rotation
 │
 ├── Time                            get_time_state, set_time, set_time_step,
 │                                   rescale_color_range_over_time
 │
 └── Static geometry math            _boundary_codim_elements,
                                     _point_coordinate_indexes, _lookup_point_coordinate,
                                     _remap_cell_ids_between_datasets,
                                     _surface_keys_from_selected_dataset,
                                     _iter_leaf_datasets, _segments_intersect, ...
                                     (≈30 @staticmethod methods, no ParaView state)
```

The problem: unrelated concerns share state implicitly through `self`, making the
file hard to test in parts and hard to read without knowing the whole class.

---

## Target Module Layout

```
backend/
 ├── pipeline.py          — PipelineManager:  sources, nodes, filter wiring, PVD
 ├── display.py           — DisplayManager:   representation, color-by array, LUT wiring
 ├── colorbar.py          — ColorBarManager:  preset, min/max, rescale, show/hide
 ├── selection.py         — SelectionManager: picking, rubber-band, edit-selection overlays
 ├── selection_geometry.py                   — pure static geometry math (no ParaView state)
 └── export.py            — ExportManager:   VTU/state save, vtk_metadata sanitization
```

---

## Migration Strategy: Facade → Extract → Remove

### Phase 1 — extract, keep facade

`paraview_backend.py` shrinks to ~100 lines of one-liner forwarding methods.
No caller changes — the public API is identical.

```
ParaViewBackend  (facade)
 ├── self.selection  = SelectionManager(self)
 ├── self.pipeline   = PipelineManager(self)
 ├── self.coloring   = ColorBarManager(self)
 └── ...

 def pick_visible_cell_ids(self, x, y, radius=1):
     return self.selection.pick_visible_cell_ids(x, y, radius)   # one-liner
```

Sub-objects access shared state through a back-reference to the facade:

```
SelectionManager.__init__(backend)
 └── self._backend = backend

# inside a method:
self._backend.view          — the RenderView proxy
self._backend.simple        — paraview.simple
self._backend.servermanager — paraview.servermanager
self._backend.source        — active source proxy (property on backend)
```

### Phase 2 — update callers

Controllers hold direct references to sub-objects instead of the monolith:

```
# before
pv_backend.pick_visible_cell_ids(x, y)

# after
pv_backend.selection.pick_visible_cell_ids(x, y)
# or, if paraview_controllers holds it directly:
self.selection_mgr.pick_visible_cell_ids(x, y)
```

### Phase 3 — delete `paraview_backend.py`

No callers remain. The file is removed.

---

## Starting Point: `selection.py` + `selection_geometry.py`

Selection is extracted first because it is the most self-contained domain:

- **`selection_geometry.py`** has zero ParaView state dependency — all ~30 static
  methods take only raw VTK datasets, points, or a renderer. They can be unit-tested
  without a running ParaView server. No class, just plain functions.

- **`SelectionManager`** owns its own mutable state (overlay proxies, boundary cache,
  surface helper, edit target dataset, timing) that is not shared with other domains.
  Its public methods are all `pick_*`, `update_edit_selection_overlay`, and the
  edit-target/interactor helpers — a clean, narrow API.

```
selection_geometry.py          (no class, no self)
 ├── Coordinate lookups         build_point_coordinate_indexes, lookup_point_id_by_coordinate
 ├── Dataset-to-dataset maps    point_id_map_between_datasets, remap_cell_ids_between_datasets
 ├── Boundary geometry          boundary_codim_elements, surface_keys_from_selected_dataset,
 │                              normalize_surface_keys_to_source_boundary
 └── 2D geometry / projection   project_points_to_display, polyline_intersects_rect,
                                point_in_rect, point_in_polygon, segments_intersect,
                                is_display_depth_visible, iter_leaf_datasets

SelectionManager               (needs backend ref for simple, view, servermanager, source)
 ├── Own state                  _edit_target_dataset, _edit_selection_overlay,
 │                              _surface_selection_helper, _boundary_cache, _timing
 ├── Cell picking               pick_visible_cell_ids[_in_rect]
 ├── Point picking              pick_visible_point_ids[_in_rect]
 ├── Surface key picking        pick_visible_surface_keys[_in_rect]
 ├── Edit overlays              update_edit_selection_overlay, clear_edit_selection_overlay
 └── Helpers                    set_edit_target_dataset, set_interactor_rotation,
                                consume_selection_backend_timing, get_pick_debug_info
```
