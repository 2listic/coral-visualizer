# Rendering Pipeline and Deployment

## How Trame renders to the browser

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

## The visible server-side window

On a workstation with an X11 or Wayland display, the `vtkRenderWindow` opens as a
**real desktop window** — the familiar grey ParaView viewport. This is the "second
window" visible on the server desktop while the user works through the browser.

On a headless HPC node, the window is an offscreen framebuffer with no display
system involvement (EGL or OSMesa — see below).

## Why hiding the server window causes slowdown

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

## EGL vs X11/OSMesa — deployment modes

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

## Scene graph overhead from multiple proxies

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
| All other pipeline node displays | During edit session | 0 (hidden at begin; restored on discard/commit) |
| GeometryFilter helper | During surface pick setup | 0 → 1 → 0 (toggled per pick) |
| `__edit_selection__` overlay | When selection is non-empty | 1 |
| `ExtractCellsByType` extracts | When cell-dimension visibility is split | 0 or 1 |

On EGL this overhead is negligible. On the X11 path it compounds with the
compositor throttling described above.
