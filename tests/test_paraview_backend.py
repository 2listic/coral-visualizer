from types import SimpleNamespace

import paraview_backend as backend_module
from constants import ARRAY_SOLID, CELL_PREFIX, POINT_PREFIX
from paraview_backend import ParaViewBackend, is_paraview_available


class FakeProperty:
    def __init__(self, data=None):
        self.data = data

    def GetData(self):
        return self.data

    def SetData(self, value):
        self.data = value


class FakeArrayInfo:
    def __init__(self, name):
        self.name = name

    def GetName(self):
        return self.name


class FakeArrayCollection:
    def __init__(self, names):
        self.names = names

    def GetNumberOfArrays(self):
        return len(self.names)

    def GetArrayInformation(self, index):
        name = self.names[index]
        return None if name is None else FakeArrayInfo(name)


class FakeDataInformation:
    def __init__(
        self,
        *,
        point_names=None,
        cell_names=None,
        bounds=(0.0, 2.0, 0.0, 4.0, 0.0, 6.0),
        dataset_type="vtkUnstructuredGrid",
        points=12,
        cells=8,
    ):
        self.point_names = point_names or []
        self.cell_names = cell_names or []
        self.bounds = bounds
        self.dataset_type = dataset_type
        self.points = points
        self.cells = cells

    def GetPointDataInformation(self):
        return FakeArrayCollection(self.point_names)

    def GetCellDataInformation(self):
        return FakeArrayCollection(self.cell_names)

    def GetBounds(self):
        return self.bounds

    def GetDataSetTypeAsString(self):
        return self.dataset_type

    def GetNumberOfPoints(self):
        return self.points

    def GetNumberOfCells(self):
        return self.cells


class FakeSMProxy:
    def __init__(self, xml_name):
        self.xml_name = xml_name

    def GetXMLName(self):
        return self.xml_name


class FakeSource:
    def __init__(self, global_id, data_information, xml_name="LegacyVTKReader", properties=None):
        self.global_id = global_id
        self.data_information = data_information
        self.SMProxy = FakeSMProxy(xml_name)
        self.properties = properties or {}
        self.updated = 0

    def GetGlobalIDAsString(self):
        return self.global_id

    def GetDataInformation(self):
        return self.data_information

    def GetProperty(self, name):
        return self.properties.get(name)

    def UpdatePipeline(self):
        self.updated += 1


class FakeDisplay:
    def __init__(self, color_array=None, representation="Surface With Edges", visibility=1):
        self.ColorArrayName = color_array
        self.Visibility = visibility
        self._representation = FakeProperty(representation)
        self._pickable = FakeProperty(1)
        self.Pickable = 1
        self.scalar_bar_calls = []
        self.representation_calls = []
        self.rescale_calls = []

    def GetProperty(self, name):
        if name == "Representation":
            return self._representation
        if name == "Pickable":
            return self._pickable
        return None

    def SetRepresentationType(self, value):
        self.representation_calls.append(value)
        self._representation.SetData(value)

    def RescaleTransferFunctionToDataRange(self, *args):
        self.rescale_calls.append(args)

    def SetScalarBarVisibility(self, view, visible):
        self.scalar_bar_calls.append((view, visible))


class FakeSimple:
    def __init__(self):
        self.calls = []
        self.deleted = []
        self.hidden = []
        self.active_source = None
        self.active_view = None

    def ColorBy(self, display, value):
        self.calls.append(("ColorBy", display, value))

    def HideUnusedScalarBars(self, view):
        self.calls.append(("HideUnusedScalarBars", view))

    def Render(self, view):
        self.calls.append(("Render", view))

    def SetActiveSource(self, source):
        self.active_source = source
        self.calls.append(("SetActiveSource", source))

    def SetActiveView(self, view):
        self.active_view = view
        self.calls.append(("SetActiveView", view))

    def Hide(self, source, view):
        self.hidden.append((source, view))

    def Delete(self, source):
        self.deleted.append(source)


class FakeOverlayProducer:
    def __init__(self):
        self.output = None
        self.updated = 0

    def GetClientSideObject(self):
        return self

    def SetOutput(self, dataset):
        self.output = dataset

    def UpdatePipeline(self):
        self.updated += 1


class FakeOverlayDataset:
    def __init__(self, cell_count):
        self.cell_count = cell_count

    def GetNumberOfCells(self):
        return self.cell_count


class FakeFilterCatalog:
    def pipeline_icon(self, node):
        return f"icon:{node['kind']}"


