from types import SimpleNamespace

from constants import ARRAY_SOLID
from paraview_runtime import ParaViewRuntime


class FakeState(SimpleNamespace):
    pass


class FakeOutputWindow:
    def __init__(self, output=""):
        self.output = output

    def GetOutput(self):
        return self.output


class FakeEditSession:
    def __init__(self, active=False):
        self.active = active
        self.source_label = "Edited Source" if active else ""
        self.geometry_mode = "volume"
        self.field_name = "Field"
        self.expression = "A+B"
        self.default_value = "0"
        self.selected = 3
        self.variables = ["A", "B"]
        self.overlay_dataset = None

    def available_cell_variables(self):
        return self.variables

    def selected_count(self):
        return self.selected

    def build_selected_volume_dataset(self):
        return self.overlay_dataset

    def default_output_filename(self):
        return "edited_result.vtu"


class FakeParaViewBackend:
    def __init__(self):
        self.calls = []
        self.display = object()
        self.source = object()
        self.view = SimpleNamespace(ViewSize=(400, 200))
        self.selected_array = "cell:M"
        self.representation = "Wireframe"

    def render(self):
        self.calls.append("render")

    def clear_active_selection(self):
        self.calls.append("clear_active_selection")

    def clear_edit_selection_overlay(self):
        self.calls.append("clear_edit_selection_overlay")

    def update_edit_selection_overlay(self, dataset):
        self.calls.append(("update_edit_selection_overlay", dataset))

    def get_ui_state(self):
        return {
            "pipeline_items": [{"text": "A", "value": "node-1"}],
            "active_pipeline_item": "node-1",
            "active_source_label": "Active",
            "active_source_type": "Calculator",
            "active_source_kind": "Filter Type",
            "active_parent_label": "Input",
            "source_path": "mesh.vtu",
            "point_arrays": [{"text": "U (Point)", "value": "point:U"}],
            "cell_arrays": [{"text": "M (Cell)", "value": "cell:M"}],
            "data_stats": [{"label": "Cells", "value": "3"}],
            "source_properties": [
                {"name": "A", "visibility": "default"},
                {"name": "B", "visibility": "advanced"},
            ],
            "display_properties": [
                {"name": "Opacity", "visibility": "default"},
                {"name": "LineWidth", "visibility": "advanced"},
            ],
            "show_calculator_help": True,
            "calculator_attribute_type": "Cell Data",
            "calculator_input_variables": ["M"],
            "calculator_coordinate_variables": ["coordsX", "coordsY", "coordsZ"],
            "active_visibility": True,
            "selected_array": self.selected_array,
            "representation": self.representation,
            "show_cells": True,
            "show_faces": False,
            "time_values": [0.0, 1.0, 2.0, 3.0],
            "current_time": 0.0,
            "time_index": 0,
            "total_timesteps": 4,
            "is_time_dependent": True,
        }

    def default_output_filename(self):
        return "pipeline_result.vtu"

    def export_active_dataset_for_editing(self):
        self.calls.append("export_active_dataset_for_editing")
        return {"dataset": object()}

    def apply_representation(self, representation):
        self.representation = representation
        self.calls.append(("apply_representation", representation))

    def apply_coloring(self, array_value):
        self.selected_array = array_value
        self.calls.append(("apply_coloring", array_value))

    def load_file(self, path):
        self.calls.append(("load_file", path))
        return ([{"text": "M (Cell)", "value": "cell:M"}], "cell:M")

    def reset_view(self):
        self.calls.append("reset_view")


def make_runtime(*, active_edit=False, output=""):
    state = FakeState(
        pick_mode=True,
        pv_runtime_message="",
        pv_runtime_type="error",
        save_filename="output",
        source_properties=[],
        display_properties=[],
        available_arrays=[],
        representation="Surface with Edges",
        error_message="stale",
        selection_count=99,
        save_status="stale",
        has_boundary=True,
    )
    backend = FakeParaViewBackend()
    edit_session = FakeEditSession(active=active_edit)
    view_calls = []
    runtime = ParaViewRuntime(
        state=state,
        pv_backend=backend,
        edit_session=edit_session,
        output_window=FakeOutputWindow(output),
        call_view_update=lambda **kwargs: view_calls.append(kwargs),
    )
    return runtime, state, backend, edit_session, view_calls


