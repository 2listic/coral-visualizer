# UI Structure

Component tree for `ui.py`. Each entry maps to a helper function or inline block
in `build_ui()`. Dialogs render in a Vuetify overlay portal regardless of where
they are declared in the source.

```
build_ui()
└── SinglePageLayout
    ├── [global dialogs — overlay portal]
    │   ├── VDialog: rescale_over_time_dialog
    │   └── VDialog: save_overwrite_dialog
    │
    ├── layout.toolbar
    │   └── _build_toolbar(ctrl)                        [ui.py:80]
    │       ├── logo + title
    │       ├── "Enter Edit Mode" button    (v_if=!edit_session_active)
    │       ├── "Save And Add To Pipeline"  (v_if=edit_session_active)
    │       ├── "Discard" button            (v_if=edit_session_active)
    │       ├── "Save Result" button
    │       └── save filename field
    │
    └── layout.content
        ├── busy indicator (VProgressCircular, absolute overlay)
        ├── _build_alerts()                             [ui.py:50]
        ├── _build_remote_browser_dialog(ctrl)          [ui.py:268]
        ├── _build_state_browser_dialog(ctrl)           [ui.py:223]
        │
        ├── _build_paraview_pipeline_panel(ctrl)        [ui.py:611]
        │   VNavigationDrawer — LEFT drawer
        │   ├── pipeline tree (VList of pipeline_items)
        │   │   └── per-node: visibility toggle, label, filter menu
        │   ├── file selector
        │   ├── upload / refresh buttons
        │   ├── "Edit session" label        (v_if=edit_session_active)
        │   ├── edit_status alert
        │   └── save_status alert
        │
        ├── _build_paraview_inspector_panel(ctrl)       [ui.py:927]
        │   VNavigationDrawer — RIGHT drawer
        │   ├── _build_inspector_tab_selector()         [ui.py:376]
        │   │   └── tab bar: Display | Properties | Information | Edit
        │   │
        │   ├── tab 0 — Display
        │   │   ├── Color by selector
        │   │   ├── Representation selector
        │   │   ├── _build_property_action_bar(ctrl)    [ui.py:341]
        │   │   └── Advanced Display Controls
        │   │       ├── color map preset
        │   │       ├── color range min/max + rescale
        │   │       ├── show/hide color bar
        │   │       ├── show/hide orientation axes
        │   │       └── categorical coloring toggle
        │   │
        │   ├── tab 1 — Properties
        │   │   └── _build_property_list(ctrl, "source_properties")  [ui.py:1417]
        │   │
        │   ├── tab 2 — Information
        │   │   └── dataset info (bounds, cell/point counts, arrays)
        │   │
        │   └── tab 3 — Edit             (v_show=edit_session_active)
        │       ├── _build_selection_tools_panel(ctrl)  [ui.py:444]  "Edit Tools"
        │       │   ├── Pick / Rotate mode buttons
        │       │   ├── Select All / Clear Selection buttons
        │       │   ├── selection count display
        │       │   ├── geometry mode selector
        │       │   ├── selection mode selector
        │       │   ├── selection behavior selector
        │       │   ├── grow selection toggle + angle slider
        │       │   └── selection status + timing
        │       ├── VDivider
        │       └── _build_edit_assign_panel(ctrl)      "Field Assignment"
        │           ├── field selector
        │           ├── expression / value field
        │           ├── available variables chip list
        │           ├── vector component syntax hint
        │           ├── "Assign to Selected" button
        │           ├── VDialog: Create New Field
        │           ├── VDialog: Overwrite Field
        │           └── apply status alert
        │
        └── _build_view_widget(render_target, ctrl)     [ui.py:20]
            VtkRemoteLocalView — main viewport
            ├── mode bound to state.mainViewMode ("remote" | "local")
            ├── click → ctrl.pv_edit_click_selection
            └── box_selection_change → ctrl.pv_edit_box_selection
```

## Key layout rules

- The left drawer (`_build_paraview_pipeline_panel`) owns pipeline navigation and
  session status only. No edit workflow controls live there.
- The right drawer (`_build_paraview_inspector_panel`) owns all inspector tabs.
  Tab 3 (Edit) is hidden outside an active edit session.
- The viewport (`_build_view_widget`) sits behind both drawers and fills the
  remaining space via absolute positioning.
- Dialogs (Create Field, Overwrite Field, rescale confirmation, save overwrite,
  state browser, remote browser) are declared inline for co-location with their
  trigger controls but render in the Vuetify overlay layer.

## Planned split (from TODO.md)

When `ui.py` is split into modules, the mapping will be:

| File | Functions |
|---|---|
| `ui/toolbar.py` | `_build_toolbar` |
| `ui/pipeline_panel.py` | `_build_paraview_pipeline_panel` |
| `ui/display_panel.py` | Display tab content, `_build_property_action_bar`, `_build_property_list` |
| `ui/edit_panel.py` | `_build_edit_assign_panel`, Selection Tools, tab 3 container |
| `ui/dialogs.py` | `_build_state_browser_dialog`, `_build_remote_browser_dialog`, global dialogs |
| `ui/__init__.py` | `build_ui` (thin wiring only) |
