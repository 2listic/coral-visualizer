"""ParaView backend adapter for the Trame visualizer."""

from __future__ import annotations

import importlib.util
import os

from constants import ARRAY_SOLID, CELL_PREFIX, MATERIAL_ID_ARRAY, POINT_PREFIX
from edit_session import EditSession


SUPPORTED_FILTERS = {
    "calculator": {"label": "Calculator", "factory": "Calculator", "icon": "mdi-calculator-variant-outline"},
    "cell_centers": {"label": "Cell Centers", "factory": "CellCenters", "icon": "mdi-crosshairs-gps"},
    "clip": {"label": "Clip", "factory": "Clip", "icon": "mdi-content-cut"},
    "contour": {"label": "Contour", "factory": "Contour", "icon": "mdi-chart-bell-curve"},
    "coordinates": {"label": "Coordinates", "factory": "Coordinates", "icon": "mdi-axis-arrow-info"},
    "glyph": {"label": "Glyph", "factory": "Glyph", "icon": "mdi-vector-point"},
    "reflect": {"label": "Reflect", "factory": "Reflect", "icon": "mdi-reflect-horizontal"},
    "slice": {"label": "Slice", "factory": "Slice", "icon": "mdi-content-cut"},
    "stream_tracer": {
        "label": "Streamline",
        "factory": "StreamTracer",
        "icon": "mdi-chart-bell-curve-cumulative",
    },
    "threshold": {"label": "Threshold", "factory": "Threshold", "icon": "mdi-filter-outline"},
    "transform": {"label": "Transform", "factory": "Transform", "icon": "mdi-axis-arrow"},
    "tube": {"label": "Tube", "factory": "Tube", "icon": "mdi-cylinder"},
    "warp_by_scalar": {
        "label": "Warp by Scalar",
        "factory": "WarpByScalar",
        "icon": "mdi-image-filter-center-focus-strong",
    },
    "warp_by_vector": {
        "label": "Warp by Vector",
        "factory": "WarpByVector",
        "icon": "mdi-axis-arrow",
    },
}

FILTER_DISCOVERY_KEYWORDS = {
    "append",
    "calculator",
    "cell",
    "clean",
    "clip",
    "connectivity",
    "contour",
    "convert",
    "decimate",
    "extract",
    "glyph",
    "ghost",
    "ids",
    "interpolate",
    "mask",
    "merge",
    "normal",
    "point",
    "probe",
    "reflect",
    "slice",
    "stream",
    "subdivide",
    "threshold",
    "transform",
    "triangulate",
    "tube",
    "warp",
}

FILTER_DISCOVERY_EXCLUDE = {
    "CreateExtractor",
    "CreateXYPointPlotView",
    "FindExtractor",
    "GetExtractors",
    "LoadDistributedPlugin",
    "SaveExtracts",
    "SaveExtractsUsingCatalystOptions",
}

FILTER_DISCOVERY_EXCLUDE_SUBSTRINGS = {
    "amr",
    "block ids",
    "cellgrid",
    "composite",
    "extractor",
    "feature edges region ids",
    "ghost",
    "global ids",
    "global point and cell ids",
    "hierarchical",
    "hypertreegrid",
    "ids",
    "idselection",
    "ioss",
    "molecule",
    "octree",
    "pedigree",
    "process ids",
    "process ids",
    "quadrature",
    "reader",
    "remove ghost",
    "select ",
    "selection",
    "source",
    "statistical model",
    "table",
}