def test_render_and_push_and_runtime_message_parsing():
    runtime, state, backend, edit_session, view_calls = make_runtime(
        output="noise\nWARN: hello\nSaving settings file ignored\nERROR: broken\n"
    )

    runtime.render_and_push()
    runtime.refresh_runtime_message(clear=True)
    runtime.refresh_runtime_message()

    assert backend.calls[0] == "render"
    assert view_calls[0] == {}
    assert state.pv_runtime_message == ""

    runtime.output_window.output += "WARN: hello\nERROR: broken\n"
    runtime.refresh_runtime_message()

    assert "WARN: hello" in state.pv_runtime_message
    assert "ERROR: broken" in state.pv_runtime_message
    assert state.pv_runtime_type == "error"


def test_sync_edit_session_state_updates_modes_and_interactor_settings():
    runtime, state, backend, edit_session, view_calls = make_runtime(active_edit=True)

    runtime.sync_edit_session_state()

    assert state.edit_session_active is True
    assert state.edit_session_label == "Edited Source"
    assert state.edit_available_variables == ["A", "B"]
    assert state.selection_count == 3
    assert state.edit_enable_picking is True
    assert state.edit_picking_modes == ["select"]
    assert state.edit_interactor_events == ["EndAnimation"]
    # We now disable all interactor settings when picking is active to prevent rotation
    assert state.edit_interactor_settings == []

    state.pick_mode = False
    runtime.sync_edit_session_state()
    assert state.edit_enable_picking is False
    assert state.edit_picking_modes == []
    assert state.edit_interactor_settings[0]["action"] == "Rotate"


def test_normalize_edit_selection_ids_and_event_summary_cover_payload_shapes():
    runtime, state, backend, edit_session, view_calls = make_runtime()

    assert runtime.normalize_edit_selection_ids(None) == []
    assert runtime.normalize_edit_selection_ids({"compositeID": 7}) == [7]
    assert runtime.normalize_edit_selection_ids(
        {"selection": [{"compositeID": 3}, {"compositeID": 5}]}
    ) == [3, 5]
    assert runtime.normalize_edit_selection_ids({"position": {"x": 1, "y": 2}}) == [
        ("coords", 1, 2)
    ]
    assert runtime.normalize_edit_selection_ids({"x": 4, "y": 6}) == [("coords", 4, 6)]
    assert runtime.normalize_edit_selection_ids(
        {
            "position": {"x": 4, "y": 6},
            "selection": [{"compositeID": 3}, {"compositeID": 5}],
        }
    ) == [("coords", 4, 6)]
    assert runtime.normalize_edit_selection_ids(
        {
            "position": {"x": 100, "y": 50},
            "size": {"width": 200, "height": 100},
        }
    ) == [("coords", 200, 100)]
    assert runtime.normalize_edit_selection_ids(
        {
            "position": {"x": 100, "y": 50},
            "scale": {"x": 0.5, "y": 2.0},
        }
    ) == [("coords", 50, 100)]
    assert runtime.normalize_edit_selection_ids([{"compositeID": 9}]) == [9]

    summary = runtime.summarize_edit_event(
        {"mode": "click", "compositeID": 7, "x": 1, "y": 2}
    )
    assert '"resolved_coords": [' in summary

    coord_summary = runtime.summarize_edit_event({"position": {"x": 3, "y": 4}})
    assert '"resolved_coords": [' in coord_summary
    assert runtime.summarize_edit_event(None) == "No event payload"


