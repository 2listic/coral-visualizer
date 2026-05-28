# Filter System

Filters are defined in `paraview_filter_catalog.py` and wired through
`paraview_controllers.py` → `paraview_backend.py`.

## Add-filter flow

```
UI "Filter" menu → ctrl.pv_add_filter(filter_key)    [paraview_controllers.py]
 └── pv_backend.add_filter(filter_key)               [paraview_backend.py]
      ├── resolve spec from SUPPORTED_FILTERS or experimental catalog
      ├── getattr(simple, spec["factory"])(Input=source)  — create ParaView proxy
      ├── simple.Show(filter_proxy, view)
      ├── inherit parent visibility, representation, selected_array
      ├── hide parent display
      ├── append new node to pipeline_nodes
      └── apply_coloring() + render()
```

All filters use the same `Input=source` pattern — no special per-filter setup in the controller.

## Supported filters (all fully working, no extra setup required)

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

## Experimental filters

When `--show-experimental-filters` is passed, `ParaViewFilterCatalog` scans
`paraview.simple` at startup for any callable matching a discovery keyword list
(clip, contour, glyph, threshold, warp, etc.) and not in an exclusion list
(readers, extractors, ghost, selection, source…). Their keys are prefixed
`factory:{FactoryName}`. They appear in a separate "Experimental" section of the
filter menu and go through the same `add_filter` code path as curated filters.