class FakePropertyInspector:
    def __init__(self):
        self.calls = []

    def collect_proxy_properties(self, proxy, scope="source"):
        self.calls.append(("collect", proxy, scope))
        return [{"name": f"{scope}_property"}]

    def tag_property_scope(self, properties, scope):
        self.calls.append(("tag", scope))
        return [{**item, "scope": scope} for item in properties]

    def apply_proxy_property_changes(self, proxy, properties):
        self.calls.append(("apply", proxy, properties))


def make_backend():
    backend = ParaViewBackend.__new__(ParaViewBackend)
    backend.simple = FakeSimple()
    backend.servermanager = SimpleNamespace()
    backend.view = SimpleNamespace(
        ViewSize=(400, 200),
        GetProperty=lambda name: FakeProperty(),
    )
    backend.pipeline_nodes = []
    backend.active_node_id = None
    backend.data_directory = "/tmp/data"
    backend._filter_counts = {}
    backend.filter_catalog = FakeFilterCatalog()
    backend.property_inspector = FakePropertyInspector()
    backend._edit_selection_overlay = None
    backend._edit_selection_display = None
    return backend


def test_is_paraview_available_reflects_importable_modules(monkeypatch):
    monkeypatch.setattr(
        backend_module.importlib.util,
        "find_spec",
        lambda name: object() if name in {"paraview", "trame.widgets.paraview"} else None,
    )
    assert is_paraview_available() is True

    monkeypatch.setattr(backend_module.importlib.util, "find_spec", lambda name: None)
    assert is_paraview_available() is False


def test_array_collection_and_array_resolution_helpers():
    backend = make_backend()
    source = FakeSource(
        "1",
        FakeDataInformation(point_names=["Velocity"], cell_names=["MaterialID"]),
    )
    display = FakeDisplay(color_array=("CELLS", "MaterialID"))
    node = backend._make_node(source, display, "/tmp/data/mesh.vtu", "source", "mesh")
    backend.pipeline_nodes = [node]
    backend.active_node_id = node["id"]

    assert backend.get_available_arrays() == [
        {"text": "Solid Color", "value": ARRAY_SOLID},
        {"text": "Velocity (Point)", "value": f"{POINT_PREFIX}Velocity"},
        {"text": "MaterialID (Cell)", "value": f"{CELL_PREFIX}MaterialID"},
    ]
    assert backend._get_selected_array() == f"{CELL_PREFIX}MaterialID"
    assert backend._resolve_available_array_value(f"{POINT_PREFIX}MaterialID") == f"{CELL_PREFIX}MaterialID"
    assert backend._resolve_available_array_value("bad") == ARRAY_SOLID


def test_default_output_filename_relative_path_and_extension_mapping():
    backend = make_backend()
    source = FakeSource(
        "1",
        FakeDataInformation(dataset_type="vtkPolyData"),
    )
    node = backend._make_node(
        source,
        FakeDisplay(),
        "/tmp/data/nested/input file.vtu",
        "filter",
        "Clip 1 / weird",
    )
    backend.pipeline_nodes = [node]
    backend.active_node_id = node["id"]

    assert backend.default_output_extension() == ".vtp"
    assert backend.default_output_filename() == "Clip_1___weird.vtp"
    assert backend._relative_path("/tmp/data/nested/input file.vtu") == "nested/input file.vtu"
    assert backend._relative_path("/outside/file.vtu") == "file.vtu"


def test_apply_coloring_handles_solid_and_scalar_arrays():
    backend = make_backend()
    source = FakeSource("1", FakeDataInformation(point_names=["U"], cell_names=["M"]))
    display = FakeDisplay()
    node = backend._make_node(source, display, "/tmp/data/mesh.vtu", "source", "mesh")
    backend.pipeline_nodes = [node]
    backend.active_node_id = node["id"]

    backend.apply_coloring(ARRAY_SOLID)
    backend.apply_coloring(f"{POINT_PREFIX}U")

    assert ("ColorBy", display, None) in backend.simple.calls
    assert ("HideUnusedScalarBars", backend.view) in backend.simple.calls
    assert ("ColorBy", display, ("POINTS", "U")) in backend.simple.calls
    assert display.scalar_bar_calls == [(backend.view, True)]
    assert display.rescale_calls == [(True, False)]


def test_apply_coloring_solid_tolerates_colorby_none_failures():
    backend = make_backend()
    source = FakeSource("1", FakeDataInformation(point_names=["U"], cell_names=["M"]))
    display = FakeDisplay()
    node = backend._make_node(source, display, "/tmp/data/mesh.vtu", "source", "mesh")
    backend.pipeline_nodes = [node]
    backend.active_node_id = node["id"]

    backend.simple.ColorBy = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("invalid association string 'NONE'")
    )

    backend.apply_coloring(ARRAY_SOLID)

    # Should not raise and should still render
    assert ("Render", backend.view) in backend.simple.calls


