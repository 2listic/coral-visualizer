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


class FakeLookupTable:
    def __init__(self):
        self.RGBPoints = [0.0, 0.0, 0.0, 1.0, 10.0, 1.0, 0.0, 0.0]
        self.InterpretValuesAsCategories = 0
        self.UseCategoricalColors = 0
        self.presets = []
        self.ranges = []

    def ApplyPreset(self, preset, rescale):
        self.presets.append((preset, rescale))

    def RescaleTransferFunction(self, range_min, range_max):
        self.ranges.append((range_min, range_max))
        self.RGBPoints[0] = range_min
        self.RGBPoints[-4] = range_max


class FakeDisplay:
    def __init__(
        self,
        color_array=None,
        representation="Surface With Edges",
        visibility=1,
        lookup_table=None,
    ):
        self.ColorArrayName = color_array
        self.Visibility = visibility
        self.LookupTable = lookup_table
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
        self.lookup_tables = {}

    def ColorBy(self, display, value):
        self.calls.append(("ColorBy", display, value))

    def GetColorTransferFunction(self, name):
        self.calls.append(("GetColorTransferFunction", name))
        self.lookup_tables.setdefault(name, FakeLookupTable())
        return self.lookup_tables[name]

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


class FakeClientView:
    def __init__(self, renderer):
        self._renderer = renderer

    def GetRenderer(self):
        return self._renderer


class FakeRenderer:
    def __init__(self, z_value=0.5):
        self.world_point = None
        self.display_point = (10.0, 10.0, 0.5)
        self.z_value = z_value

    def SetWorldPoint(self, x, y, z, w):
        self.world_point = (x, y, z, w)

    def WorldToDisplay(self):
        return None

    def GetDisplayPoint(self):
        return self.display_point

    def GetZ(self, x, y):
        return self.z_value


class FakeSimpleCell:
    def __init__(self, point_ids):
        self._point_ids = list(point_ids)

    def GetNumberOfPoints(self):
        return len(self._point_ids)

    def GetPointId(self, idx):
        return self._point_ids[idx]


class FakeSurfaceDataset:
    def __init__(self, points, cells):
        self._points = list(points)
        self._cells = [FakeSimpleCell(cell) for cell in cells]

    def GetNumberOfPoints(self):
        return len(self._points)

    def GetNumberOfCells(self):
        return len(self._cells)

    def GetCell(self, cell_id):
        return self._cells[cell_id]

    def GetPoint(self, point_id):
        return self._points[point_id]

    def GetPointData(self):
        return SimpleNamespace(GetArray=lambda name: None)


def make_backend():
    backend = ParaViewBackend.__new__(ParaViewBackend)
    renderer = FakeRenderer()
    backend.simple = FakeSimple()
    backend.servermanager = SimpleNamespace()
    backend.view = SimpleNamespace(
        ViewSize=(400, 200),
        GetProperty=lambda name: FakeProperty(),
        GetClientSideObject=lambda: FakeClientView(renderer),
    )
    backend.pipeline_nodes = []
    backend.active_node_id = None
    backend.data_directory = "/tmp/data"
    backend._filter_counts = {}
    backend.filter_catalog = FakeFilterCatalog()
    backend.property_inspector = FakePropertyInspector()
    backend._edit_selection_overlay = None
    backend._edit_selection_display = None
    backend._scalar_bar_visible = False
    return backend


def test_load_file_marks_time_dependent_for_non_list_timesteps():
    class FakeTimeValues:
        def __init__(self, values):
            self._values = list(values)

        def __iter__(self):
            return iter(self._values)

    class FakeScene:
        def __init__(self):
            self.TimeKeeper = SimpleNamespace(TimestepValues=FakeTimeValues([0, 1, 2, 3]))
            self.AnimationTime = 0.0
            self.updated = 0

        def UpdateAnimationUsingDataTimeSteps(self):
            self.updated += 1

    backend = make_backend()
    backend.state = SimpleNamespace(
        is_time_dependent=False,
        total_timesteps=0,
        time_values=[],
        current_time=0.0,
        time_index=0,
        time_playing=False,
    )
    backend.reset_camera = lambda: None
    backend.set_active_node = lambda _node_id: True

    source = FakeSource(
        "1",
        FakeDataInformation(point_names=["Velocity"], cell_names=["MaterialID"]),
    )
    display = FakeDisplay()
    scene = FakeScene()
    backend.simple.OpenDataFile = lambda _filename: source
    backend.simple.GetAnimationScene = lambda: scene
    backend.simple.Show = lambda _source, _view: display

    arrays, default_array = backend.load_file("/tmp/data/animation.pvd")

    assert scene.updated == 1
    assert backend.state.is_time_dependent is True
    assert backend.state.total_timesteps == 4
    assert backend.state.time_values == [0.0, 1.0, 2.0, 3.0]
    assert backend.state.current_time == 0.0
    assert backend.state.time_index == 0
    assert arrays[0]["value"] == ARRAY_SOLID
    assert default_array == ARRAY_SOLID


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


