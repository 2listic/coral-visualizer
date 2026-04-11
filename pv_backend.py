"""ParaView backend adapter for the Trame visualizer."""

from __future__ import annotations

import importlib.util
import os

from constants import ARRAY_SOLID, CELL_PREFIX, MATERIAL_ID_ARRAY, POINT_PREFIX


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

    def __init__(self, data_directory=None):
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

        node = {
            "id": self._node_id(source),
            "source": source,
            "display": display,
            "filename": filename,
        }
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

        if node["display"] is not None and self.view is not None:
            self.simple.Hide(node["source"], self.view)
        self.simple.Delete(node["source"])

        self.pipeline_nodes = [entry for entry in self.pipeline_nodes if entry["id"] != node_id]

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

        filename = self._get_active_node()["filename"]
        relative_filename = self._relative_path(filename)
        active_label = os.path.basename(relative_filename or filename or "source")
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
                    "text": os.path.basename(node["filename"] or "source"),
                    "value": node["id"],
                    "icon": (
                        "mdi-eye-outline"
                        if node["display"] is not None and node["display"].Visibility
                        else "mdi-eye-off-outline"
                    ),
                }
                for node in self.pipeline_nodes
            ],
            "active_pipeline_item": self.active_node_id,
            "active_source_label": active_label,
            "active_source_type": xml_name or source.__class__.__name__,
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
            sm_property = proxy.SMProxy.GetProperty(name)
            if sm_property is None:
                continue

            visibility = sm_property.GetPanelVisibility()
            if visibility not in {"default", "advanced"}:
                continue
            if sm_property.GetIsInternal() or sm_property.GetInformationOnly():
                continue

            prop = proxy.GetProperty(name)
            type_name = type(prop).__name__
            if type_name in {"ProxyProperty", "InputProperty"}:
                continue
            if scope == "display" and name in {"Representation", "ColorArrayName"}:
                continue

            try:
                value = prop.GetData()
            except Exception:
                value = None

            available = list(getattr(prop, "Available", []) or [])
            properties.append(
                {
                    "scope": "unknown",
                    "name": name,
                    "label": cls._property_label(name),
                    "type": type_name,
                    "visibility": visibility,
                    "value": cls._format_property_value(value),
                    "pending_value": cls._normalize_property_value(type_name, value),
                    "options": available,
                    "editable": cls._is_editable_property(type_name, value, available),
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
        if type_name == "ArrayListProperty":
            return list(value or [])
        if isinstance(value, tuple):
            return list(value)
        return value

    @staticmethod
    def _is_editable_property(type_name, value, available):
        """Return True for the property types supported by the generated editor."""
        if type_name == "ArrayListProperty":
            return True
        if type_name == "StringListProperty":
            return True
        if type_name == "EnumerationProperty":
            return True
        if type_name == "VectorProperty" and not isinstance(value, (list, tuple)):
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

            prop = proxy.GetProperty(item["name"])
            if prop is None or not hasattr(prop, "SetData"):
                continue

            current = ParaViewBackend._normalize_property_value(
                item["type"], prop.GetData()
            )
            pending = item.get("pending_value")
            normalized_pending = ParaViewBackend._coerce_property_value(
                item["type"], pending
            )
            if current == normalized_pending:
                continue

            prop.SetData(normalized_pending)

    @staticmethod
    def _coerce_property_value(type_name, value):
        """Coerce UI values into a representation suitable for ParaView properties."""
        if type_name == "ArrayListProperty":
            if value is None:
                return []
            return list(value)

        if type_name == "EnumerationProperty":
            return value

        if type_name == "VectorProperty":
            if value in ("", None):
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
