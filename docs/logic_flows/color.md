# Color / Color-Bar Logic

## Color-by change

Triggered when the user picks an array in the "Color by" selector.

```
state.selected_array change
 └── on_array_change()                         [state_handlers.py]
      ├── pv_backend.apply_coloring(value)
      │    ├── ColorBy(display, (assoc, name))  — binds array to display
      │    ├── _ensure_display_lookup_table()   — creates LUT if missing
      │    ├── _restore_scalar_bar_visibility() — reapplies user visibility flag
      │    └── render()
      ├── update_color_state()                  — targeted 6-key color flush
      └── call_view_update()
```

## Representation change

Triggered when the user picks a display mode (Surface, Wireframe, Points, …).

```
state.representation change
 └── on_representation_change()                [state_handlers.py]
      ├── pv_backend.apply_representation(value)
      │    ├── display.SetRepresentationType() — switches ParaView display mode
      │    ├── _apply_representation_to_extract_displays()
      │    └── render()
      ├── update_ui_state()                     — full flush: display_properties vary by mode
      └── call_view_update()
```

## Scalar bar visibility — two-layer preservation

Scalar bar visibility is tracked in two places that must stay in sync:

- `pv_backend._scalar_bar_visible` — Python flag, the authoritative user intent
- `state.color_bar_visible` — Trame state, what the UI toggle reflects

**Why preservation is needed at all:** ParaView's `RescaleTransferFunctionToDataRange`
internally calls `UpdateScalarBars` as a side effect, which hides the scalar bar.
This is the confirmed case from the CODEX_LOG. `ApplyPreset` and
`RescaleTransferFunction` are treated the same way defensively.

**Layer 1 — backend** (`_restore_scalar_bar_visibility` [paraview_backend.py]):
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

## Color-bar control actions

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

## `get_color_control_state` — reading color state from the backend

Called inside both `get_ui_state()` (full flush) and `update_color_state()` (targeted flush).

```
pv_backend.get_color_control_state()           [paraview_backend.py]
 ├── _get_selected_array()              — check if a non-solid array is active
 ├── _active_lookup_table()             [paraview_backend.py]
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
