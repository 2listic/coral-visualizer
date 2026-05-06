from types import SimpleNamespace

import vtk_runtime as vtk_runtime_module
from constants import ARRAY_SOLID, CELL_PREFIX, MATERIAL_ID_ARRAY
from vtk_runtime import VtkRuntime


class FakeActorProperty:
    def __init__(self):
        self.colors = []

    def SetColor(self, r, g, b):
        self.colors.append((r, g, b))


class FakeActor:
    def __init__(self):
        self.visibility = None
        self.property = FakeActorProperty()

    def SetVisibility(self, value):
        self.visibility = value

    def GetProperty(self):
        return self.property


class FakeMapper:
    def __init__(self):
        self.scalar_visibility_off = 0

    def ScalarVisibilityOff(self):
        self.scalar_visibility_off += 1


class FakeDataset:
    def __init__(self):
        self.modified = 0

    def Modified(self):
        self.modified += 1


class FakeScalarBars:
    def __init__(self):
        self.calls = []

    def set_bar(self, slot, lut, label):
        self.calls.append(("set", slot, lut, label))

    def remove_bar(self, slot):
        self.calls.append(("remove", slot))


class FakeRenderWindow:
    def __init__(self):
        self.render_calls = 0

    def Render(self):
        self.render_calls += 1


class FakeCamera:
    def __init__(self):
        self.calls = []

    def SetFocalPoint(self, *args):
        self.calls.append(("focal", args))

    def SetPosition(self, *args):
        self.calls.append(("position", args))

    def SetViewUp(self, *args):
        self.calls.append(("view_up", args))


class FakeRenderer:
    def __init__(self, bounds=(0.0, 2.0, 0.0, 4.0, 1.0, 5.0)):
        self.bounds = bounds
        self.camera = FakeCamera()
        self.calls = []

    def ResetCamera(self):
        self.calls.append("ResetCamera")

    def ResetCameraClippingRange(self):
        self.calls.append("ResetCameraClippingRange")

    def ComputeVisiblePropBounds(self):
        return self.bounds

    def GetActiveCamera(self):
        return self.camera


def make_runtime():
    state = SimpleNamespace(
        representation="Surface",
        selected_array=f"{CELL_PREFIX}{MATERIAL_ID_ARRAY}",
        available_arrays=[],
        has_boundary=False,
        error_message="stale",
        selection_count=99,
        save_status="stale",
    )
    scalar_bars = FakeScalarBars()
    edit_state = SimpleNamespace(
        merged_bnd_actor=FakeActor(),
        merged_bnd_dataset=FakeDataset(),
        merged_bnd_mapper=FakeMapper(),
        vol_dataset=FakeDataset(),
        vol_selection_actor=FakeActor(),
        bnd_selection_actor=FakeActor(),
        bnd_selection_set={1, 2},
        vol_selection_set={3},
    )
    runtime = VtkRuntime(
        state=state,
        renderer=FakeRenderer(),
        render_window=FakeRenderWindow(),
        scalar_bars=scalar_bars,
        edit_state=edit_state,
        call_view_update=lambda: scalar_bars.calls.append(("view_update",)),
    )
    runtime.viz = SimpleNamespace(
        vol_actor=FakeActor(),
        bnd_actor=FakeActor(),
        vol_mapper=FakeMapper(),
        bnd_mapper=FakeMapper(),
        vol_dataset=FakeDataset(),
        bnd_dataset=FakeDataset(),
        vol_luts={},
        bnd_luts={MATERIAL_ID_ARRAY: "boundary-lut"},
        full_dataset=object(),
    )
    runtime.active_lut = "active-lut"
    return runtime, state, scalar_bars, edit_state


def test_update_scalar_bars_uses_labels_and_boundary_bar_rules():
    runtime, state, scalar_bars, edit_state = make_runtime()

    runtime.update_scalar_bars("lut", f"{CELL_PREFIX}{MATERIAL_ID_ARRAY}")
    runtime.update_scalar_bars(None, "point:U")

    assert scalar_bars.calls[0] == ("set", "bar_active_array", "lut", "Material ID")
    assert scalar_bars.calls[1] == (
        "set",
        "bar_boundary",
        "boundary-lut",
        "Boundary ID",
    )
    assert ("remove", "bar_active_array") in scalar_bars.calls
    assert ("remove", "bar_boundary") in scalar_bars.calls


def test_render_and_push_and_apply_representation_touch_all_relevant_actors(
    monkeypatch,
):
    runtime, state, scalar_bars, edit_state = make_runtime()
    repr_calls = []

    monkeypatch.setattr(
        vtk_runtime_module,
        "apply_representation",
        lambda vol_actor, bnd_actor, representation: repr_calls.append(
            (vol_actor, bnd_actor, representation)
        ),
    )

    runtime.apply_representation("Wireframe")
    runtime.render_and_push()

    assert len(repr_calls) == 4
    assert runtime.render_window.render_calls == 1
    assert scalar_bars.calls[-1] == ("view_update",)