def test_sync_edit_selection_overlay_covers_inactive_empty_and_present_selection():
    runtime, state, backend, edit_session, view_calls = make_runtime(active_edit=False)

    runtime.sync_edit_selection_overlay()
    assert backend.calls[:2] == [
        "clear_active_selection",
        "clear_edit_selection_overlay",
    ]
    assert view_calls[-1] == {}

    backend.calls.clear()
    edit_session.active = True
    edit_session.overlay_dataset = None
    runtime.sync_edit_selection_overlay()
    assert backend.calls[:2] == [
        "clear_active_selection",
        "clear_edit_selection_overlay",
    ]

    backend.calls.clear()
    edit_session.overlay_dataset = SimpleNamespace(GetNumberOfCells=lambda: 2)
    runtime.sync_edit_selection_overlay()
    assert backend.calls == [
        "clear_active_selection",
        ("update_edit_selection_overlay", edit_session.overlay_dataset),
    ]


def test_update_ui_state_applies_backend_metadata_and_editability_flags():
    runtime, state, backend, edit_session, view_calls = make_runtime(active_edit=True)

    runtime.update_ui_state()

    assert state.pipeline_items == [{"text": "A", "value": "node-1"}]
    assert state.active_pipeline_item == "node-1"
    assert state.source_default_property_count == 1
    assert state.source_advanced_property_count == 1
    assert state.display_default_property_count == 1
    assert state.display_advanced_property_count == 1
    assert state.available_arrays == [
        {"text": "Solid Color", "value": ARRAY_SOLID},
        {"text": "U (Point)", "value": "point:U"},
        {"text": "M (Cell)", "value": "cell:M"},
    ]
    assert state.selected_array == "cell:M"
    assert state.representation == "Wireframe"
    assert state.show_cells is True
    assert state.show_faces is False
    assert state.time_values == [0.0, 1.0, 2.0, 3.0]
    assert state.current_time == 0.0
    assert state.time_index == 0
    assert state.total_timesteps == 4
    assert state.is_time_dependent is True
    assert state.pv_properties_dirty is False
    assert state.save_filename == "edited_result.vtu"
    assert state.save_target_label == "Edited dataset: Edited Source"
    assert state.can_edit_active is True
    assert state.edit_session_active is True


def test_update_ui_state_tolerates_missing_backend_keys():
    runtime, state, backend, edit_session, view_calls = make_runtime()
    backend.get_ui_state = lambda: {
        "pipeline_items": [],
        "active_pipeline_item": None,
    }

    runtime.update_ui_state()

    assert state.active_source_label == ""
    assert state.active_source_kind == "Reader Type"
    assert state.show_calculator_help is False
    assert state.available_arrays == [{"text": "Solid Color", "value": ARRAY_SOLID}]
    assert state.selected_array == ARRAY_SOLID
    assert state.representation == "Surface with Edges"
    assert state.show_cells is True
    assert state.show_faces is True
    assert state.time_values == []
    assert state.total_timesteps == 0
    assert state.is_time_dependent is False


def test_apply_representation_apply_coloring_and_load_file_refresh_state():
    runtime, state, backend, edit_session, view_calls = make_runtime()

    runtime.apply_representation("Points")
    runtime.apply_coloring("cell:M")
    runtime.load_file("/tmp/data/mesh.vtu")

    assert ("apply_representation", "Points") in backend.calls
    assert ("apply_coloring", "cell:M") in backend.calls
    assert ("load_file", "/tmp/data/mesh.vtu") in backend.calls
    assert ("apply_representation", "Surface with Edges") in backend.calls
    assert ("apply_coloring", ARRAY_SOLID) in backend.calls
    assert "reset_view" in backend.calls
    assert state.selected_array == ARRAY_SOLID
    assert state.representation == "Surface with Edges"
    assert state.has_boundary is False
    assert state.error_message == ""
    assert state.selection_count == 0
    assert state.save_status == ""
    assert backend.calls.count("render") >= 1
    assert view_calls[-1] == {}