def test_color_controls_manage_lookup_table_scalar_bar_and_axes():
    backend = make_backend()
    backend.view.OrientationAxesVisibility = 1
    lut = FakeLookupTable()
    source = FakeSource("1", FakeDataInformation(point_names=["U"], cell_names=["M"]))
    display = FakeDisplay(color_array=("POINTS", "U"), lookup_table=lut)
    node = backend._make_node(source, display, "/tmp/data/mesh.vtu", "source", "mesh")
    backend.pipeline_nodes = [node]
    backend.active_node_id = node["id"]
    backend._scalar_bar_visible = True

    state = backend.get_color_control_state()
    assert state["color_controls_enabled"] is True
    assert state["color_range_min"] == "0"
    assert state["color_range_max"] == "10"
    assert state["color_bar_visible"] is True
    assert state["orientation_axes_visible"] is True

    backend.apply_color_map_preset("Cool to Warm")
    backend.apply_color_range("2.5", "7.5")
    backend.set_scalar_bar_visible(False)
    hidden_state = backend.get_color_control_state()
    backend.rescale_color_range_to_data()
    backend.set_orientation_axes_visible(False)
    backend.set_categorical_coloring(True)

    assert lut.presets == [("Cool to Warm", True)]
    assert lut.ranges == [(2.5, 7.5)]
    assert hidden_state["color_bar_visible"] is False
    assert display.scalar_bar_calls[-1] == (backend.view, False)
    assert backend.view.OrientationAxesVisibility == 0
    assert lut.InterpretValuesAsCategories == 1
    assert lut.UseCategoricalColors == 1


def test_rescale_color_range_over_time_uses_display_fallback_when_simple_api_missing():
    backend = make_backend()
    source = FakeSource("1", FakeDataInformation(point_names=["U"], cell_names=["M"]))
    display = FakeDisplay(color_array=("POINTS", "U"))
    node = backend._make_node(source, display, "/tmp/data/mesh.vtu", "source", "mesh")
    backend.pipeline_nodes = [node]
    backend.active_node_id = node["id"]
    backend._scalar_bar_visible = True

    backend.rescale_color_range_over_time()

    assert display.rescale_calls == [(False, True)]
    assert display.scalar_bar_calls[-1] == (backend.view, True)


def test_rescale_color_range_over_time_raises_when_no_compatible_api():
    backend = make_backend()
    source = FakeSource("1", FakeDataInformation(point_names=["U"], cell_names=["M"]))
    display = FakeDisplay(color_array=("POINTS", "U"))
    node = backend._make_node(source, display, "/tmp/data/mesh.vtu", "source", "mesh")
    backend.pipeline_nodes = [node]
    backend.active_node_id = node["id"]

    display.RescaleTransferFunctionToDataRange = None

    try:
        backend.rescale_color_range_over_time()
        assert False, "Expected RuntimeError when no compatible over-time API is available"
    except RuntimeError as exc:
        assert "rescale-over-time API" in str(exc)


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


