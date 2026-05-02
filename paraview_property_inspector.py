"""Property-inspector helpers for the ParaView backend."""

from constants import ARRAY_SOLID, CELL_PREFIX, POINT_PREFIX
from paraview_filter_catalog import humanize_paraview_name


class ParaViewPropertyInspector:
    """Generate editable property descriptors for ParaView proxies."""

    def collect_proxy_properties(self, proxy, scope="source"):
        """Extract user-facing proxy properties from a ParaView proxy."""
        if proxy is None:
            return []

        properties = []
        for name in proxy.ListProperties():
            prop = proxy.GetProperty(name)
            type_name = type(prop).__name__
            sm_property = proxy.SMProxy.GetProperty(
                name) if proxy.SMProxy is not None else None

            if type_name == "InputProperty":
                continue

            if type_name == "ProxyProperty" and name in {"ClipType", "GlyphType", "SeedType"}:
                properties.extend(
                    self._collect_proxy_subproperties(
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

            available = self._property_options(proxy, name, type_name, value)
            effective_type = self._effective_property_type(
                type_name, sm_property)
            properties.append(
                {
                    "scope": "unknown",
                    "name": name,
                    "label": humanize_paraview_name(name),
                    "type": effective_type,
                    "visibility": visibility,
                    "value": self._format_property_value(value),
                    "pending_value": self._normalize_property_value(effective_type, value),
                    "options": available,
                    "editable": self._is_editable_property(
                        effective_type, value, available
                    ),
                    "priority": self._property_priority(name, scope),
                }
            )

        properties = sorted(properties, key=lambda item: (
            item["priority"], item["label"]))
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

    def apply_proxy_property_changes(self, proxy, properties):
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
                current = self._normalize_property_value(
                    item["type"],
                    current_value.SMProxy.GetXMLName()
                    if hasattr(current_value, "SMProxy") and current_value.SMProxy is not None
                    else current_value,
                )
            else:
                prop = target_proxy.GetProperty(property_name)
                if prop is None or not hasattr(prop, "SetData"):
                    continue
                current = self._normalize_property_value(
                    item["type"], prop.GetData()
                )
            pending = item.get("pending_value")
            normalized_pending = self._coerce_property_value(
                item["type"], pending)
            normalized_pending_ui = self._normalize_property_value(
                item["type"], normalized_pending
            )
            if current == normalized_pending_ui:
                continue

            if item["type"] == "ProxySelectionProperty":
                setattr(target_proxy, property_name, normalized_pending)
            else:
                prop.SetData(normalized_pending)

    @staticmethod
    def tag_property_scope(properties, scope):
        """Annotate generated properties with their owning scope."""
        for item in properties:
            item["scope"] = scope
        return properties

    def _collect_proxy_subproperties(
        self, proxy, name, type_name, value, sm_property, scope
    ):
        """Expose proxy-switch properties and selected sub-proxy fields."""
        available = list(
            getattr(proxy.GetProperty(name), "Available", []) or [])
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
                    "label": humanize_paraview_name(name),
                    "type": "ProxySelectionProperty",
                    "visibility": parent_visibility,
                    "value": current_proxy_name,
                    "pending_value": current_proxy_name,
                    "options": available,
                    "editable": True,
                    "priority": self._property_priority(name, scope),
                }
            )

        if value is None or not hasattr(value, "ListProperties"):
            return items

        prefix_label = humanize_paraview_name(name)
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
            effective_child_type = self._effective_property_type(
                child_type, child_sm_property)

            items.append(
                {
                    "scope": "unknown",
                    "name": f"{name}.{child_name}",
                    "label": f"{prefix_label} {humanize_paraview_name(child_name)}",
                    "type": effective_child_type,
                    "visibility": visibility,
                    "value": self._format_property_value(child_value),
                    "pending_value": self._normalize_property_value(
                        effective_child_type, child_value
                    ),
                    "options": self._property_options(value, child_name, child_type, child_value),
                    "editable": self._is_editable_property(effective_child_type, child_value, []),
                    "priority": self._property_priority(f"{name}.{child_name}", scope),
                }
            )

        return items

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
        if type_name == "VectorProperty":
            if isinstance(value, (list, tuple)):
                return ", ".join(str(item) for item in value)
            if value is not None and hasattr(value, "__iter__"):
                try:
                    return ", ".join(str(item) for item in value)
                except Exception:
                    pass
            return str(value) if value is not None else ""
        if isinstance(value, tuple):
            return list(value)
        return value

    @staticmethod
    def _is_editable_property(type_name, value, available):
        """Return True for the property types supported by the generated editor."""
        return type_name in {
            "BooleanProperty",
            "ArrayListProperty",
            "ProxySelectionProperty",
            "ArraySelectionProperty",
            "StringListProperty",
            "EnumerationProperty",
            "VectorProperty",
        }

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

    def _property_options(self, proxy, name, type_name, value):
        """Return normalized option items for a property widget."""
        if type_name == "ArraySelectionProperty":
            return self._array_selection_options(proxy, name, value)
        return list(getattr(proxy.GetProperty(name), "Available", []) or [])

    def _effective_property_type(self, type_name, sm_property):
        """Map raw ParaView property types to more useful UI-facing kinds."""
        if type_name == "VectorProperty" and self._has_domain(
            sm_property, "vtkSMBooleanDomain"
        ):
            return "BooleanProperty"
        return type_name

    @staticmethod
    def _has_domain(sm_property, domain_class_name):
        """Return True when the given property exposes a matching domain."""
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

    def _array_selection_options(self, proxy, name, value):
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

        current = self._normalize_property_value(
            "ArraySelectionProperty", value)
        if current not in {item["value"] for item in options} and current != "__none__":
            options.append(
                {"text": current.split(":", 1)[1], "value": current})
        return options
