"""VTK backend orchestration helpers."""

from constants import (
    ARRAY_SOLID,
    CELL_PREFIX,
    MANIFOLD_ID_ARRAY,
    MATERIAL_ID_ARRAY,
    SCALAR_BAR_ACTIVE_ARRAY,
    SCALAR_BAR_BOUNDARY,
)
from mesh_edit import setup_edit_state
from vtk_pipeline import (
    apply_categorical_coloring,
    apply_coloring,
    apply_representation,
    build_visualization,
    get_available_arrays,
)


class VtkRuntime:
    """Own the mutable VTK scene state and related update helpers."""

    def __init__(
        self,
        *,
        state,
        renderer,
        render_window,
        scalar_bars,
        edit_state,
        call_view_update,
    ):
        self.state = state
        self.renderer = renderer
        self.render_window = render_window
        self.scalar_bars = scalar_bars
        self.edit_state = edit_state
        self.call_view_update = call_view_update
        self.viz = None
        self.active_lut = None

    def _array_label(self, array_value):
        if array_value == f"{CELL_PREFIX}{MATERIAL_ID_ARRAY}":
            return "Material ID"
        if array_value == f"{CELL_PREFIX}{MANIFOLD_ID_ARRAY}":
            return "Manifold ID"
        if ":" in array_value:
            return array_value.split(":", 1)[1]
        return array_value

    def update_scalar_bars(self, active_lut, array_value):
        """Manage scalar bars for the current VTK scene."""
        if active_lut is not None:
            self.scalar_bars.set_bar(
                SCALAR_BAR_ACTIVE_ARRAY, active_lut, self._array_label(array_value)
            )
        else:
            self.scalar_bars.remove_bar(SCALAR_BAR_ACTIVE_ARRAY)

        is_material_id = array_value == f"{CELL_PREFIX}{MATERIAL_ID_ARRAY}"
        bnd_lut = (
            self.viz.bnd_luts.get(MATERIAL_ID_ARRAY)
            if is_material_id and self.viz
            else None
        )
        if bnd_lut is not None:
            self.scalar_bars.set_bar(SCALAR_BAR_BOUNDARY, bnd_lut, "Boundary ID")
        else:
            self.scalar_bars.remove_bar(SCALAR_BAR_BOUNDARY)

    def render_and_push(self):
        """Render the VTK view and push the update to the client."""
        self.render_window.Render()
        self.call_view_update()

    def apply_edit_coloring(self, edit_target):
        """Apply edit-mode coloring and actor visibility for the current target."""
        if edit_target == "boundary":
            if self.edit_state.merged_bnd_actor:
                self.edit_state.merged_bnd_actor.SetVisibility(1)
                apply_representation(
                    None, self.edit_state.merged_bnd_actor, self.state.representation
                )
            if (
                self.edit_state.merged_bnd_dataset is not None
                and self.edit_state.merged_bnd_mapper is not None
            ):
                lut, _ = apply_categorical_coloring(
                    self.edit_state.merged_bnd_mapper,
                    self.edit_state.merged_bnd_dataset,
                    MATERIAL_ID_ARRAY,
                )
                if lut is not None:
                    self.scalar_bars.set_bar(SCALAR_BAR_BOUNDARY, lut, "Boundary ID")
            if self.viz:
                self.viz.vol_mapper.ScalarVisibilityOff()
                self.viz.vol_actor.GetProperty().SetColor(0.7, 0.7, 0.7)
                apply_representation(
                    self.viz.vol_actor, None, self.state.representation
                )
            self.scalar_bars.remove_bar(SCALAR_BAR_ACTIVE_ARRAY)
            return

        if self.edit_state.merged_bnd_actor:
            self.edit_state.merged_bnd_actor.SetVisibility(0)
        self.scalar_bars.remove_bar(SCALAR_BAR_BOUNDARY)
        if self.edit_state.vol_dataset is None or self.viz is None:
            return

        apply_representation(self.viz.vol_actor, None, self.state.representation)
        lut, _ = apply_categorical_coloring(
            self.viz.vol_mapper, self.edit_state.vol_dataset, MATERIAL_ID_ARRAY
        )
        if lut is None:
            return
        self.viz.vol_dataset.Modified()
        self.scalar_bars.set_bar(SCALAR_BAR_ACTIVE_ARRAY, lut, "Material ID")

    def apply_representation(self, representation):
        """Apply the chosen representation to all VTK scene actors."""
        if self.viz is not None:
            apply_representation(self.viz.vol_actor, self.viz.bnd_actor, representation)
        if self.edit_state.merged_bnd_actor:
            apply_representation(None, self.edit_state.merged_bnd_actor, representation)
        if self.edit_state.vol_selection_actor:
            apply_representation(
                None, self.edit_state.vol_selection_actor, representation
            )
        if self.edit_state.bnd_selection_actor:
            apply_representation(
                None, self.edit_state.bnd_selection_actor, representation
            )

    def apply_coloring(self, selected_array):
        """Apply coloring to the current VTK scene."""
        if self.viz is None:
            return

        self.active_lut = apply_coloring(
            self.viz.vol_actor,
            self.viz.vol_mapper,
            self.viz.vol_dataset,
            selected_array,
            self.viz.vol_luts,
        )
        if self.viz.bnd_actor is not None:
            apply_coloring(
                self.viz.bnd_actor,
                self.viz.bnd_mapper,
                self.viz.bnd_dataset,
                selected_array,
                self.viz.bnd_luts,
            )
        self.update_scalar_bars(self.active_lut, selected_array)
        self.render_and_push()

    def load_file(self, selected_file):
        """Load a dataset through the VTK backend and refresh derived state."""
        self.viz = build_visualization(selected_file, self.renderer)

        arrays = get_available_arrays(self.viz.full_dataset)
        default_array = next(
            (
                item["value"]
                for item in arrays
                if item["value"] == f"{CELL_PREFIX}{MATERIAL_ID_ARRAY}"
            ),
            arrays[1]["value"] if len(arrays) > 1 else ARRAY_SOLID,
        )

        self.active_lut = apply_coloring(
            self.viz.vol_actor,
            self.viz.vol_mapper,
            self.viz.vol_dataset,
            default_array,
            self.viz.vol_luts,
        )
        if self.viz.bnd_actor is not None:
            apply_coloring(
                self.viz.bnd_actor,
                self.viz.bnd_mapper,
                self.viz.bnd_dataset,
                default_array,
                self.viz.bnd_luts,
            )
        apply_representation(
            self.viz.vol_actor, self.viz.bnd_actor, self.state.representation
        )
        self.update_scalar_bars(self.active_lut, default_array)
        setup_edit_state(self.edit_state, self.viz, self.renderer)

        self.state.available_arrays = arrays
        self.state.selected_array = default_array
        self.state.has_boundary = (
            self.viz.bnd_actor is not None
            or self.edit_state.merged_bnd_dataset is not None
        )
        self.state.error_message = ""
        self.state.selection_count = 0
        self.state.save_status = ""
        self.render_and_push()

    def reset_camera(self):
        """Reset the current VTK camera."""
        if self.renderer is None or self.render_window is None:
            return
        self.renderer.ResetCamera()
        self.render_and_push()

    def reset_view(self):
        """Restore a canonical view using the VTK renderer."""
        if self.renderer is None or self.render_window is None:
            return

        camera = self.renderer.GetActiveCamera()
        bounds = self.renderer.ComputeVisiblePropBounds()
        if bounds and bounds[0] <= bounds[1]:
            xmin, xmax, ymin, ymax, zmin, zmax = bounds
            center = (
                0.5 * (xmin + xmax),
                0.5 * (ymin + ymax),
                0.5 * (zmin + zmax),
            )
            span_x = max(abs(xmax - xmin), 1e-6)
            span_y = max(abs(ymax - ymin), 1e-6)
            span_z = max(abs(zmax - zmin), 1e-6)
            distance = max(span_x, span_y, span_z) * 2.5
            camera.SetFocalPoint(*center)
            camera.SetPosition(center[0], center[1], center[2] + distance)
            camera.SetViewUp(0.0, 1.0, 0.0)
        self.renderer.ResetCamera()
        self.renderer.ResetCameraClippingRange()
        self.render_and_push()