def test_apply_representation_and_apply_property_changes_render():
    backend = make_backend()
    source = FakeSource("1", FakeDataInformation())
    display = FakeDisplay()
    node = backend._make_node(source, display, "/tmp/data/mesh.vtu", "source", "mesh")
    backend.pipeline_nodes = [node]
    backend.active_node_id = node["id"]

    backend.apply_representation("Wireframe")
    backend.apply_property_changes([{"name": "A"}], [{"name": "B"}])

    assert display.representation_calls == ["Wireframe"]
    assert source.updated == 1
    assert ("apply", source, [{"name": "A"}]) in backend.property_inspector.calls
    assert ("apply", display, [{"name": "B"}]) in backend.property_inspector.calls


def test_reset_view_updates_camera_from_bounds():
    backend = make_backend()
    source = FakeSource("1", FakeDataInformation(bounds=(0.0, 2.0, 0.0, 4.0, 1.0, 5.0)))
    node = backend._make_node(source, FakeDisplay(), "/tmp/data/mesh.vtu", "source", "mesh")
    backend.pipeline_nodes = [node]
    backend.active_node_id = node["id"]
    backend.view.ResetCamera = lambda: setattr(backend.view, "did_reset", True)

    backend.reset_view()

    assert backend.view.CameraFocalPoint == (1.0, 2.0, 3.0)
    assert backend.view.CameraViewUp == (0.0, 1.0, 0.0)
    assert backend.view.CenterOfRotation == (1.0, 2.0, 3.0)
    assert backend.view.did_reset is True


def test_get_ui_state_reports_defaults_without_active_source():
    backend = make_backend()

    ui_state = backend.get_ui_state()

    assert ui_state["pipeline_items"] == []
    assert ui_state["active_pipeline_item"] is None
    assert ui_state["active_source_label"] == ""
    assert ui_state["active_source_kind"] == "Reader Type"
    assert ui_state["show_calculator_help"] is False
    assert ui_state["calculator_coordinate_variables"] == [
        "coordsX",
        "coordsY",
        "coordsZ",
    ]
    assert ui_state["selected_array"] == ARRAY_SOLID
    assert ui_state["representation"] == "Surface with Edges"


def test_get_ui_state_reports_pipeline_metadata_for_active_source():
    backend = make_backend()
    source = FakeSource(
        "1",
        FakeDataInformation(point_names=["Velocity"], cell_names=["MaterialID"], points=7, cells=3),
        xml_name="Calculator",
        properties={"AttributeType": FakeProperty("Cell Data")},
    )
    display = FakeDisplay(color_array=("POINTS", "Velocity"), visibility=0)
    root = backend._make_node(source, display, "/tmp/data/mesh.vtu", "source", "mesh")
    child_source = FakeSource("2", FakeDataInformation(cell_names=["MaterialID"]), xml_name="Threshold")
    child = backend._make_node(child_source, FakeDisplay(), "/tmp/data/mesh.vtu", "filter", "Threshold 1", parent_id=root["id"], filter_key="threshold")
    backend.pipeline_nodes = [root, child]
    backend.active_node_id = root["id"]

    ui_state = backend.get_ui_state()

    assert ui_state["pipeline_items"][0]["node_icon"] == "icon:source"
    assert ui_state["pipeline_items"][1]["depth"] == 1
    assert ui_state["active_source_label"] == "mesh"
    assert ui_state["active_source_type"] == "Calculator"
    assert ui_state["active_source_kind"] == "Reader Type"
    assert ui_state["point_arrays"] == [{"text": "Velocity (Point)", "value": "point:Velocity"}]
    assert ui_state["cell_arrays"] == [{"text": "MaterialID (Cell)", "value": "cell:MaterialID"}]
    assert ui_state["data_stats"][0] == {"label": "Points", "value": "7"}
    assert ui_state["active_visibility"] is False
    assert ui_state["selected_array"] == "point:Velocity"
    assert ui_state["show_calculator_help"] is True
    assert ui_state["calculator_attribute_type"] == "Cell Data"
    assert ui_state["calculator_input_variables"] == ["MaterialID"]
    assert ui_state["source_properties"] == [{"name": "source_property", "scope": "source"}]
    assert ui_state["display_properties"] == [{"name": "display_property", "scope": "display"}]