def test_apply_edit_coloring_covers_boundary_and_volume_modes(monkeypatch):
    runtime, state, scalar_bars, edit_state = make_runtime()
    repr_calls = []
    cat_calls = []

    monkeypatch.setattr(
        vtk_runtime_module,
        "apply_representation",
        lambda vol_actor, bnd_actor, representation: repr_calls.append(
            (vol_actor, bnd_actor, representation)
        ),
    )
    monkeypatch.setattr(
        vtk_runtime_module,
        "apply_categorical_coloring",
        lambda mapper, dataset, array_name: cat_calls.append(
            (mapper, dataset, array_name)
        )
        or ("lut", None),
    )

    runtime.apply_edit_coloring("boundary")

    assert edit_state.merged_bnd_actor.visibility == 1
    assert runtime.viz.vol_mapper.scalar_visibility_off == 1
    assert runtime.viz.vol_actor.property.colors[-1] == (0.7, 0.7, 0.7)
    assert ("set", "bar_boundary", "lut", "Boundary ID") in scalar_bars.calls
    assert ("remove", "bar_active_array") in scalar_bars.calls

    scalar_bars.calls.clear()
    runtime.apply_edit_coloring("volume")

    assert edit_state.merged_bnd_actor.visibility == 0
    assert runtime.viz.vol_dataset.modified == 1
    assert ("remove", "bar_boundary") in scalar_bars.calls
    assert ("set", "bar_active_array", "lut", "Material ID") in scalar_bars.calls


def test_apply_coloring_updates_active_lut_scalar_bars_and_renders(monkeypatch):
    runtime, state, scalar_bars, edit_state = make_runtime()
    color_calls = []

    monkeypatch.setattr(
        vtk_runtime_module,
        "apply_coloring",
        lambda actor, mapper, dataset, selected_array, luts: color_calls.append(
            (actor, mapper, dataset, selected_array, luts)
        )
        or "new-lut",
    )

    runtime.apply_coloring("point:U")

    assert runtime.active_lut == "new-lut"
    assert len(color_calls) == 2
    assert scalar_bars.calls[0] == ("set", "bar_active_array", "new-lut", "U")
    assert runtime.render_window.render_calls == 1


def test_load_file_populates_state_and_calls_pipeline_helpers(monkeypatch):
    runtime, state, scalar_bars, edit_state = make_runtime()
    viz = SimpleNamespace(
        vol_actor=FakeActor(),
        bnd_actor=FakeActor(),
        vol_mapper=FakeMapper(),
        bnd_mapper=FakeMapper(),
        vol_dataset=FakeDataset(),
        bnd_dataset=FakeDataset(),
        vol_luts={},
        bnd_luts={},
        full_dataset=object(),
    )
    setup_calls = []

    monkeypatch.setattr(
        vtk_runtime_module, "build_visualization", lambda path, renderer: viz
    )
    monkeypatch.setattr(
        vtk_runtime_module,
        "get_available_arrays",
        lambda dataset: [
            {"text": "Solid Color", "value": ARRAY_SOLID},
            {"text": "MaterialID (Cell)", "value": f"{CELL_PREFIX}{MATERIAL_ID_ARRAY}"},
        ],
    )
    monkeypatch.setattr(
        vtk_runtime_module,
        "apply_coloring",
        lambda actor, mapper, dataset, selected_array, luts: "lut",
    )
    monkeypatch.setattr(
        vtk_runtime_module,
        "apply_representation",
        lambda vol_actor, bnd_actor, representation: setup_calls.append(
            ("apply_representation", representation)
        ),
    )
    monkeypatch.setattr(
        vtk_runtime_module,
        "setup_edit_state",
        lambda edit_state_obj, viz_obj, renderer: setup_calls.append(
            ("setup_edit_state", viz_obj, renderer)
        ),
    )

    runtime.load_file("/tmp/data/mesh.vtu")

    assert runtime.viz is viz
    assert state.available_arrays[1]["value"] == f"{CELL_PREFIX}{MATERIAL_ID_ARRAY}"
    assert state.selected_array == f"{CELL_PREFIX}{MATERIAL_ID_ARRAY}"
    assert state.has_boundary is True
    assert state.error_message == ""
    assert state.selection_count == 0
    assert state.save_status == ""
    assert ("apply_representation", "Surface") in setup_calls
    assert setup_calls[-1][0] == "setup_edit_state"
    assert runtime.render_window.render_calls == 1


def test_reset_camera_and_reset_view_drive_renderer_and_camera():
    runtime, state, scalar_bars, edit_state = make_runtime()

    runtime.reset_camera()
    runtime.reset_view()

    assert runtime.renderer.calls[0] == "ResetCamera"
    assert ("focal", (1.0, 2.0, 3.0)) in runtime.renderer.camera.calls
    assert ("view_up", (0.0, 1.0, 0.0)) in runtime.renderer.camera.calls
    assert "ResetCameraClippingRange" in runtime.renderer.calls
    assert runtime.render_window.render_calls == 2
