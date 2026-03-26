"""Scalar bar lifecycle management for the trame visualizer."""

from vtkmodules.vtkRenderingAnnotation import vtkScalarBarActor

from constants import SCALAR_BAR_ACTIVE_ARRAY, SCALAR_BAR_BOUNDARY


def build_scalar_bar(
    lut, title, position=(0.05, 0.05), width=0.08, height=0.35, max_labels=20
):
    """Create a positioned vtkScalarBarActor for the given LUT.

    max_labels caps the number of tick/category labels shown. For categorical
    LUTs with many IDs this prevents the bar from becoming unreadably dense.
    """
    bar = vtkScalarBarActor()
    bar.SetLookupTable(lut)
    bar.SetTitle(title)
    bar.SetOrientationToVertical()
    bar.SetTextPositionToPrecedeScalarBar()
    bar.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
    bar.GetPositionCoordinate().SetValue(position[0], position[1])
    bar.SetWidth(width)
    bar.SetHeight(height)
    bar.SetNumberOfLabels(min(lut.GetNumberOfTableValues(), max_labels))
    bar.UnconstrainedFontSizeOn()
    bar.GetTitleTextProperty().SetFontSize(25)
    bar.GetLabelTextProperty().SetFontSize(10)
    return bar


_SLOT_CONFIG = {
    SCALAR_BAR_ACTIVE_ARRAY: {"position": (0.05, 0.05), "height": 0.35},
    SCALAR_BAR_BOUNDARY: {"position": (0.05, 0.45), "height": 0.35},
}


class ScalarBarManager:
    """Owns the two scalar bar actors (active coloring + boundary ID) in the renderer.

    Slots:
        SCALAR_BAR_ACTIVE_ARRAY — bottom-left bar: current Color-by array in view mode, or
                   MaterialID in volume edit target.
        SCALAR_BAR_BOUNDARY — upper-left bar: boundary IDs in view mode (when MaterialID is
                   selected) or boundary edit target.
    """

    def __init__(self, renderer):
        self._renderer = renderer
        self._bars = {SCALAR_BAR_ACTIVE_ARRAY: None, SCALAR_BAR_BOUNDARY: None}

    def set_bar(self, slot, lut, label):
        """Replace *slot* bar with one built from *lut* and *label*."""
        self.remove_bar(slot)
        cfg = _SLOT_CONFIG[slot]
        bar = build_scalar_bar(
            lut, label, position=cfg["position"], width=0.08, height=cfg["height"]
        )
        self._bars[slot] = bar
        self._renderer.AddActor(bar)

    def remove_bar(self, slot):
        """Remove the *slot* bar from the renderer if present."""
        if self._bars[slot] is not None:
            self._renderer.RemoveActor(self._bars[slot])
            self._bars[slot] = None
