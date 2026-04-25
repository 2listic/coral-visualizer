"""ParaView backend adapter for the Trame visualizer."""

from __future__ import annotations

import importlib.util
import os
from math import isfinite

from constants import ARRAY_SOLID, CELL_PREFIX, MATERIAL_ID_ARRAY, POINT_PREFIX
from edit_session import EditSession
from paraview_filter_catalog import ParaViewFilterCatalog, SUPPORTED_FILTERS
from paraview_property_inspector import ParaViewPropertyInspector
from vtkmodules.vtkCommonDataModel import vtkDataSet
from vtkmodules.vtkIOLegacy import vtkDataSetWriter


def is_paraview_available():
    """Return True when both ParaView and the trame ParaView widget are importable."""
    try:
        return all(
            importlib.util.find_spec(name) is not None
            for name in ("paraview", "trame.widgets.paraview")
        )
    except ModuleNotFoundError:
        return False


class ParaViewBackend:
    """Thin adapter around ``paraview.simple`` with lightweight pipeline state."""

    def __init__(self, data_directory=None, show_experimental_filters=True):
        if not is_paraview_available():
            raise RuntimeError(
                "ParaView backend requested but 'paraview' or 'trame.widgets.paraview' "
                "is not available in this Python environment."
            )

        from paraview import simple
        from paraview import servermanager

        self.simple = simple
        self.servermanager = servermanager
        self.view = None
        self.pipeline_nodes = []
        self.active_node_id = None
        self.data_directory = os.path.abspath(data_directory) if data_directory else None
        self._filter_counts = {key: 0 for key in SUPPORTED_FILTERS}
        self.filter_catalog = ParaViewFilterCatalog(
            self.simple, show_experimental_filters=show_experimental_filters
        )
        self.property_inspector = ParaViewPropertyInspector()
        self._edit_selection_overlay = None
        self._edit_selection_display = None

    @property
    def source(self):
        """Return the active ParaView source proxy."""
        node = self._get_active_node()
        return None if node is None else node["source"]

    @property
    def display(self):
        """Return the active ParaView display proxy."""
        node = self._get_active_node()
        return None if node is None else node["display"]

    def initialize_view(self):
        """Create the render view used by Trame."""
        self.simple._DisableFirstRenderCameraReset()
        self.view = self.simple.GetActiveViewOrCreate("RenderView")
        self.view.MakeRenderWindowInteractor(True)
        self.simple.SetActiveView(self.view)
        return self.view

    def load_file(self, filename):
        """Load a dataset into the current view and make it active."""
        if self.view is None:
            self.initialize_view()

        source = self.simple.OpenDataFile(filename)
        if source is None:
            raise RuntimeError(f"ParaView could not open file: {filename}")

        source.UpdatePipeline()
        self.simple.SetActiveSource(source)
        display = self.simple.Show(source, self.view)
        display.SetRepresentationType(
            self._normalize_representation("Surface with Edges")
        )

        node = self._make_node(
            source=source,
            display=display,
            filename=filename,
            kind="source",
            label=os.path.basename(self._relative_path(filename) or filename or "source"),
        )
        self.pipeline_nodes.append(node)
        self.set_active_node(node["id"])
        self.reset_camera()

        arrays = self.get_available_arrays()
        default_array = next(
            (
                item["value"]
                for item in arrays
                if item["value"] == f"{CELL_PREFIX}{MATERIAL_ID_ARRAY}"
            ),
            arrays[1]["value"] if len(arrays) > 1 else ARRAY_SOLID,
        )
        return arrays, default_array

    def get_available_filters(self):
        """Return supported and experimental filter lists for the UI."""
        return self.filter_catalog.get_available_filters()

    def add_filter(self, filter_key):
        """Create a new filter node from the active pipeline node."""
        node = self._get_active_node()
        if node is None:
            raise RuntimeError("No active source available for filtering")

        spec = SUPPORTED_FILTERS.get(filter_key)
        if spec is None:
            spec = self.filter_catalog.experimental_filter_spec(filter_key)
        if spec is None:
            raise ValueError(f"Unsupported filter: {filter_key}")

        source = node["source"]
        display = node["display"]
        selected_array = self._get_selected_array()
        representation = self._get_representation()
        visible = bool(display.Visibility) if display is not None else True

        filter_proxy = getattr(self.simple, spec["factory"])(Input=source)
        filter_proxy.UpdatePipeline()
        self.simple.SetActiveSource(filter_proxy)
        filter_display = self.simple.Show(filter_proxy, self.view)
        filter_display.Visibility = 1 if visible else 0
        filter_display.SetRepresentationType(self._normalize_representation(representation))
        if display is not None:
            display.Visibility = 0

        self._filter_counts[filter_key] = self._filter_counts.get(filter_key, 0) + 1
        filter_node = self._make_node(
            source=filter_proxy,
            display=filter_display,
            filename=node["filename"],
            kind="filter",
            label=f"{spec['label']} {self._filter_counts[filter_key]}",
            parent_id=node["id"],
            filter_key=filter_key,
        )
        self.pipeline_nodes.append(filter_node)
        self.set_active_node(filter_node["id"])
        self.apply_coloring(self._resolve_available_array_value(selected_array))
        self.render()
        return filter_node["id"]

    def default_output_filename(self):
        """Return a suggested output filename for the active pipeline node."""
        node = self._get_active_node()
        if node is None:
            return "output" + self.default_output_extension()
        label = node.get("label") or "output"
        safe_label = "".join(
            char if char.isalnum() or char in {"-", "_"} else "_" for char in label
        ).strip("_")
        if not safe_label:
            safe_label = "output"
        return safe_label + self.default_output_extension()

    def default_output_extension(self):
        """Return the default output extension for saved pipeline results."""
        return self._default_output_extension()

    def save_active_data(self, output_path):
        """Save the currently active pipeline result to a new file."""
        source = self.source
        if source is None:
            raise RuntimeError("No active pipeline item to save")
        source.UpdatePipeline()
        suffix = os.path.splitext(str(output_path))[1].lower()
        if suffix == ".vtk":
            dataset = self.servermanager.Fetch(source)
            if isinstance(dataset, vtkDataSet):
                writer = vtkDataSetWriter()
                writer.SetFileName(str(output_path))
                writer.SetInputData(dataset)
                if writer.Write() != 1:
                    raise RuntimeError(
                        f"Failed to write legacy VTK dataset to {output_path}"
                    )
            else:
                # Fallback for unsupported/non-dataset pipeline outputs.
                self.simple.SaveData(output_path, proxy=source)
        else:
            self.simple.SaveData(output_path, proxy=source)
        return output_path

    def export_active_dataset_for_editing(self):
        """Fetch the active pipeline result as a local VTK dataset for editing."""
        source = self.source
        node = self._get_active_node()
        if source is None or node is None:
            raise RuntimeError("No active pipeline item available for editing")

        from paraview import servermanager

        source.UpdatePipeline()
        dataset = servermanager.Fetch(source)
        if not EditSession.is_supported_dataset(dataset):
            data_type = type(dataset).__name__ if dataset is not None else "Unknown"
            raise TypeError(
                f"Edit mode currently supports only vtkUnstructuredGrid outputs, got {data_type}."
            )
        return {
            "node_id": node["id"],
            "label": node.get("label") or os.path.basename(node.get("filename") or "source"),
            "filename": node.get("filename") or "",
            "dataset": dataset,
        }

    def set_active_node(self, node_id):
        """Make the given pipeline node active."""
        node = self._find_node(node_id)
        if node is None:
            return False

        self.active_node_id = node_id
        self.simple.SetActiveSource(node["source"])
        if self.view is not None:
            self.simple.SetActiveView(self.view)
            self._sync_view_center(node["source"])
        return True

    def set_visibility(self, node_id, visible):
        """Show or hide the display associated with a pipeline node."""
        node = self._find_node(node_id)
        if node is None or node["display"] is None:
            return False

        node["display"].Visibility = 1 if visible else 0
        self.render()
        return True

    def get_visibility(self, node_id):
        """Return the visibility of a pipeline node, or ``None`` if unavailable."""
        node = self._find_node(node_id)
        if node is None or node["display"] is None:
            return None
        return bool(node["display"].Visibility)

    def delete_node(self, node_id):
        """Delete a pipeline node and adjust active selection."""
        node = self._find_node(node_id)
        if node is None:
            return False

        node_ids = {entry["id"] for entry in self._collect_descendants(node_id)}
        node_ids.add(node_id)
        nodes_to_delete = [entry for entry in self.pipeline_nodes if entry["id"] in node_ids]
        for entry in reversed(nodes_to_delete):
            if entry["display"] is not None and self.view is not None:
                self.simple.Hide(entry["source"], self.view)
            self.simple.Delete(entry["source"])

        self.pipeline_nodes = [
            entry for entry in self.pipeline_nodes if entry["id"] not in node_ids
        ]

        if not self.pipeline_nodes:
            self.active_node_id = None
            self.render()
            return True

        next_active = self.pipeline_nodes[-1]["id"]
        self.set_active_node(next_active)
        self.render()
        return True

    def get_available_arrays(self):
        """Return Trame select items for point and cell arrays."""
        source = self.source
        if source is None:
            return [{"text": "Solid Color", "value": ARRAY_SOLID}]

        arrays = [{"text": "Solid Color", "value": ARRAY_SOLID}]
        data_information = source.GetDataInformation()
        arrays.extend(
            self._collect_array_items(data_information.GetPointDataInformation(), "POINTS")
        )
        arrays.extend(
            self._collect_array_items(data_information.GetCellDataInformation(), "CELLS")
        )
        return arrays

    def apply_coloring(self, array_value):
        """Apply solid or scalar coloring to the active representation."""
        display = self.display
        if display is None:
            return

        array_value = self._resolve_available_array_value(array_value)

        if array_value == ARRAY_SOLID or array_value is None:
            self._disable_scalar_coloring(display)
            self.render()
            return

        if array_value.startswith(POINT_PREFIX):
            name = array_value[len(POINT_PREFIX) :]
            association = "POINTS"
        elif array_value.startswith(CELL_PREFIX):
            name = array_value[len(CELL_PREFIX) :]
            association = "CELLS"
        else:
            raise ValueError(f"Unsupported array value for ParaView backend: {array_value}")

        self.simple.ColorBy(display, (association, name))
        display.RescaleTransferFunctionToDataRange(True, False)
        display.SetScalarBarVisibility(self.view, True)
        self.render()

    def _disable_scalar_coloring(self, display, *, hide_unused_scalar_bars=True):
        """Best-effort disable scalar coloring across ParaView version differences."""
        try:
            self.simple.ColorBy(display, None)
        except Exception:
            if hasattr(display, "ColorArrayName"):
                try:
                    display.ColorArrayName = [None, ""]
                except Exception:
                    pass
            if hasattr(display, "LookupTable"):
                try:
                    display.LookupTable = None
                except Exception:
                    pass
            if hasattr(display, "SetScalarBarVisibility"):
                try:
                    display.SetScalarBarVisibility(self.view, False)
                except Exception:
                    pass

        if hide_unused_scalar_bars:
            try:
                self.simple.HideUnusedScalarBars(self.view)
            except Exception:
                pass

    def apply_representation(self, representation):
        """Update the representation used by the active display."""
        display = self.display
        if display is None:
            return

        display.SetRepresentationType(self._normalize_representation(representation))
        self.render()

    def reset_camera(self):
        """Reset camera and render the active view."""
        if self.view is None:
            return

        if self.source is not None:
            self._sync_view_center(self.source)
        self.view.ResetCamera()
        self.render()

    def reset_view(self):
        """Restore a canonical XYZ view and fit the active dataset."""
        if self.view is None:
            return

        source = self.source
        if source is None:
            return

        data_information = source.GetDataInformation()
        bounds = data_information.GetBounds() if data_information is not None else None
        if not bounds:
            self.reset_camera()
            return

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

        self.view.CameraFocalPoint = center
        self.view.CameraPosition = (center[0], center[1], center[2] + distance)
        self.view.CameraViewUp = (0.0, 1.0, 0.0)
        self.view.CenterOfRotation = center
        self.view.ResetCamera()
        self.render()

    def render(self):
        """Trigger a ParaView render."""
        if self.view is not None:
            self.simple.Render(self.view)

    def clear_edit_selection_overlay(self):
        """Remove the transient edit-selection overlay from the view."""
        if self._edit_selection_display is not None:
            try:
                self.simple.Hide(self._edit_selection_overlay, self.view)
            except Exception:
                pass
            self._edit_selection_display = None

        if self._edit_selection_overlay is not None:
            try:
                self.simple.Delete(self._edit_selection_overlay)
            except Exception:
                pass
            self._edit_selection_overlay = None

    def clear_active_selection(self):
        """Clear any ParaView-side selection state on the active source."""
        source = self.source
        if source is None:
            return
        self._clear_selection_state(source)

    def _clear_selection_state(self, source=None):
        """Clear ParaView selection state globally and for a specific source."""
        try:
            self.simple.ClearSelection(source)
        except Exception:
            pass
        try:
            self.simple.ClearSelection()
        except Exception:
            pass

    def set_interactor_rotation(self, enabled):
        """Enable or disable grid manipulation on the ParaView server-side view."""
        if self.view is None:
            return

        # Attempt to use modern ParaView 'Interactions' property if available
        if hasattr(self.view, "Interactions"):
            try:
                current = list(self.view.Interactions)
                if enabled:
                    current[0] = "Rotate"
                    current[1] = "Pan"
                    current[2] = "Zoom"
                else:
                    # Disable common interactions
                    current[0] = "None"
                    current[1] = "None"
                    current[2] = "None"
                self.view.Interactions = current
                return
            except Exception:
                pass

        # Fallback for ParaView versions that use Camera3DManipulators / Camera2DManipulators
        if hasattr(self.view, "Camera3DManipulators"):
            try:
                m3d = list(self.view.Camera3DManipulators)
                if enabled:
                    # Restore standard defaults if they appear disabled
                    if m3d[0] == "None": m3d[0] = "Rotate"
                    if m3d[1] == "None": m3d[1] = "Pan"
                    if m3d[2] == "None": m3d[2] = "Zoom"
                else:
                    # Disable everything to prevent accidental rotation/pan during picking
                    m3d = ["None"] * 9
                self.view.Camera3DManipulators = m3d
            except Exception:
                pass

        if hasattr(self.view, "Camera2DManipulators"):
            try:
                m2d = list(self.view.Camera2DManipulators)
                if enabled:
                    if m2d[0] == "None": m2d[0] = "Pan"
                else:
                    m2d = ["None"] * 9
                self.view.Camera2DManipulators = m2d
            except Exception:
                pass

    def update_edit_selection_overlay(self, dataset):
        """Show the selected edit-session cells as a transient ParaView overlay."""
        if self.view is None:
            return

        source = self.source

        if dataset is None or dataset.GetNumberOfCells() == 0:
            self.clear_edit_selection_overlay()
            self.render()
            return

        # Recreate the transient overlay on each update to avoid stale proxy state.
        self.clear_edit_selection_overlay()
        overlay = self.simple.TrivialProducer(registrationName="__edit_selection__")
        overlay.GetClientSideObject().SetOutput(dataset)
        overlay.UpdatePipeline()
        display = self.simple.Show(overlay, self.view)
        # Overlay producers may not expose a stable LUT; skip scalar-bar cleanup to avoid warnings.
        self._disable_scalar_coloring(display, hide_unused_scalar_bars=False)
        display.SetRepresentationType("Surface With Edges")
        display.DiffuseColor = [1.0, 0.92, 0.25]  # Bright Gold
        display.AmbientColor = [1.0, 0.92, 0.25]
        display.EdgeColor = [0.0, 0.0, 0.0]       # Black edges for contrast
        display.Opacity = 1.0
        if hasattr(display, "Pickable"):
            display.Pickable = 0
        pickable_property = display.GetProperty("Pickable")
        if pickable_property is not None and hasattr(pickable_property, "SetData"):
            pickable_property.SetData(0)
        if hasattr(display, "LineWidth"):
            display.LineWidth = 4.0
        if hasattr(display, "PointSize"):
            display.PointSize = 10.0

        # Ensure it's always on top if possible (Polygon Offset)
        if hasattr(display, "RelativeCoincidentTopologyPolygonOffsetParameters"):
            display.RelativeCoincidentTopologyPolygonOffsetParameters = [-2.0, -2.0]

        self._edit_selection_overlay = overlay
        self._edit_selection_display = display

        if source is not None:
            self.simple.SetActiveSource(source)

        self.render()

    def pick_visible_cell_ids(self, x, y, radius=1):
        """Return selected visible cell ids around a display-space click."""
        source = self.source
        if self.view is None or source is None:
            return []

        try:
            x = int(round(float(x)))
            y = int(round(float(y)))
        except (TypeError, ValueError):
            return []

        candidates = self._candidate_pick_positions(x, y)
        self.clear_edit_selection_overlay()
        self.simple.SetActiveView(self.view)
        self.simple.SetActiveSource(source)

        picked_result = []
        for px, py in candidates:
            self._clear_selection_state(source)
            rect = [px - radius, py - radius, px + radius, py + radius]
            self.simple.SelectSurfaceCells(Rectangle=rect, View=self.view, Modifier=None)
            picked_result = self._fetch_selected_original_cell_ids(source)
            picked_result = self._filter_visible_cell_ids_by_depth(source, picked_result)
            if picked_result:
                break

        # Always clear and RENDER to hide the native ParaView purple selection
        self._clear_selection_state(source)
        self.render()
        return picked_result

    def pick_visible_cell_ids_in_rect(self, x0, y0, x1, y1, behavior="touch"):
        """Return selected visible cell ids inside a display-space rectangle."""
        source = self.source
        if self.view is None or source is None:
            return []

        try:
            x0 = int(round(float(x0)))
            y0 = int(round(float(y0)))
            x1 = int(round(float(x1)))
            y1 = int(round(float(y1)))
        except (TypeError, ValueError):
            return []

        # No Y-inversion here as coordinates from VtkRemoteLocalView are already PV-compatible
        rect = [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
        self.clear_edit_selection_overlay()
        self.simple.SetActiveView(self.view)
        self.simple.SetActiveSource(source)
        self._clear_selection_state(source)
        self.simple.SelectSurfaceCells(Rectangle=rect, View=self.view, Modifier=None)
        picked = self._fetch_selected_original_cell_ids(source)
        picked = self._filter_visible_cell_ids_by_depth(source, picked)
        self._clear_selection_state(source)
        self.render()
        if not picked or behavior != "inside":
            return picked
        return self._filter_cell_ids_inside_rect(source, picked, rect)

    def pick_visible_point_ids(self, x, y, radius=1):
        """Return selected visible point ids around a display-space click."""
        source = self.source
        if self.view is None or source is None:
            return []
        try:
            x = int(round(float(x)))
            y = int(round(float(y)))
        except (TypeError, ValueError):
            return []

        candidates = self._candidate_pick_positions(x, y)
        self.clear_edit_selection_overlay()
        self.simple.SetActiveView(self.view)
        self.simple.SetActiveSource(source)
        picked_result = []
        for px, py in candidates:
            self._clear_selection_state(source)
            rect = [px - radius, py - radius, px + radius, py + radius]
            self.simple.SelectSurfacePoints(Rectangle=rect, View=self.view, Modifier=None)
            picked_result = self._fetch_selected_original_point_ids(source)
            if picked_result:
                break
        self._clear_selection_state(source)
        self.render()
        return picked_result

    def pick_visible_point_ids_in_rect(self, x0, y0, x1, y1, behavior="touch"):
        """Return selected visible point ids inside a display-space rectangle."""
        source = self.source
        if self.view is None or source is None:
            return []
        try:
            x0 = int(round(float(x0)))
            y0 = int(round(float(y0)))
            x1 = int(round(float(x1)))
            y1 = int(round(float(y1)))
        except (TypeError, ValueError):
            return []

        rect = [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
        self.clear_edit_selection_overlay()
        self.simple.SetActiveView(self.view)
        self.simple.SetActiveSource(source)
        self._clear_selection_state(source)
        self.simple.SelectSurfacePoints(Rectangle=rect, View=self.view, Modifier=None)
        picked = self._fetch_selected_original_point_ids(source)
        self._clear_selection_state(source)
        self.render()
        return picked

    def pick_visible_surface_keys(self, x, y, radius=2):
        """Return boundary face/edge keys touched by a display-space click."""
        try:
            x = int(round(float(x)))
            y = int(round(float(y)))
            radius = int(round(float(radius)))
        except (TypeError, ValueError):
            return []

        rect = [x - radius, y - radius, x + radius, y + radius]
        return self._pick_surface_keys_in_rect(rect, behavior="touch")

    def pick_visible_surface_keys_in_rect(self, x0, y0, x1, y1, behavior="touch"):
        """Return boundary face/edge keys touched by a display-space rectangle."""
        try:
            x0 = int(round(float(x0)))
            y0 = int(round(float(y0)))
            x1 = int(round(float(x1)))
            y1 = int(round(float(y1)))
        except (TypeError, ValueError):
            return []

        rect = [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
        return self._pick_surface_keys_in_rect(rect, behavior=behavior)

    def _filter_cell_ids_inside_rect(self, source, cell_ids, rect):
        """Return only cells whose projected vertices are fully inside the display rect."""
        try:
            dataset = self.servermanager.Fetch(source)
        except Exception:
            return cell_ids

        if dataset is None or self.view is None:
            return cell_ids

        client_view = self.view.GetClientSideObject()
        renderer = client_view.GetRenderer() if client_view is not None else None
        if renderer is None:
            return cell_ids

        xmin, ymin, xmax, ymax = rect
        selected = []
        for cell_id in cell_ids:
            if cell_id < 0 or cell_id >= dataset.GetNumberOfCells():
                continue
            cell = dataset.GetCell(int(cell_id))
            if cell is None:
                continue

            inside = True
            for point_idx in range(cell.GetNumberOfPoints()):
                point = dataset.GetPoint(cell.GetPointId(point_idx))
                renderer.SetWorldPoint(point[0], point[1], point[2], 1.0)
                renderer.WorldToDisplay()
                dx, dy, dz = renderer.GetDisplayPoint()
                if not (isfinite(dx) and isfinite(dy) and isfinite(dz)):
                    inside = False
                    break
                if dx < xmin or dx > xmax or dy < ymin or dy > ymax:
                    inside = False
                    break

            if inside:
                selected.append(int(cell_id))

        return selected

    def _pick_surface_keys_in_rect(self, rect, behavior="touch"):
        """Return boundary keys whose projected geometry intersects/is inside rect."""
        source = self.source
        if self.view is None or source is None:
            return []

        self.clear_edit_selection_overlay()

        # Fast path: use native ParaView/VTK surface selection on an extracted
        # boundary-surface representation and map selected cells back to source keys.
        native_keys = self._pick_surface_keys_native(rect, behavior=behavior)
        if native_keys is not None:
            return native_keys

        try:
            dataset = self.servermanager.Fetch(source)
        except Exception:
            return []

        if dataset is None:
            return []

        client_view = self.view.GetClientSideObject()
        renderer = client_view.GetRenderer() if client_view is not None else None
        if renderer is None:
            return []

        boundary = self._boundary_codim_elements(dataset)
        if not boundary:
            return []

        inside_only = behavior == "inside"
        picked = []
        for key, element in boundary.items():
            if not self._surface_element_is_visible(dataset, element["point_ids"], renderer):
                continue
            projected = self._project_points_to_display(dataset, element["point_ids"], renderer)
            if not projected:
                continue
            if inside_only:
                if all(self._point_in_rect(point, rect) for point in projected):
                    picked.append(key)
            else:
                if self._polyline_intersects_rect(projected, rect):
                    picked.append(key)
        return picked

    def _pick_surface_keys_native(self, rect, behavior="touch"):
        """Native ParaView selection path for visible boundary faces (3D)."""
        source = self.source
        if self.view is None or source is None:
            return None

        try:
            dataset = self.servermanager.Fetch(source)
        except Exception:
            return None
        if dataset is None:
            return None
        if not hasattr(dataset, "GetNumberOfCells") or not hasattr(dataset, "GetCell"):
            return None

        top_dim = max(
            (dataset.GetCell(cell_id).GetCellDimension() for cell_id in range(dataset.GetNumberOfCells())),
            default=0,
        )
        # Keep old custom path for 2D/1D where ExtractSurface does not target boundary edges.
        if top_dim != 3:
            return None

        # For "inside" behavior, use native touch selection first and refine with geometric check.
        inside_only = behavior == "inside"
        temp_source = None
        temp_display = None
        extract = None
        selected_dataset = None
        original_source = source
        original_display = self.display
        original_visibility = (
            int(original_display.Visibility)
            if original_display is not None and hasattr(original_display, "Visibility")
            else None
        )

        try:
            self.simple.SetActiveView(self.view)
            self.simple.SetActiveSource(source)
            self._clear_selection_state(source)

            temp_source = self.simple.ExtractSurface(Input=source)
            for prop_name, prop_value in (
                ("PassThroughPointIds", 1),
                ("PassThroughCellIds", 1),
                ("PassThroughPointIdsArrayName", "vtkOriginalPointIds"),
                ("PassThroughCellIdsArrayName", "vtkOriginalCellIds"),
            ):
                if hasattr(temp_source, prop_name):
                    try:
                        setattr(temp_source, prop_name, prop_value)
                    except Exception:
                        pass
            temp_source.UpdatePipeline()

            temp_display = self.simple.Show(temp_source, self.view)
            # Keep the temporary selection helper uncolored to avoid LUT lookups/warnings.
            try:
                self._disable_scalar_coloring(
                    temp_display, hide_unused_scalar_bars=False
                )
            except Exception:
                pass
            if original_display is not None and original_visibility is not None:
                original_display.Visibility = 0

            self.simple.SetActiveSource(temp_source)
            self._clear_selection_state(temp_source)
            self.simple.SelectSurfaceCells(Rectangle=rect, View=self.view, Modifier=None)

            extract = self.simple.ExtractSelection(Input=temp_source)
            extract.UpdatePipeline()
            selected_dataset = self.servermanager.Fetch(extract)
            keys = self._surface_keys_from_selected_dataset(
                selected_dataset, source_dataset=dataset
            )
            if keys is None:
                return None

            if inside_only and keys:
                # Refine to inside-only using existing projected containment on this subset.
                client_view = self.view.GetClientSideObject()
                renderer = client_view.GetRenderer() if client_view is not None else None
                if renderer is not None:
                    inside_keys = []
                    for key in keys:
                        projected = self._project_points_to_display(dataset, key, renderer)
                        if projected and all(self._point_in_rect(point, rect) for point in projected):
                            inside_keys.append(key)
                    keys = inside_keys
            return keys
        except Exception:
            return None
        finally:
            try:
                if original_display is not None and original_visibility is not None:
                    original_display.Visibility = original_visibility
            except Exception:
                pass
            try:
                self.simple.SetActiveSource(original_source)
            except Exception:
                pass
            try:
                if temp_display is not None and temp_source is not None:
                    self.simple.Hide(temp_source, self.view)
            except Exception:
                pass
            try:
                if extract is not None:
                    self.simple.Delete(extract)
            except Exception:
                pass
            try:
                if temp_source is not None:
                    self.simple.Delete(temp_source)
            except Exception:
                pass
            try:
                self.render()
            except Exception:
                pass

    @staticmethod
    def _surface_keys_from_selected_dataset(selected_dataset, source_dataset=None):
        """Map selected ExtractSurface cells back to original source point-id keys."""
        if selected_dataset is None or selected_dataset.GetNumberOfCells() <= 0:
            return []

        point_data = selected_dataset.GetPointData()
        original_point_array = None
        for name in ("vtkOriginalPointIds", "OriginalPointIds", "vtkOriginalPointId", "vtkOriginalIds"):
            array = point_data.GetArray(name) if point_data is not None else None
            if array is not None:
                original_point_array = array
                break

        coordinate_to_source_point_id = None
        if original_point_array is None:
            if source_dataset is None or not hasattr(source_dataset, "GetNumberOfPoints"):
                return None
            coordinate_to_source_point_id = {}
            for source_point_id in range(source_dataset.GetNumberOfPoints()):
                point = source_dataset.GetPoint(source_point_id)
                if point is None:
                    continue
                key = (
                    round(float(point[0]), 12),
                    round(float(point[1]), 12),
                    round(float(point[2]), 12),
                )
                coordinate_to_source_point_id[key] = int(source_point_id)

        keys = []
        for cell_id in range(selected_dataset.GetNumberOfCells()):
            cell = selected_dataset.GetCell(cell_id)
            if cell is None or cell.GetNumberOfPoints() <= 0:
                continue
            try:
                if original_point_array is not None:
                    key = tuple(
                        sorted(
                            int(original_point_array.GetTuple1(cell.GetPointId(point_idx)))
                            for point_idx in range(cell.GetNumberOfPoints())
                        )
                    )
                else:
                    mapped = []
                    for point_idx in range(cell.GetNumberOfPoints()):
                        point = selected_dataset.GetPoint(cell.GetPointId(point_idx))
                        if point is None:
                            mapped = []
                            break
                        coord_key = (
                            round(float(point[0]), 12),
                            round(float(point[1]), 12),
                            round(float(point[2]), 12),
                        )
                        point_id = coordinate_to_source_point_id.get(coord_key)
                        if point_id is None:
                            mapped = []
                            break
                        mapped.append(int(point_id))
                    key = tuple(sorted(mapped))
            except Exception:
                continue
            if key:
                keys.append(key)

        # Preserve deterministic order while deduplicating.
        seen = set()
        deduped = []
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return deduped

    @staticmethod
    def _boundary_codim_elements(dataset):
        """Return boundary codimension-one entities keyed by sorted point ids."""
        cell_count = dataset.GetNumberOfCells()
        top_dim = max(
            (dataset.GetCell(cell_id).GetCellDimension() for cell_id in range(cell_count)),
            default=0,
        )
        if top_dim < 2:
            return {}

        counts = {}
        metadata = {}
        for cell_id in range(cell_count):
            cell = dataset.GetCell(cell_id)
            if cell.GetCellDimension() != top_dim:
                continue

            if top_dim == 3:
                subcell_count = cell.GetNumberOfFaces()
                getter = cell.GetFace
            else:
                subcell_count = cell.GetNumberOfEdges()
                getter = cell.GetEdge

            for subcell_id in range(subcell_count):
                subcell = getter(subcell_id)
                ordered_ids = tuple(
                    int(subcell.GetPointId(point_id))
                    for point_id in range(subcell.GetNumberOfPoints())
                )
                key = tuple(sorted(ordered_ids))
                counts[key] = counts.get(key, 0) + 1
                if key not in metadata:
                    metadata[key] = {"point_ids": ordered_ids}

        return {
            key: metadata[key]
            for key, count in counts.items()
            if count == 1
        }

    @staticmethod
    def _project_points_to_display(dataset, point_ids, renderer):
        projected = []
        for point_id in point_ids:
            point = dataset.GetPoint(int(point_id))
            renderer.SetWorldPoint(point[0], point[1], point[2], 1.0)
            renderer.WorldToDisplay()
            dx, dy, dz = renderer.GetDisplayPoint()
            if not (isfinite(dx) and isfinite(dy) and isfinite(dz)):
                return []
            projected.append((float(dx), float(dy)))
        return projected

    def _surface_element_is_visible(self, dataset, point_ids, renderer):
        """Return True when the element centroid is visible in the current depth buffer."""
        if dataset is None or renderer is None or not point_ids:
            return False

        points = []
        for point_id in point_ids:
            try:
                points.append(dataset.GetPoint(int(point_id)))
            except Exception:
                return False
        if not points:
            return False

        count = float(len(points))
        centroid = (
            sum(point[0] for point in points) / count,
            sum(point[1] for point in points) / count,
            sum(point[2] for point in points) / count,
        )
        projected = self._project_world_point_to_display(renderer, centroid)
        if projected is None:
            return False
        return self._is_display_depth_visible(renderer, projected[0], projected[1], projected[2])

    def _filter_visible_cell_ids_by_depth(self, source, cell_ids):
        """Keep only cell ids with centroid visible from the current camera."""
        if not cell_ids:
            return []

        renderer = self._get_renderer()
        if renderer is None:
            return list(cell_ids)

        try:
            dataset = self.servermanager.Fetch(source)
        except Exception:
            return list(cell_ids)
        if dataset is None:
            return list(cell_ids)

        visible_ids = []
        for cell_id in cell_ids:
            try:
                cid = int(cell_id)
            except (TypeError, ValueError):
                continue
            if cid < 0 or cid >= dataset.GetNumberOfCells():
                continue

            cell = dataset.GetCell(cid)
            if cell is None or cell.GetNumberOfPoints() <= 0:
                continue

            points = []
            for point_idx in range(cell.GetNumberOfPoints()):
                points.append(dataset.GetPoint(cell.GetPointId(point_idx)))
            count = float(len(points))
            centroid = (
                sum(point[0] for point in points) / count,
                sum(point[1] for point in points) / count,
                sum(point[2] for point in points) / count,
            )
            projected = self._project_world_point_to_display(renderer, centroid)
            if projected is None:
                continue
            if self._is_display_depth_visible(renderer, projected[0], projected[1], projected[2]):
                visible_ids.append(cid)

        return visible_ids

    def _get_renderer(self):
        if self.view is None:
            return None
        client_view = self.view.GetClientSideObject()
        if client_view is None:
            return None
        return client_view.GetRenderer()

    @staticmethod
    def _project_world_point_to_display(renderer, point):
        """Project one 3D world point to display coords and return (x, y, z)."""
        try:
            renderer.SetWorldPoint(float(point[0]), float(point[1]), float(point[2]), 1.0)
            renderer.WorldToDisplay()
            dx, dy, dz = renderer.GetDisplayPoint()
        except Exception:
            return None
        if not (isfinite(dx) and isfinite(dy) and isfinite(dz)):
            return None
        return (float(dx), float(dy), float(dz))

    @staticmethod
    def _is_display_depth_visible(renderer, x, y, z, tolerance=1e-4):
        """Return True when display depth ``z`` is on/near the visible z-buffer value."""
        if renderer is None:
            return True
        try:
            buffer_z = float(renderer.GetZ(int(round(x)), int(round(y))))
        except Exception:
            return True
        if not isfinite(buffer_z):
            return True
        # Smaller z is closer to camera in display coordinates.
        return float(z) <= buffer_z + float(tolerance)

    @staticmethod
    def _point_in_rect(point, rect):
        x, y = point
        xmin, ymin, xmax, ymax = rect
        return xmin <= x <= xmax and ymin <= y <= ymax

    def _polyline_intersects_rect(self, points, rect):
        """Return True if polygon/polyline projected points intersect a screen rect."""
        xmin, ymin, xmax, ymax = rect
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        if max(xs) < xmin or min(xs) > xmax or max(ys) < ymin or min(ys) > ymax:
            return False

        if any(self._point_in_rect(point, rect) for point in points):
            return True

        rect_corners = [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)]
        if len(points) >= 3 and any(self._point_in_polygon(corner, points) for corner in rect_corners):
            return True

        edges = list(zip(points, points[1:]))
        if len(points) >= 3:
            edges.append((points[-1], points[0]))

        rect_edges = [
            ((xmin, ymin), (xmax, ymin)),
            ((xmax, ymin), (xmax, ymax)),
            ((xmax, ymax), (xmin, ymax)),
            ((xmin, ymax), (xmin, ymin)),
        ]
        for segment in edges:
            if any(self._segments_intersect(segment[0], segment[1], edge[0], edge[1]) for edge in rect_edges):
                return True

        return False

    @staticmethod
    def _point_in_polygon(point, polygon):
        """Ray-casting point-in-polygon test in 2D."""
        x, y = point
        inside = False
        j = len(polygon) - 1
        for i in range(len(polygon)):
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            intersects = ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            )
            if intersects:
                inside = not inside
            j = i
        return inside

    @staticmethod
    def _segments_intersect(p1, p2, q1, q2):
        """Return True if 2D segments p1-p2 and q1-q2 intersect."""

        def orientation(a, b, c):
            value = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])
            if abs(value) < 1e-9:
                return 0
            return 1 if value > 0 else 2

        def on_segment(a, b, c):
            return (
                min(a[0], c[0]) - 1e-9 <= b[0] <= max(a[0], c[0]) + 1e-9
                and min(a[1], c[1]) - 1e-9 <= b[1] <= max(a[1], c[1]) + 1e-9
            )

        o1 = orientation(p1, p2, q1)
        o2 = orientation(p1, p2, q2)
        o3 = orientation(q1, q2, p1)
        o4 = orientation(q1, q2, p2)

        if o1 != o2 and o3 != o4:
            return True
        if o1 == 0 and on_segment(p1, q1, p2):
            return True
        if o2 == 0 and on_segment(p1, q2, p2):
            return True
        if o3 == 0 and on_segment(q1, p1, q2):
            return True
        if o4 == 0 and on_segment(q1, p2, q2):
            return True
        return False

    def get_pick_debug_info(self, x, y, radius=4):
        """Return debug information for the current click-to-pick attempt."""
        width, height = self.view.ViewSize if self.view is not None else (0, 0)
        try:
            px = int(round(float(x)))
            py = int(round(float(y)))
        except (TypeError, ValueError):
            return {
                "raw_pointer": {"x": x, "y": y},
                "view_size": {"width": int(width or 0), "height": int(height or 0)},
                "pick_radius": int(radius),
                "candidate_positions": [],
            }

        candidates = self._candidate_pick_positions(px, py)
        return {
            "raw_pointer": {"x": px, "y": py},
            "view_size": {"width": int(width or 0), "height": int(height or 0)},
            "pick_radius": int(radius),
            "candidate_positions": [
                {"x": cx, "y": cy, "rect": [cx - radius, cy - radius, cx + radius, cy + radius]}
                for cx, cy in candidates
            ],
        }

    def _candidate_pick_positions(self, x, y):
        """Return plausible pixel coordinates for the current event convention."""
        width, height = self.view.ViewSize if self.view is not None else (0, 0)
        width = int(width or 0)
        height = int(height or 0)

        candidates = []

        def add(px, py):
            try:
                px = int(round(float(px)))
                py = int(round(float(py)))
            except (TypeError, ValueError):
                return
            key = (px, py)
            if key not in candidates:
                candidates.append(key)

        # In modern Trame/ParaView, the event Y is often already inverted (0=bottom).
        # We try the raw coordinate first.
        add(x, y)
        
        # Fallback to inverted if raw fails
        if height > 0:
            add(x, height - y)

        if width > 0 and height > 0 and 0 <= x <= 1 and 0 <= y <= 1:
            # Normalized coordinates fallback
            add(x * width, y * height)
            add(x * width, (1 - y) * height)

        return candidates

    def _fetch_selected_original_cell_ids(self, source):
        """Extract selected original cell ids from the source selection."""
        try:
            extract = self.simple.ExtractSelection(Input=source)
            extract.UpdatePipeline()
            dataset = self.servermanager.Fetch(extract)
        except Exception:
            return []

        if dataset is None:
            return []

        cell_data = dataset.GetCellData()
        candidate_names = [
            "vtkOriginalCellIds",
            "originalCellIds",
            "OriginalCellIds",
        ]

        selected_ids = []
        for name in candidate_names:
            array = cell_data.GetArray(name)
            if array is not None:
                selected_ids = [
                    int(array.GetTuple1(i)) for i in range(array.GetNumberOfTuples())
                ]
                break

        try:
            self.simple.Delete(extract)
        except Exception:
            pass

        return selected_ids

    def _fetch_selected_original_point_ids(self, source):
        """Extract selected original point ids from the source selection."""
        try:
            extract = self.simple.ExtractSelection(Input=source)
            extract.UpdatePipeline()
            dataset = self.servermanager.Fetch(extract)
        except Exception:
            return []

        if dataset is None:
            return []

        point_data = dataset.GetPointData()
        candidate_names = [
            "vtkOriginalPointIds",
            "originalPointIds",
            "OriginalPointIds",
        ]

        selected_ids = []
        for name in candidate_names:
            array = point_data.GetArray(name)
            if array is not None:
                selected_ids = [
                    int(array.GetTuple1(i)) for i in range(array.GetNumberOfTuples())
                ]
                break

        try:
            self.simple.Delete(extract)
        except Exception:
            pass

        return selected_ids

    def get_ui_state(self):
        """Return lightweight UI metadata for the current ParaView selection."""
        source = self.source
        if source is None:
            return {
                "pipeline_items": [],
                "active_pipeline_item": None,
                "active_source_label": "",
                "active_source_type": "",
                "active_source_kind": "Reader Type",
                "active_parent_label": "",
                "source_path": "",
                "point_arrays": [],
                "cell_arrays": [],
                "data_stats": [],
                "source_properties": [],
                "display_properties": [],
                "show_calculator_help": False,
                "calculator_attribute_type": "",
                "calculator_input_variables": [],
                "calculator_coordinate_variables": ["coordsX", "coordsY", "coordsZ"],
                "active_visibility": True,
                "selected_array": ARRAY_SOLID,
                "representation": "Surface with Edges",
            }

        data_information = source.GetDataInformation()
        point_items = self._collect_array_items(
            data_information.GetPointDataInformation(), "POINTS"
        )
        cell_items = self._collect_array_items(
            data_information.GetCellDataInformation(), "CELLS"
        )

        active_node = self._get_active_node()
        filename = active_node["filename"]
        relative_filename = self._relative_path(filename)
        active_label = active_node.get("label") or os.path.basename(
            relative_filename or filename or "source"
        )
        xml_name = ""
        if hasattr(source, "SMProxy") and source.SMProxy is not None:
            xml_name = source.SMProxy.GetXMLName() or ""

        stats = [
            {"label": "Points", "value": str(data_information.GetNumberOfPoints())},
            {"label": "Cells", "value": str(data_information.GetNumberOfCells())},
            {"label": "Point Arrays", "value": str(len(point_items))},
            {"label": "Cell Arrays", "value": str(len(cell_items))},
        ]

        return {
            "pipeline_items": [
                {
                    "text": node.get("label") or os.path.basename(node.get("filename") or "source"),
                    "value": node["id"],
                    "node_icon": self._pipeline_icon(node),
                    "visibility_icon": (
                        "mdi-eye-outline"
                        if node["display"] is not None and node["display"].Visibility
                        else "mdi-eye-off-outline"
                    ),
                    "depth": self._pipeline_depth(node),
                }
                for node in self.pipeline_nodes
            ],
            "active_pipeline_item": self.active_node_id,
            "active_source_label": active_label,
            "active_source_type": xml_name or source.__class__.__name__,
            "active_source_kind": self._active_kind_label(),
            "active_parent_label": self._active_parent_label(),
            "source_path": relative_filename or "",
            "point_arrays": point_items,
            "cell_arrays": cell_items,
            "data_stats": stats,
            "source_properties": self.property_inspector.tag_property_scope(
                self.property_inspector.collect_proxy_properties(source), "source"
            ),
            "display_properties": self.property_inspector.tag_property_scope(
                self.property_inspector.collect_proxy_properties(
                    self.display, scope="display"
                ),
                "display",
            ),
            "show_calculator_help": self._is_active_calculator(),
            "calculator_attribute_type": self._calculator_attribute_type(),
            "calculator_input_variables": self._calculator_input_variables(),
            "calculator_coordinate_variables": ["coordsX", "coordsY", "coordsZ"],
            "active_visibility": bool(self.display.Visibility) if self.display else True,
            "selected_array": self._get_selected_array(),
            "representation": self._get_representation(),
        }

    def apply_property_changes(self, source_properties, display_properties):
        """Apply edited property values to the active ParaView source/display proxies."""
        self.property_inspector.apply_proxy_property_changes(
            self.source, source_properties
        )
        self.property_inspector.apply_proxy_property_changes(
            self.display, display_properties
        )

        if self.source is not None:
            self.source.UpdatePipeline()
        self.render()

    def _get_active_node(self):
        """Return the active pipeline node."""
        return self._find_node(self.active_node_id)

    def _active_kind_label(self):
        """Return a UI label describing the active node kind."""
        node = self._get_active_node()
        if node is None:
            return "Reader Type"
        return "Filter Type" if node.get("kind") == "filter" else "Reader Type"

    def _active_parent_label(self):
        """Return the parent pipeline label for the active node when available."""
        node = self._get_active_node()
        if node is None or not node.get("parent_id"):
            return ""
        parent = self._find_node(node["parent_id"])
        if parent is None:
            return ""
        return parent.get("label") or os.path.basename(parent.get("filename") or "source")

    def _is_active_calculator(self):
        """Return True when the active node is a Calculator filter."""
        node = self._get_active_node()
        if node is None:
            return False
        if node.get("filter_key") == "calculator":
            return True
        source = node.get("source")
        if source is None or not hasattr(source, "SMProxy") or source.SMProxy is None:
            return False
        return (source.SMProxy.GetXMLName() or "") == "Calculator"

    def _calculator_attribute_type(self):
        """Return the active Calculator attribute type label."""
        if not self._is_active_calculator() or self.source is None:
            return ""
        prop = self.source.GetProperty("AttributeType")
        if prop is not None and hasattr(prop, "GetData"):
            return prop.GetData() or ""
        return ""

    def _calculator_input_variables(self):
        """Return input-array variable names available to the active Calculator."""
        if not self._is_active_calculator():
            return []

        node = self._get_active_node()
        if node is None:
            return []

        input_node = self._find_node(node.get("parent_id")) if node.get("parent_id") else None
        input_source = input_node["source"] if input_node is not None else self.source
        if input_source is None:
            return []

        data_information = input_source.GetDataInformation()
        if data_information is None:
            return []

        attribute_type = self._calculator_attribute_type()
        array_information = (
            data_information.GetCellDataInformation()
            if attribute_type == "Cell Data"
            else data_information.GetPointDataInformation()
        )
        items = self._collect_array_items(
            array_information,
            "CELLS" if attribute_type == "Cell Data" else "POINTS",
        )
        return [item["text"].rsplit(" ", 1)[0] for item in items]

    def _sync_view_center(self, source):
        """Align the view center of rotation with the active source bounds center."""
        if self.view is None or source is None:
            return

        data_information = source.GetDataInformation()
        if data_information is None:
            return

        bounds = data_information.GetBounds()
        if not bounds or len(bounds) != 6:
            return

        center = [
            0.5 * (bounds[0] + bounds[1]),
            0.5 * (bounds[2] + bounds[3]),
            0.5 * (bounds[4] + bounds[5]),
        ]

        center_property = self.view.GetProperty("CenterOfRotation")
        if center_property is not None and hasattr(center_property, "SetData"):
            center_property.SetData(center)

        focal_property = self.view.GetProperty("CameraFocalPoint")
        if focal_property is not None and hasattr(focal_property, "SetData"):
            focal_property.SetData(center)

    def _find_node(self, node_id):
        """Find a pipeline node by id."""
        for node in self.pipeline_nodes:
            if node["id"] == node_id:
                return node
        return None

    def _collect_descendants(self, node_id):
        """Return all descendants of the provided node id."""
        descendants = []
        direct_children = [
            node for node in self.pipeline_nodes if node.get("parent_id") == node_id
        ]
        for child in direct_children:
            descendants.append(child)
            descendants.extend(self._collect_descendants(child["id"]))
        return descendants

    def _get_selected_array(self):
        """Return the current UI array selector value for the active display."""
        display = self.display
        if display is None:
            return ARRAY_SOLID

        color_array = getattr(display, "ColorArrayName", None)
        if not color_array or len(color_array) < 2 or not color_array[1]:
            return ARRAY_SOLID
        if color_array[0] == "POINTS":
            return f"{POINT_PREFIX}{color_array[1]}"
        if color_array[0] == "CELLS":
            return f"{CELL_PREFIX}{color_array[1]}"
        return ARRAY_SOLID

    def _resolve_available_array_value(self, array_value):
        """Return a valid array selector for the active source, or a safe fallback."""
        source = self.source
        if source is None or not array_value or array_value == ARRAY_SOLID:
            return ARRAY_SOLID

        available_items = self.get_available_arrays()
        available_values = {item["value"] for item in available_items}
        if array_value in available_values:
            return array_value

        if array_value.startswith(POINT_PREFIX):
            name = array_value[len(POINT_PREFIX) :]
        elif array_value.startswith(CELL_PREFIX):
            name = array_value[len(CELL_PREFIX) :]
        else:
            return ARRAY_SOLID

        point_candidate = f"{POINT_PREFIX}{name}"
        cell_candidate = f"{CELL_PREFIX}{name}"
        if point_candidate in available_values:
            return point_candidate
        if cell_candidate in available_values:
            return cell_candidate

        return available_items[1]["value"] if len(available_items) > 1 else ARRAY_SOLID

    def _get_representation(self):
        """Return the current representation label for the active display."""
        display = self.display
        if display is None:
            return "Surface with Edges"
        representation = display.GetProperty("Representation")
        if representation is not None and hasattr(representation, "GetData"):
            representation = representation.GetData()
        reverse = {
            "Surface": "Surface",
            "Surface With Edges": "Surface with Edges",
            "Wireframe": "Wireframe",
            "Points": "Points",
        }
        return reverse.get(representation, "Surface with Edges")

    @staticmethod
    def _node_id(source):
        """Build a stable UI id for a ParaView source proxy."""
        return f"source:{source.GetGlobalIDAsString()}"

    @staticmethod
    def _collect_array_items(data_information, association):
        """Convert ParaView array metadata into Trame select items."""
        if data_information is None:
            return []

        items = []
        for index in range(data_information.GetNumberOfArrays()):
            array_info = data_information.GetArrayInformation(index)
            if array_info is None:
                continue
            name = array_info.GetName()
            if not name:
                continue

            if association == "POINTS":
                items.append({"text": f"{name} (Point)", "value": f"{POINT_PREFIX}{name}"})
            else:
                items.append({"text": f"{name} (Cell)", "value": f"{CELL_PREFIX}{name}"})

        return items

    @staticmethod
    def _normalize_representation(representation):
        """Map UI labels to ParaView representation labels."""
        mapping = {
            "Surface": "Surface",
            "Surface with Edges": "Surface With Edges",
            "Wireframe": "Wireframe",
            "Points": "Points",
        }
        return mapping.get(representation, representation)

    @staticmethod
    def _make_node(
        source,
        display,
        filename,
        kind,
        label,
        parent_id=None,
        filter_key=None,
    ):
        """Build a pipeline node descriptor."""
        return {
            "id": ParaViewBackend._node_id(source),
            "source": source,
            "display": display,
            "filename": filename,
            "kind": kind,
            "label": label,
            "parent_id": parent_id,
            "filter_key": filter_key,
        }

    def _pipeline_label(self, node):
        """Return a readable pipeline label with lightweight hierarchy cues."""
        depth = 0
        parent_id = node.get("parent_id")
        while parent_id:
            parent = self._find_node(parent_id)
            if parent is None:
                break
            depth += 1
            parent_id = parent.get("parent_id")
        prefix = "  " * depth
        return f"{prefix}{node.get('label') or os.path.basename(node.get('filename') or 'source')}"

    def _pipeline_depth(self, node):
        """Return hierarchy depth for a pipeline node."""
        depth = 0
        parent_id = node.get("parent_id")
        while parent_id:
            parent = self._find_node(parent_id)
            if parent is None:
                break
            depth += 1
            parent_id = parent.get("parent_id")
        return depth

    def _pipeline_icon(self, node):
        """Return a kind-aware icon for a pipeline entry."""
        return self.filter_catalog.pipeline_icon(node)

    def _relative_path(self, filename):
        """Return a path relative to the configured data directory when possible."""
        if not filename:
            return ""
        if self.data_directory is None:
            return os.path.basename(filename)
        try:
            common = os.path.commonpath([self.data_directory, os.path.abspath(filename)])
        except ValueError:
            return os.path.basename(filename)
        if common != self.data_directory:
            return os.path.basename(filename)
        return os.path.relpath(filename, self.data_directory)

    def _default_output_extension(self):
        """Return a reasonable file extension for the active dataset type."""
        source = self.source
        if source is None:
            return ".vtk"
        data_information = source.GetDataInformation()
        type_name = (
            data_information.GetDataSetTypeAsString()
            if data_information is not None and hasattr(data_information, "GetDataSetTypeAsString")
            else ""
        )
        mapping = {
            "PolyData": ".vtp",
            "UnstructuredGrid": ".vtu",
            "StructuredGrid": ".vts",
            "RectilinearGrid": ".vtr",
            "ImageData": ".vti",
            "MultiBlockDataSet": ".vtm",
            "PartitionedDataSetCollection": ".vtm",
            "PartitionedDataSet": ".vtm",
        }
        for key, suffix in mapping.items():
            if key in type_name:
                return suffix
        return ".vtk"
