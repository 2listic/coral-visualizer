from types import SimpleNamespace

from paraview_property_inspector import ParaViewPropertyInspector


def make_property(class_name, *, data=None, available=None):
    class Property:
        def __init__(self):
            self.data = data
            self.Available = available

        def GetData(self):
            return self.data

        def SetData(self, value):
            self.data = value

    Property.__name__ = class_name
    return Property()


class FakeDomain:
    def __init__(self, class_name):
        self.class_name = class_name

    def GetClassName(self):
        return self.class_name


class FakeDomainIterator:
    def __init__(self, domains):
        self.domains = list(domains)
        self.index = 0

    def Begin(self):
        self.index = 0

    def IsAtEnd(self):
        return self.index >= len(self.domains)

    def GetDomain(self):
        return self.domains[self.index]

    def Next(self):
        self.index += 1


class FakeSMProperty:
    def __init__(
        self,
        visibility="default",
        *,
        is_internal=False,
        information_only=False,
        domains=None,
    ):
        self.visibility = visibility
        self.is_internal = is_internal
        self.information_only = information_only
        self.domains = domains or []

    def GetPanelVisibility(self):
        return self.visibility

    def GetIsInternal(self):
        return self.is_internal

    def GetInformationOnly(self):
        return self.information_only

    def NewDomainIterator(self):
        return FakeDomainIterator(self.domains)


class FakeSMProxy:
    def __init__(self, properties, *, xml_name="Plane"):
        self.properties = properties
        self.xml_name = xml_name

    def GetProperty(self, name):
        return self.properties.get(name)

    def GetXMLName(self):
        return self.xml_name


class FakeProxy:
    def __init__(self, properties, sm_properties=None, *, xml_name="Plane"):
        self._properties = properties
        self.SMProxy = (
            FakeSMProxy(sm_properties or {}, xml_name=xml_name)
            if sm_properties is not None
            else None
        )
        for name, value in properties.items():
            if type(value).__name__ == "ProxyProperty":
                setattr(self, name, value.data)

    def ListProperties(self):
        return list(self._properties.keys())

    def GetProperty(self, name):
        return self._properties.get(name)


class FakeArrayInformation:
    def __init__(self, name, components):
        self.name = name
        self.components = components

    def GetName(self):
        return self.name

    def GetNumberOfComponents(self):
        return self.components


class FakeArrayCollection:
    def __init__(self, arrays):
        self.arrays = arrays

    def GetNumberOfArrays(self):
        return len(self.arrays)

    def GetArrayInformation(self, index):
        return self.arrays[index]


class FakeDataInformation:
    def __init__(self, point_arrays, cell_arrays):
        self.point_arrays = FakeArrayCollection(point_arrays)
        self.cell_arrays = FakeArrayCollection(cell_arrays)

    def GetPointDataInformation(self):
        return self.point_arrays

    def GetCellDataInformation(self):
        return self.cell_arrays


class FakeProxyWithDataInfo:
    def __init__(self, data_information):
        self._data_information = data_information
        self.Input = None

    def GetDataInformation(self):
        return self._data_information

    def GetProperty(self, _name):
        return SimpleNamespace(Available=[])


def test_collect_proxy_properties_includes_proxy_subproperties_and_skips_internal_input():
    inspector = ParaViewPropertyInspector()

    clip_child = FakeProxy(
        {
            "Origin": make_property("VectorProperty", data=(1.0, 2.0, 3.0)),
            "Secret": make_property("VectorProperty", data=(9.0, 9.0, 9.0)),
        },
        {
            "Origin": FakeSMProperty("default"),
            "Secret": FakeSMProperty("advanced", is_internal=True),
        },
        xml_name="Plane",
    )

    proxy = FakeProxy(
        {
            "ClipType": make_property(
                "ProxyProperty",
                data=clip_child,
                available=["Plane", "Box"],
            ),
            "ScaleFactor": make_property("VectorProperty", data=(2.5,)),
            "Input": make_property("InputProperty", data=None),
        },
        {
            "ClipType": FakeSMProperty("default"),
            "ScaleFactor": FakeSMProperty("advanced"),
            "Input": FakeSMProperty("default"),
        },
    )

    properties = inspector.collect_proxy_properties(proxy, scope="source")
    names = [item["name"] for item in properties]

    assert "ClipType" in names
    assert "ClipType.Origin" in names
    assert "ScaleFactor" in names
    assert "Input" not in names
    assert "ClipType.Secret" not in names

    clip_selector = next(item for item in properties if item["name"] == "ClipType")
    clip_origin = next(item for item in properties if item["name"] == "ClipType.Origin")

    assert clip_selector["type"] == "ProxySelectionProperty"
    assert clip_selector["pending_value"] == "Plane"
    assert clip_origin["value"] == "1.0, 2.0, 3.0"
    assert clip_origin["pending_value"] == "1.0, 2.0, 3.0"