def test_save_active_data_uses_legacy_writer_for_vtk(tmp_path, monkeypatch):
    backend = make_backend()
    source = FakeSource("1", FakeDataInformation())
    node = backend._make_node(source, FakeDisplay(), "/tmp/data/mesh.vtu", "source", "mesh")
    backend.pipeline_nodes = [node]
    backend.active_node_id = node["id"]

    class FakeVtkDataSet:
        pass

    monkeypatch.setattr(backend_module, "vtkDataSet", FakeVtkDataSet)

    writes = []

    class FakeWriter:
        def SetFileName(self, name):
            writes.append(("file", name))

        def SetInputData(self, dataset):
            writes.append(("data", dataset))

        def Write(self):
            writes.append(("write",))
            return 1

    monkeypatch.setattr(backend_module, "vtkDataSetWriter", lambda: FakeWriter())

    dataset = FakeVtkDataSet()
    backend.servermanager.Fetch = lambda _source: dataset
    backend.simple.SaveData = lambda path, proxy=None: writes.append(("savedata", path, proxy))

    output = tmp_path / "saved.vtk"
    backend.save_active_data(str(output))

    assert ("savedata", str(output), source) not in writes
    assert ("file", str(output)) in writes
    assert ("data", dataset) in writes
    assert ("write",) in writes


def test_save_active_data_falls_back_to_savedata_for_non_dataset_vtk(tmp_path, monkeypatch):
    backend = make_backend()
    source = FakeSource("1", FakeDataInformation())
    node = backend._make_node(source, FakeDisplay(), "/tmp/data/mesh.vtu", "source", "mesh")
    backend.pipeline_nodes = [node]
    backend.active_node_id = node["id"]

    class FakeVtkDataSet:
        pass

    monkeypatch.setattr(backend_module, "vtkDataSet", FakeVtkDataSet)
    backend.servermanager.Fetch = lambda _source: object()
    calls = []
    backend.simple.SaveData = lambda path, proxy=None: calls.append((path, proxy))

    output = tmp_path / "saved.vtk"
    backend.save_active_data(str(output))

    assert calls == [(str(output), source)]


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


def test_update_edit_selection_overlay_does_not_cleanup_scalar_bars():
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

    hide_calls = [call for call in backend.simple.calls if call[0] == "HideUnusedScalarBars"]
    assert hide_calls == []


def test_pick_visible_cell_ids_in_rect_filters_out_occluded_cells():
    backend = make_backend()
    source = FakeSource("1", FakeDataInformation())
    node = backend._make_node(source, FakeDisplay(), "/tmp/data/mesh.vtu", "source", "mesh")
    backend.pipeline_nodes = [node]
    backend.active_node_id = node["id"]

    backend.simple.ClearSelection = lambda *_args, **_kwargs: None
    backend.simple.SelectSurfaceCells = lambda **_kwargs: None
    backend._fetch_selected_original_cell_ids = lambda _source: [1, 2, 3]
    backend._filter_visible_cell_ids_by_depth = lambda _source, ids: [1, 3]

    picked = backend.pick_visible_cell_ids_in_rect(1, 2, 30, 40, behavior="touch")

    assert picked == [1, 3]


def test_pick_surface_keys_in_rect_skips_occluded_boundary_elements():
    backend = make_backend()
    source = FakeSource("1", FakeDataInformation())
    node = backend._make_node(source, FakeDisplay(), "/tmp/data/mesh.vtu", "source", "mesh")
    backend.pipeline_nodes = [node]
    backend.active_node_id = node["id"]
    backend.servermanager.Fetch = lambda _source: object()

    boundary = {
        (1, 2, 3): {"point_ids": (1, 2, 3)},
        (4, 5, 6): {"point_ids": (4, 5, 6)},
    }
    backend._boundary_codim_elements = lambda _dataset: boundary
    backend._project_points_to_display = lambda _dataset, _point_ids, _renderer: [
        (10.0, 10.0),
        (20.0, 10.0),
        (15.0, 20.0),
    ]
    backend._surface_element_is_visible = lambda _dataset, point_ids, _renderer: point_ids == (1, 2, 3)

    picked = backend._pick_surface_keys_in_rect([0, 0, 30, 30], behavior="touch")

    assert picked == [(1, 2, 3)]


def test_surface_keys_from_selected_dataset_falls_back_to_coordinate_mapping():
    # selected surface polydata points are reindexed but coordinates match source dataset
    selected = FakeSurfaceDataset(
        points=[(1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 0.0, 0.0)],
        cells=[(0, 1, 2)],
    )
    source = FakeSurfaceDataset(
        points=[(0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
        cells=[],
    )

    keys = ParaViewBackend._surface_keys_from_selected_dataset(
        selected, source_dataset=source
    )

    assert keys == [(1, 2, 3)]
