# Startup, File Load, and State Sync

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
 └── on_file_change()                          [state_handlers.py]
      └── paraview_runtime.load_file(path)     [paraview_runtime.py]
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
paraview_runtime.update_ui_state()     [paraview_runtime.py]
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
ctrl.pv_add_filter(filter_key)    [paraview_controllers.py]
 ├── pv_backend.add_filter(filter_key)
 ├── update_paraview_ui_state()
 └── render_and_push()
```
