from types import SimpleNamespace

from constants import ARRAY_SOLID, BOUNDARY, INTERACTION_QUALITY_PRESETS
from state_setup import initialize_state, resolve_initial_file


class FakeParaViewBackend:
    def get_available_filters(self):
        return {
            "supported": [{"text": "Clip", "value": "clip", "icon": "mdi-content-cut"}],
            "experimental": [
                {
                    "text": "Append Geometry",
                    "value": "factory:AppendGeometry",
                    "icon": "mdi-plus-box-multiple-outline",
                }
            ],
        }


def test_resolve_initial_file_prefers_existing_requested_file(tmp_path):
    requested = tmp_path / "mesh.vtu"
    requested.write_text("dummy")

    result = resolve_initial_file(
        str(requested),
        [{"text": "fallback", "value": "fallback.vtu"}],
    )

    assert result == str(requested)


def test_resolve_initial_file_falls_back_to_first_available_item():
    result = resolve_initial_file(
        "missing.vtu",
        [
            {"text": "first", "value": "first.vtu"},
            {"text": "second", "value": "second.vtu"},
        ],
    )

    assert result == "first.vtu"


def test_initialize_state_populates_defaults_for_paraview_backend():
    state = SimpleNamespace()

    initialize_state(
        state,
        available_files=[{"text": "mesh", "value": "mesh.vtu"}],
        initial_file="mesh.vtu",
        backend="paraview",
        backend_message="ready",
        pv_backend=FakeParaViewBackend(),
    )

    assert state.backend == "paraview"
    assert state.backend_message == "ready"
    assert state.selected_file == "mesh.vtu"
    assert state.available_arrays == [{"text": "Solid Color", "value": ARRAY_SOLID}]
    assert state.selected_array == ARRAY_SOLID
    assert state.representation == "Surface with Edges"
    assert state.edit_target == BOUNDARY
    assert state.filter_supported_options == [
        {"text": "Clip", "value": "clip", "icon": "mdi-content-cut"}
    ]
    assert state.filter_experimental_options == [
        {
            "text": "Append Geometry",
            "value": "factory:AppendGeometry",
            "icon": "mdi-plus-box-multiple-outline",
        }
    ]
    assert state.show_experimental_filters is True
    assert state.mainViewMode == "remote"
    assert state.interaction_quality == "high"
    assert (
        state.interactive_quality
        == INTERACTION_QUALITY_PRESETS["high"]["interactive_quality"]
    )
    assert state.interactive_ratio == INTERACTION_QUALITY_PRESETS["high"]["interactive_ratio"]
    assert state.selection_behavior_options == [
        {"text": "Touch", "value": "touch"},
        {"text": "Contained", "value": "inside"},
    ]
    assert state.edit_selection_mode == "replace"
    assert state.edit_selection_mode_options == [
        {"text": "Replace", "value": "replace"},
        {"text": "Add", "value": "add"},
        {"text": "Subtract", "value": "subtract"},
        {"text": "Flip", "value": "flip"},
    ]
    assert state.edit_enable_picking is False
    assert "cursor: default" in state.edit_view_style

def test_initialize_state_uses_empty_filter_catalog_without_paraview_backend():
    state = SimpleNamespace()

    initialize_state(
        state,
        available_files=[],
        initial_file=None,
        backend="vtk",
        backend_message="vtk only",
        pv_backend=None,
    )

    assert state.backend == "vtk"
    assert state.filter_supported_options == []
    assert state.filter_experimental_options == []
    assert state.show_experimental_filters is False
    assert state.selected_file is None
    assert state.assign_id_value == "0"