def test_pipeline_helpers_cover_parentage_labels_and_descendants():
    backend = make_backend()
    root = backend._make_node(FakeSource("1", FakeDataInformation()), FakeDisplay(), "/tmp/data/a.vtu", "source", "Reader")
    child = backend._make_node(FakeSource("2", FakeDataInformation()), FakeDisplay(), "/tmp/data/a.vtu", "filter", "Clip 1", parent_id=root["id"], filter_key="clip")
    grandchild = backend._make_node(FakeSource("3", FakeDataInformation()), FakeDisplay(), "/tmp/data/a.vtu", "filter", "Threshold 1", parent_id=child["id"], filter_key="threshold")
    backend.pipeline_nodes = [root, child, grandchild]
    backend.active_node_id = grandchild["id"]

    assert [node["id"] for node in backend._collect_descendants(root["id"])] == [child["id"], grandchild["id"]]
    assert backend._pipeline_depth(grandchild) == 2
    assert backend._pipeline_label(grandchild) == "    Threshold 1"
    assert backend._active_kind_label() == "Filter Type"
    assert backend._active_parent_label() == "Clip 1"


def test_delete_node_removes_descendants_and_selects_last_remaining_node():
    backend = make_backend()
    root = backend._make_node(FakeSource("1", FakeDataInformation()), FakeDisplay(), "/tmp/data/a.vtu", "source", "Reader")
    child = backend._make_node(FakeSource("2", FakeDataInformation()), FakeDisplay(), "/tmp/data/a.vtu", "filter", "Clip 1", parent_id=root["id"], filter_key="clip")
    other = backend._make_node(FakeSource("3", FakeDataInformation()), FakeDisplay(), "/tmp/data/b.vtu", "source", "Other")
    backend.pipeline_nodes = [root, child, other]
    backend.active_node_id = child["id"]
    chosen = []
    backend.set_active_node = lambda node_id: chosen.append(node_id) or True

    deleted = backend.delete_node(root["id"])

    assert deleted is True
    assert backend.simple.deleted == [child["source"], root["source"]]
    assert [node["id"] for node in backend.pipeline_nodes] == [other["id"]]
    assert chosen == [other["id"]]


def test_candidate_pick_positions_and_pick_debug_info_cover_fallbacks():
    backend = make_backend()

    candidates = backend._candidate_pick_positions(0.25, 0.5)
    debug = backend.get_pick_debug_info(10, 20, radius=3)

    assert (0, 0) in candidates
    assert (0, 200) in candidates
    assert (100, 100) in candidates
    assert debug["raw_pointer"] == {"x": 10, "y": 20}
    assert debug["view_size"] == {"width": 400, "height": 200}
    assert debug["pick_radius"] == 3
    assert debug["candidate_positions"][0]["rect"] == [7, 17, 13, 23]


def test_update_edit_selection_overlay_makes_overlay_non_pickable_and_restores_active_source():
    backend = make_backend()
    source = FakeSource("1", FakeDataInformation())
    display = FakeDisplay()
    node = backend._make_node(source, display, "/tmp/data/mesh.vtu", "source", "mesh")
    backend.pipeline_nodes = [node]
    backend.active_node_id = node["id"]
    overlay_display = FakeDisplay()
    overlay = FakeOverlayProducer()

    backend.simple.TrivialProducer = lambda registrationName=None: overlay
    backend.simple.Show = lambda producer, view: overlay_display

    backend.update_edit_selection_overlay(FakeOverlayDataset(2))

    assert backend._edit_selection_overlay is overlay
    assert backend._edit_selection_display is overlay_display
    assert overlay_display.Pickable == 0
    assert overlay_display.GetProperty("Pickable").GetData() == 0
    assert backend.simple.active_source is source


def test_update_edit_selection_overlay_tolerates_colorby_none_failures():
    backend = make_backend()
    source = FakeSource("1", FakeDataInformation())
    display = FakeDisplay()
    node = backend._make_node(source, display, "/tmp/data/mesh.vtu", "source", "mesh")
    backend.pipeline_nodes = [node]
    backend.active_node_id = node["id"]
    overlay_display = FakeDisplay()
    overlay = FakeOverlayProducer()

    backend.simple.TrivialProducer = lambda registrationName=None: overlay
    backend.simple.Show = lambda producer, view: overlay_display
    backend.simple.ColorBy = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("invalid association string 'NONE'")
    )

    backend.update_edit_selection_overlay(FakeOverlayDataset(2))

    assert backend._edit_selection_overlay is overlay
    assert backend._edit_selection_display is overlay_display
    assert backend.simple.active_source is source
