"""Diagnostic payloads for ParaView edit-selection events."""


class SelectionDebugLogger:
    """Build and emit compact selection-coordinate debug records."""

    def __init__(self, *, pv_backend, debug_view):
        self._pv_backend = pv_backend
        self._debug_view = debug_view

    def log(self, kind, *, x0=None, y0=None, x1=None, y1=None, x=None, y=None):
        payload = self._payload(kind, x0=x0, y0=y0, x1=x1, y1=y1, x=x, y=y)
        if self._debug_view("edit.selection.coords", **payload):
            print(f"[selection-record] {payload}", flush=True)

    def _payload(self, kind, *, x0=None, y0=None, x1=None, y1=None, x=None, y=None):
        payload = {"kind": kind}
        view_width, view_height = self._view_size()

        if x is not None and y is not None:
            payload["pixel"] = (round(float(x), 3), round(float(y), 3))
            if view_width and view_height:
                payload["normalized"] = (
                    round(float(x) / view_width, 6),
                    round(float(y) / view_height, 6),
                )

        if None not in (x0, y0, x1, y1):
            rx0, ry0 = float(x0), float(y0)
            rx1, ry1 = float(x1), float(y1)
            payload["pixel_rect"] = (
                round(rx0, 3),
                round(ry0, 3),
                round(rx1, 3),
                round(ry1, 3),
            )
            if view_width and view_height:
                payload["normalized_rect"] = (
                    round(rx0 / view_width, 6),
                    round(ry0 / view_height, 6),
                    round(rx1 / view_width, 6),
                    round(ry1 / view_height, 6),
                )

        return payload

    def _view_size(self):
        view = getattr(self._pv_backend, "view", None)
        if view is None or not hasattr(view, "ViewSize"):
            return None, None
        try:
            width, height = view.ViewSize
            return float(width), float(height)
        except (TypeError, ValueError):
            return None, None