EXPERIMENTAL_FILTER_ICON_RULES = [
    ("clip", "mdi-content-cut"),
    ("slice", "mdi-content-cut"),
    ("contour", "mdi-chart-bell-curve"),
    ("threshold", "mdi-filter-outline"),
    ("calculator", "mdi-calculator-variant-outline"),
    ("transform", "mdi-axis-arrow"),
    ("reflect", "mdi-reflect-horizontal"),
    ("tube", "mdi-cylinder"),
    ("glyph", "mdi-vector-point"),
    ("stream", "mdi-chart-bell-curve-cumulative"),
    ("warp", "mdi-axis-arrow"),
    ("extract", "mdi-select-drag"),
    ("clean", "mdi-broom"),
    ("triangulate", "mdi-triangle-outline"),
    ("connect", "mdi-graph-outline"),
    ("merge", "mdi-source-merge"),
    ("append", "mdi-plus-box-multiple-outline"),
]


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

        self.simple = simple
        self.view = None
        self.pipeline_nodes = []
        self.active_node_id = None
        self.data_directory = os.path.abspath(data_directory) if data_directory else None
        self._filter_counts = {key: 0 for key in SUPPORTED_FILTERS}
        self._show_experimental_filters = show_experimental_filters
        self._experimental_filter_specs = (
            self._discover_experimental_filters() if show_experimental_filters else []
        )

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
        return {
            "supported": [
                {"text": spec["label"], "value": key, "icon": spec["icon"]}
                for key, spec in SUPPORTED_FILTERS.items()
            ],
            "experimental": [
                {
                    "text": spec["label"],
                    "value": spec["value"],
                    "icon": spec["icon"],
                }
                for spec in self._experimental_filter_specs
            ],
        }

    def add_filter(self, filter_key):
        """Create a new filter node from the active pipeline node."""
        node = self._get_active_node()
        if node is None:
            raise RuntimeError("No active source available for filtering")

        spec = SUPPORTED_FILTERS.get(filter_key)
        if spec is None:
            spec = self._experimental_filter_spec(filter_key)
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
            return "output" + self._default_output_extension()
        label = node.get("label") or "output"
        safe_label = "".join(
            char if char.isalnum() or char in {"-", "_"} else "_" for char in label
        ).strip("_")
        if not safe_label:
            safe_label = "output"
        return safe_label + self._default_output_extension()

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

    def _experimental_filter_spec(self, filter_key):
        """Return the discovered experimental filter spec matching the given UI key."""
        for spec in self._experimental_filter_specs:
            if spec["value"] == filter_key:
                return {
                    "label": spec["label"],
                    "factory": spec["factory"],
                    "icon": spec["icon"],
                }
        return None

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

    def render(self):
        """Trigger a ParaView render."""
        if self.view is not None:
            self.simple.Render(self.view)

    def get_ui_state(self):
        """Return lightweight UI metadata for the current ParaView selection."""
        source = self.source
        if source is None:
            return {
                "pipeline_items": [],
                "active_pipeline_item": None,
                "active_source_label": "",
                "active_source_type": "",
                "source_path": "",
                "point_arrays": [],
                "cell_arrays": [],
                "data_stats": [],
                "source_properties": [],
                "display_properties": [],
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
            "source_properties": self._tag_property_scope(
                self._collect_proxy_properties(source), "source"
            ),
            "display_properties": self._tag_property_scope(
                self._collect_proxy_properties(self.display, scope="display"), "display"
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
        self._apply_proxy_property_changes(self.source, source_properties)
        self._apply_proxy_property_changes(self.display, display_properties)

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

    @classmethod
    def _collect_proxy_properties(cls, proxy, scope="source"):
        """Extract user-facing proxy properties from a ParaView proxy."""
        if proxy is None:
            return []

        properties = []
        for name in proxy.ListProperties():
            prop = proxy.GetProperty(name)
            type_name = type(prop).__name__
            sm_property = proxy.SMProxy.GetProperty(name) if proxy.SMProxy is not None else None

            if type_name == "InputProperty":
                continue

            if type_name == "ProxyProperty" and name in {"ClipType", "GlyphType", "SeedType"}:
                properties.extend(
                    cls._collect_proxy_subproperties(
                        proxy, name, type_name, None, sm_property, scope
                    )
                )
                continue

            if sm_property is None:
                continue

            visibility = sm_property.GetPanelVisibility()
            if visibility not in {"default", "advanced"}:
                continue
            if sm_property.GetIsInternal() or sm_property.GetInformationOnly():
                continue

            if scope == "display" and name in {"Representation", "ColorArrayName"}:
                continue

            try:
                value = prop.GetData()
            except Exception:
                value = None

            available = cls._property_options(proxy, name, type_name, value)
            effective_type = cls._effective_property_type(type_name, sm_property)
            properties.append(
                {
                    "scope": "unknown",
                    "name": name,
                    "label": cls._property_label(name),
                    "type": effective_type,
                    "visibility": visibility,
                    "value": cls._format_property_value(value),
                    "pending_value": cls._normalize_property_value(effective_type, value),
                    "options": available,
                    "editable": cls._is_editable_property(effective_type, value, available),
                    "priority": cls._property_priority(name, scope),
                }
            )

        properties = sorted(properties, key=lambda item: (item["priority"], item["label"]))
        if scope == "display":
            properties = [
                item
                for item in properties
                if item["name"]
                in {
                    "Opacity",
                    "Interpolation",
                    "MapScalars",
                    "InterpolateScalarsBeforeMapping",
                    "PointSize",
                    "LineWidth",
                }
            ]
        return properties

    @classmethod
    def _collect_proxy_subproperties(
        cls, proxy, name, type_name, value, sm_property, scope
    ):
        """Expose proxy-switch properties and selected sub-proxy fields."""
        available = list(getattr(proxy.GetProperty(name), "Available", []) or [])
        items = []
        parent_visibility = (
            sm_property.GetPanelVisibility()
            if sm_property is not None and sm_property.GetPanelVisibility() in {"default", "advanced"}
            else "default"
        )
        current_proxy_name = ""
        if value is None and hasattr(proxy, name):
            value = getattr(proxy, name)
        if value is not None and hasattr(value, "SMProxy") and value.SMProxy is not None:
            current_proxy_name = value.SMProxy.GetXMLName() or ""

        if available:
            items.append(
                {
                    "scope": "unknown",
                    "name": name,
                    "label": cls._property_label(name),
                    "type": "ProxySelectionProperty",
                    "visibility": parent_visibility,
                    "value": current_proxy_name,
                    "pending_value": current_proxy_name,
                    "options": available,
                    "editable": True,
                    "priority": cls._property_priority(name, scope),
                }
            )

        if value is None or not hasattr(value, "ListProperties"):
            return items

        prefix_label = cls._property_label(name)
        for child_name in value.ListProperties():
            child_sm_property = value.SMProxy.GetProperty(child_name)
            if child_sm_property is None:
                continue
            visibility = child_sm_property.GetPanelVisibility()
            if visibility not in {"default", "advanced"}:
                continue
            if child_sm_property.GetIsInternal() or child_sm_property.GetInformationOnly():
                continue

            child_prop = value.GetProperty(child_name)
            child_type = type(child_prop).__name__
            if child_type in {"ProxyProperty", "InputProperty"}:
                continue
            try:
                child_value = child_prop.GetData()
            except Exception:
                child_value = None
            effective_child_type = cls._effective_property_type(child_type, child_sm_property)

            items.append(
                {
                    "scope": "unknown",
                    "name": f"{name}.{child_name}",
                    "label": f"{prefix_label} {cls._property_label(child_name)}",
                    "type": effective_child_type,
                    "visibility": visibility,
                    "value": cls._format_property_value(child_value),
                    "pending_value": cls._normalize_property_value(effective_child_type, child_value),
                    "options": cls._property_options(value, child_name, child_type, child_value),
                    "editable": cls._is_editable_property(effective_child_type, child_value, []),
                    "priority": cls._property_priority(f"{name}.{child_name}", scope),
                }
            )

        return items

    @staticmethod
    def _tag_property_scope(properties, scope):
        """Annotate generated properties with their owning scope."""
        for item in properties:
            item["scope"] = scope
        return properties

    @staticmethod
    def _property_label(name):
        """Convert a proxy property name into a readable label."""
        label = []
        for idx, char in enumerate(name):
            if idx > 0 and char.isupper() and not name[idx - 1].isupper():
                label.append(" ")
            label.append(char)
        return "".join(label)

    @staticmethod
    def _format_property_value(value):
        """Format ParaView property values for the generated inspector."""
        if isinstance(value, (list, tuple)):
            return ", ".join(str(item) for item in value)
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _normalize_property_value(type_name, value):
        """Normalize property values for editing widgets."""
        if type_name == "BooleanProperty":
            return bool(value)
        if type_name == "ArrayListProperty":
            return list(value or [])
        if type_name == "ProxySelectionProperty":
            return value or ""
        if type_name == "ArraySelectionProperty":
            if isinstance(value, (list, tuple)) and len(value) >= 2:
                association, name = value[0], value[1]
                if not association or not name:
                    return "__none__"
                return f"{association}:{name}"
            return "__none__"
        if type_name == "VectorProperty" and isinstance(value, (list, tuple)):
            return ", ".join(str(item) for item in value)
        if isinstance(value, tuple):
            return list(value)
        return value

    @staticmethod
    def _is_editable_property(type_name, value, available):
        """Return True for the property types supported by the generated editor."""
        if type_name == "BooleanProperty":
            return True
        if type_name == "ArrayListProperty":
            return True
        if type_name == "ProxySelectionProperty":
            return True
        if type_name == "ArraySelectionProperty":
            return True
        if type_name == "StringListProperty":
            return True
        if type_name == "EnumerationProperty":
            return True
        if type_name == "VectorProperty":
            return True
        return False

    @staticmethod
    def _property_priority(name, scope):
        """Assign a UI priority to properties so useful controls appear first."""
        display_priority = {
            "Opacity": 0,
            "Interpolation": 1,
            "MapScalars": 2,
            "InterpolateScalarsBeforeMapping": 3,
            "PointSize": 4,
            "LineWidth": 5,
            "AmbientColor": 6,
            "DiffuseColor": 7,
        }
        source_priority = {
            "PointArrayStatus": 0,
            "CellArrayStatus": 1,
            "TimeArray": 2,
            "Scalars": 3,
            "Vectors": 4,
            "ScaleFactor": 5,
            "GlyphMode": 6,
            "OrientationArray": 7,
            "ScaleArray": 8,
            "IntegrationDirection": 9,
            "MaximumStreamlineLength": 10,
            "Invert": 11,
            "Value": 12,
            "ClipType": 13,
            "ClipType.Origin": 14,
            "ClipType.Normal": 15,
            "ClipType.Offset": 16,
        }
        if scope == "display":
            return display_priority.get(name, 100)
        return source_priority.get(name, 100)

    @staticmethod
    def _apply_proxy_property_changes(proxy, properties):
        """Apply edits for a list of generated property descriptors."""
        if proxy is None:
            return

        for item in properties:
            if not item.get("editable"):
                continue

            target_proxy = proxy
            property_name = item["name"]
            if "." in property_name:
                parent_name, child_name = property_name.split(".", 1)
                target_proxy = getattr(proxy, parent_name, None)
                property_name = child_name
                if target_proxy is None:
                    continue

            if item["type"] == "ProxySelectionProperty":
                current_value = getattr(target_proxy, property_name)
                current = ParaViewBackend._normalize_property_value(
                    item["type"],
                    current_value.SMProxy.GetXMLName()
                    if hasattr(current_value, "SMProxy") and current_value.SMProxy is not None
                    else current_value,
                )
            else:
                prop = target_proxy.GetProperty(property_name)
                if prop is None or not hasattr(prop, "SetData"):
                    continue
                current = ParaViewBackend._normalize_property_value(
                    item["type"], prop.GetData()
                )
            pending = item.get("pending_value")
            normalized_pending = ParaViewBackend._coerce_property_value(
                item["type"], pending
            )
            normalized_pending_ui = ParaViewBackend._normalize_property_value(
                item["type"], normalized_pending
            )
            if current == normalized_pending_ui:
                continue

            if item["type"] == "ProxySelectionProperty":
                setattr(target_proxy, property_name, normalized_pending)
            else:
                prop.SetData(normalized_pending)

    @staticmethod
    def _coerce_property_value(type_name, value):
        """Coerce UI values into a representation suitable for ParaView properties."""
        if type_name == "ArrayListProperty":
            if value is None:
                return []
            return list(value)

        if type_name == "ProxySelectionProperty":
            return value

        if type_name == "BooleanProperty":
            return 1 if bool(value) else 0

        if type_name == "ArraySelectionProperty":
            if not value or value == "__none__":
                return [None, ""]
            association, _, name = str(value).partition(":")
            return [association, name]

        if type_name == "EnumerationProperty":
            return value

        if type_name == "VectorProperty":
            if value in ("", None):
                return value
            if isinstance(value, str) and "," in value:
                parts = [part.strip() for part in value.split(",")]
                try:
                    return [float(part) for part in parts if part != ""]
                except (TypeError, ValueError):
                    return value
            try:
                return float(value)
            except (TypeError, ValueError):
                return value

        return value

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

    @classmethod
    def _property_options(cls, proxy, name, type_name, value):
        """Return normalized option items for a property widget."""
        if type_name == "ArraySelectionProperty":
            return cls._array_selection_options(proxy, name, value)
        return list(getattr(proxy.GetProperty(name), "Available", []) or [])

    @staticmethod
    def _effective_property_type(type_name, sm_property):
        """Map raw ParaView property types to more useful UI-facing kinds."""
        if type_name == "VectorProperty" and ParaViewBackend._has_domain(
            sm_property, "vtkSMBooleanDomain"
        ):
            return "BooleanProperty"
        return type_name

    @staticmethod
    def _has_domain(sm_property, domain_class_name):
        """Return True when the given server-manager property exposes a matching domain."""
        if sm_property is None or not hasattr(sm_property, "NewDomainIterator"):
            return False
        iterator = sm_property.NewDomainIterator()
        iterator.Begin()
        while not iterator.IsAtEnd():
            domain = iterator.GetDomain()
            if domain is not None and domain.GetClassName() == domain_class_name:
                return True
            iterator.Next()
        return False

    @classmethod
    def _array_selection_options(cls, proxy, name, value):
        """Build selection options for ParaView array-selection properties."""
        data_information = None
        if proxy is not None:
            info_source = proxy
            if hasattr(proxy, "Input") and proxy.Input is not None:
                info_source = proxy.Input
            if hasattr(info_source, "GetDataInformation"):
                data_information = info_source.GetDataInformation()
        if data_information is None:
            return [{"text": "None", "value": "__none__"}]

        want_vectors = name in {"Vectors", "OrientationArray"}
        options = [{"text": "None", "value": "__none__"}]
        for association, info in (
            ("POINTS", data_information.GetPointDataInformation()),
            ("CELLS", data_information.GetCellDataInformation()),
        ):
            if info is None:
                continue
            for index in range(info.GetNumberOfArrays()):
                array_info = info.GetArrayInformation(index)
                if array_info is None or not array_info.GetName():
                    continue
                if want_vectors and array_info.GetNumberOfComponents() < 2:
                    continue
                name_value = array_info.GetName()
                options.append(
                    {
                        "text": f"{name_value} ({'Point' if association == 'POINTS' else 'Cell'})",
                        "value": f"{association}:{name_value}",
                    }
                )

        current = cls._normalize_property_value("ArraySelectionProperty", value)
        if current not in {item["value"] for item in options} and current != "__none__":
            options.append({"text": current.split(":", 1)[1], "value": current})
        return options

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
        if node.get("kind") == "filter":
            filter_key = node.get("filter_key")
            if filter_key in SUPPORTED_FILTERS:
                return SUPPORTED_FILTERS[filter_key]["icon"]
            return "mdi-filter-outline"
        return "mdi-database-outline"

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

    def _discover_experimental_filters(self):
        """Discover additional filter factories from `paraview.simple`."""
        supported_factories = {spec["factory"] for spec in SUPPORTED_FILTERS.values()}
        discovered = []
        for name in sorted(dir(self.simple)):
            if (
                not name
                or not name[0].isupper()
                or name in FILTER_DISCOVERY_EXCLUDE
                or name in supported_factories
            ):
                continue
            attr = getattr(self.simple, name, None)
            if not callable(attr):
                continue
            lower_name = name.lower()
            if not any(keyword in lower_name for keyword in FILTER_DISCOVERY_KEYWORDS):
                continue
            if any(token in lower_name for token in FILTER_DISCOVERY_EXCLUDE_SUBSTRINGS):
                continue
            discovered.append(
                {
                    "value": f"factory:{name}",
                    "label": self._property_label(name),
                    "factory": name,
                    "icon": self._experimental_filter_icon(name),
                }
            )
        return discovered

    @staticmethod
    def _experimental_filter_icon(factory_name):
        """Choose a best-effort icon for an experimental filter from its factory name."""
        lower_name = factory_name.lower()
        for keyword, icon in EXPERIMENTAL_FILTER_ICON_RULES:
            if keyword in lower_name:
                return icon
        return "mdi-flask-outline"