def test_collect_proxy_properties_limits_display_scope_to_supported_fields():
    inspector = ParaViewPropertyInspector()
    proxy = FakeProxy(
        {
            "Opacity": make_property("VectorProperty", data=(0.25,)),
            "Representation": make_property("StringListProperty", data="Surface"),
            "LineWidth": make_property("VectorProperty", data=(2.0,)),
        },
        {
            "Opacity": FakeSMProperty("default"),
            "Representation": FakeSMProperty("default"),
            "LineWidth": FakeSMProperty("default"),
        },
    )

    properties = inspector.collect_proxy_properties(proxy, scope="display")

    assert [item["name"] for item in properties] == ["Opacity", "LineWidth"]


def test_apply_proxy_property_changes_updates_plain_and_nested_properties():
    inspector = ParaViewPropertyInspector()

    child_proxy = FakeProxy(
        {"Origin": make_property("VectorProperty", data=(0.0, 0.0, 0.0))},
        {"Origin": FakeSMProperty("default")},
        xml_name="Plane",
    )

    proxy = FakeProxy(
        {
            "ClipType": make_property(
                "ProxyProperty",
                data=child_proxy,
                available=["Plane", "Box"],
            ),
            "ScaleFactor": make_property("VectorProperty", data=(1.0,)),
        },
        {
            "ClipType": FakeSMProperty("default"),
            "ScaleFactor": FakeSMProperty("default"),
        },
    )

    inspector.apply_proxy_property_changes(
        proxy,
        [
            {
                "editable": True,
                "name": "ScaleFactor",
                "type": "VectorProperty",
                "pending_value": "2.5, 3.5",
            },
            {
                "editable": True,
                "name": "ClipType.Origin",
                "type": "VectorProperty",
                "pending_value": "4, 5, 6",
            },
            {
                "editable": True,
                "name": "ClipType",
                "type": "ProxySelectionProperty",
                "pending_value": "Box",
            },
        ],
    )

    assert proxy.GetProperty("ScaleFactor").GetData() == [2.5, 3.5]
    assert proxy.ClipType == "Box"
    assert child_proxy.GetProperty("Origin").GetData() == [4.0, 5.0, 6.0]


def test_array_selection_options_include_none_filter_vectors_and_preserve_unknown_value():
    inspector = ParaViewPropertyInspector()
    data_information = FakeDataInformation(
        [
            FakeArrayInformation("Velocity", 3),
            FakeArrayInformation("Temperature", 1),
        ],
        [FakeArrayInformation("MaterialID", 1)],
    )
    proxy = FakeProxyWithDataInfo(data_information)

    vector_options = inspector._array_selection_options(
        proxy,
        "Vectors",
        ["POINTS", "LegacyArray"],
    )
    scalar_options = inspector._array_selection_options(
        proxy,
        "Scalars",
        ["CELLS", "MaterialID"],
    )

    assert vector_options[0] == {"text": "None", "value": "__none__"}
    assert {"text": "Velocity (Point)", "value": "POINTS:Velocity"} in vector_options
    assert not any(item["value"] == "POINTS:Temperature" for item in vector_options)
    assert {"text": "LegacyArray", "value": "POINTS:LegacyArray"} in vector_options
    assert {"text": "MaterialID (Cell)", "value": "CELLS:MaterialID"} in scalar_options


def test_property_helper_methods_cover_boolean_domains_and_array_coercion():
    inspector = ParaViewPropertyInspector()
    sm_property = FakeSMProperty(domains=[FakeDomain("vtkSMBooleanDomain")])

    assert (
        inspector._effective_property_type("VectorProperty", sm_property)
        == "BooleanProperty"
    )
    assert (
        inspector._normalize_property_value("ArraySelectionProperty", ["POINTS", "U"])
        == "POINTS:U"
    )
    assert (
        inspector._normalize_property_value("ArraySelectionProperty", ["", ""])
        == "__none__"
    )
    assert inspector._coerce_property_value("BooleanProperty", True) == 1
    assert inspector._coerce_property_value("ArraySelectionProperty", "POINTS:U") == [
        "POINTS",
        "U",
    ]
    assert inspector._coerce_property_value("VectorProperty", "1, 2.5, 3") == [
        1.0,
        2.5,
        3.0,
    ]
    assert inspector._property_priority("Opacity", "display") == 0
    assert inspector._property_priority("ClipType.Origin", "source") == 14
    assert inspector._is_editable_property("EnumerationProperty", None, []) is True
    assert inspector._format_property_value((1, 2)) == "1, 2"
