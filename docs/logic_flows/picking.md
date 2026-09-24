# Selection / Picking Flow

The full path from a user gesture to a list of selected cell (or surface) IDs.
Picking always runs inside an active edit session; the results feed back into
`edit_session` and update the gold overlay in the view.

## 6a. Click pick — cell or point mode

```
UI click event
 └── ctrl.pv_edit_click_selection(event)            [paraview_controllers.py]
      ├── normalize_edit_selection_ids(event)        [paraview_runtime.py]
      │    — extracts (x, y) screen coords from the raw Trame event payload,
      │      preferring repicked coords over composite toggle IDs
      └── _pick_edit_ids_at_coords(mode, x, y)
           └── pv_backend.pick_visible_cell_ids(x, y, radius=1)
                │                                    [paraview_backend.py]
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

## 6b. Box drag pick — cell or point mode

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

## 6c. Surface key pick (boundary face mode)

Used when the selected field is a surface/boundary field. The pick target is
a visible boundary face (a codimension-1 entity), not a volumetric cell.

```
pv_backend.pick_visible_surface_keys(x, y, radius=2)
 └── _pick_surface_keys_in_rect(rect)               [paraview_backend.py]
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
      │     ├── _surface_keys_from_selected_dataset(
      │     │       selected,
      │     │       source_dataset=_edit_target_dataset,      — working_dataset reference
      │     │       source_point_indexes=_edit_source_point_indexes,  — pre-built (#34 B5 fix)
      │     │       prebuilt_boundary=_edit_boundary_elements         — pre-built (#34 B5b fix)
      │     │   )
      │     │    ├── _iter_leaf_datasets()           — flatten composite blocks
      │     │    ├── coordinate lookup via source_point_indexes
      │     │    │    — built once at session begin; O(1) per point lookup during pick.
      │     │    │      Neither PassThroughPointIds nor PassThroughCellIds is used:
      │     │    │      in ParaView 6.1 both produce output-geometry indices through the
      │     │    │      proxy/Fetch round-trip — see PR #31, issue #34.
      │     │    └── _normalize_surface_keys_to_source_boundary(
      │     │             keys, prebuilt_boundary=_edit_boundary_elements
      │     │         )
      │     │         — ParaView may triangulate quads; resolves partial triangle keys
      │     │           back to the canonical quad key in the source boundary map.
      │     │           Uses pre-built boundary map; no per-pick rebuild.
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

## 6d. Overlay update (after any successful pick)

```
_apply_selection_ids(picked_ids, mode, behavior)    [paraview_controllers.py]
 ├── edit_session.replace/add/subtract_selection(ids)
 ├── sync_edit_session_state()                       — update count, field readiness
 └── sync_paraview_edit_selection_overlay()
      └── pv_backend.update_edit_selection_overlay(selected_dataset)
                                                    [paraview_backend.py]
           ├── clear_edit_selection_overlay()        — delete stale TrivialProducer proxy
           ├── simple.TrivialProducer("__edit_selection__")
           │    — lightweight proxy that wraps a local vtkDataSet without a reader
           ├── overlay.GetClientSideObject().SetOutput(selected_cells_dataset)
           ├── simple.Show(overlay, view)
           ├── style: gold fill, black edges, Pickable=0, LineWidth=4, PointSize=10
           │    RelativeCoincidentTopologyPolygonOffsetParameters=[-2,-2]  — always on top
           └── render()
```
