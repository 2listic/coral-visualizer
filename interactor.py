"""VTK interactor observer management for pick mode in the trame visualizer."""

from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera

from constants import VOLUME
from mesh_edit import handle_bnd_pick, handle_vol_pick


class PickInteractorManager:
    """Owns the LeftButton observer lifecycle for cell-picking in edit mode.

    In pick mode, left-click picks boundary/volume cells via vtkCellPicker.
    In camera mode, left-click is forwarded to the interactor style for rotation.
    Middle/right-click camera controls are always active.
    """

    def __init__(self, rw_interactor, renderer, render_window, state, ctrl, edit):
        self._rwi = rw_interactor
        self._renderer = renderer
        self._rw = render_window
        self._state = state
        self._ctrl = ctrl
        self._edit = edit
        self._default_style = None

    def install(self):
        """Add LeftButton observers and swap to a pick-friendly interactor style."""
        if self._edit._observer_tag is not None:
            return

        # Save the original style so we can restore it on remove()
        self._default_style = self._rwi.GetInteractorStyle()

        # Plain trackball style for middle/right-click camera control (pan, zoom)
        style = vtkInteractorStyleTrackballCamera()
        self._rwi.SetInteractorStyle(style)

        # Remove the style's left-button observers — we handle left-click ourselves
        self._rwi.RemoveObservers("LeftButtonPressEvent")
        self._rwi.RemoveObservers("LeftButtonReleaseEvent")

        self._edit._observer_tag = self._rwi.AddObserver(
            "LeftButtonPressEvent", self._on_press
        )
        self._edit._release_observer_tag = self._rwi.AddObserver(
            "LeftButtonReleaseEvent", self._on_release
        )

    def remove(self):
        """Remove picking observers and restore the original interactor style."""
        if self._edit._observer_tag is not None:
            self._rwi.RemoveObserver(self._edit._observer_tag)
            self._edit._observer_tag = None
        if self._edit._release_observer_tag is not None:
            self._rwi.RemoveObserver(self._edit._release_observer_tag)
            self._edit._release_observer_tag = None

        if self._default_style is not None:
            self._rwi.SetInteractorStyle(self._default_style)
            self._default_style = None

    def _on_press(self, obj, event):
        """Pick boundary/volume cells or forward to camera rotation."""
        if not self._state.edit_mode:
            return
        if not self._state.pick_mode:
            obj.GetInteractorStyle().OnLeftButtonDown()
            return
        x, y = obj.GetEventPosition()
        if self._state.edit_target == VOLUME:
            cell_id = handle_vol_pick(x, y, self._renderer, self._edit)
            if cell_id is not None:
                self._state.selection_count = len(self._edit.vol_selection_set)
                self._state.flush()
                self._rw.Render()
                self._ctrl.view_update()
        else:
            cell_id = handle_bnd_pick(
                x,
                y,
                self._renderer,
                self._edit,
                group_select=self._state.group_select,
                angle_threshold=self._state.angle_threshold,
            )
            if cell_id is not None:
                self._state.selection_count = len(self._edit.bnd_selection_set)
                self._state.flush()
                self._rw.Render()
                self._ctrl.view_update()

    def _on_release(self, obj, event):
        """Forward left-button release to camera style when in rotation mode."""
        if not self._state.edit_mode or self._state.pick_mode:
            return
        obj.GetInteractorStyle().OnLeftButtonUp()
