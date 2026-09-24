# Logic Flows

Execution paths and data flows in the Trame/ParaView visualizer.
One file per domain — open the relevant file to trace a specific flow.

| File | Contents |
|---|---|
| [startup_load.md](startup_load.md) | App startup, file load, UI state sync, controller→backend pattern |
| [edit_session.md](edit_session.md) | Edit session lifecycle: begin, selection, assign, materialize, commit, discard |
| [picking.md](picking.md) | Selection / picking flow: click, box drag, surface key pick, overlay update |
| [filters.md](filters.md) | Filter system: add-filter flow, supported filter catalogue |
| [color.md](color.md) | Color-by change, representation change, scalar bar preservation, color-bar controls |
| [rendering.md](rendering.md) | Rendering pipeline, deployment modes (X11/EGL/OSMesa), scene graph overhead, image delivery and the trame-vtk stale-retry patch |
