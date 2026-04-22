"""ParaView backend adapter for the Trame visualizer."""

from __future__ import annotations

import importlib.util
import os
from math import isfinite

from constants import ARRAY_SOLID, CELL_PREFIX, MATERIAL_ID_ARRAY, POINT_PREFIX
from edit_session import EditSession
from paraview_filter_catalog import ParaViewFilterCatalog, SUPPORTED_FILTERS
from paraview_property_inspector import ParaViewPropertyInspector


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
            self.simple.ColorBy(display, None)
            self.simple.HideUnusedScalarBars(self.view)
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
        try:
            self.simple.ClearSelection(source)
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
        self.simple.ColorBy(display, None)
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
        self.simple.SetActiveView(self.view)
        self.simple.SetActiveSource(source)

        picked_result = []
        for px, py in candidates:
            self.simple.ClearSelection(source)
            rect = [px - radius, py - radius, px + radius, py + radius]
            self.simple.SelectSurfaceCells(Rectangle=rect, View=self.view, Modifier=None)
            picked_result = self._fetch_selected_original_cell_ids(source)
            if picked_result:
                break

        # Always clear and RENDER to hide the native ParaView purple selection
        self.simple.ClearSelection(source)
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
        self.simple.SetActiveView(self.view)
        self.simple.SetActiveSource(source)
        self.simple.ClearSelection(source)
        self.simple.SelectSurfaceCells(Rectangle=rect, View=self.view, Modifier=None)
        picked = self._fetch_selected_original_cell_ids(source)
        self.simple.ClearSelection(source)
        self.render()
        if not picked or behavior != "inside":
            return picked
        return self._filter_cell_ids_inside_rect(source, picked, rect)

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
