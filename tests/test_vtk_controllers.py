from types import SimpleNamespace

from constants import BOUNDARY, MATERIAL_ID_ARRAY, VOLUME
from vtk_controllers import register_vtk_handlers


class FakeState(SimpleNamespace):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._handlers = {}

    def change(self, name):
        def decorator(fn):
            self._handlers[name] = fn
            return fn

        return decorator


class FakeCtrl:
    def __init__(self):
        self.handlers = {}

    def add(self, name):
        def decorator(fn):
            self.handlers[name] = fn
            return fn

        return decorator


class FakeActor:
    def __init__(self):
        self.visibility = None

    def SetVisibility(self, value):
        self.visibility = value


class FakeArray:
    def __init__(self, size):
        self.values = [0] * size

    def SetValue(self, index, value):
        self.values[index] = value


class FakeCellData:
    def __init__(self, array):
        self.array = array

    def GetArray(self, name):
        return self.array if name == MATERIAL_ID_ARRAY else None


class FakeDataset:
    def __init__(self, count, array=None):
        self.count = count
        self.array = array
        self.modified = 0

    def GetNumberOfCells(self):
        return self.count

    def GetCellData(self):
        return FakeCellData(self.array)

    def Modified(self):
        self.modified += 1


def make_edit_state():
    return SimpleNamespace(
        merged_bnd_actor=FakeActor(),
        bnd_selection_actor=FakeActor(),
        bnd_selection_set={1, 2},
        vol_selection_actor=FakeActor(),
        vol_selection_set={3},
        merged_bnd_dataset=FakeDataset(4),
        bnd_selection_mapper="bnd-selection-mapper",
        vol_dataset=FakeDataset(3, FakeArray(3)),
        vol_selection_mapper="vol-selection-mapper",
        full_dataset=object(),
    )


def register_handlers(state=None, edit_state=None, *, is_vtk_backend=True):
    state = state or FakeState(
        edit_mode=False,
        error_message="",
        edit_target=BOUNDARY,
        pick_mode=False,
        selection_count=5,
        selected_array="cell:MaterialID",
        representation="Surface",
        assign_id_value="7",
        save_filename="edited",
        save_status="",
        save_status_type="info",
    )
    ctrl = FakeCtrl()
    edit_state = edit_state or make_edit_state()
    calls = []
    viz = SimpleNamespace(
        bnd_actor=FakeActor(),
    )

    register_vtk_handlers(
        state,
        ctrl,
        is_vtk_backend=lambda: is_vtk_backend,
        viz_getter=lambda: viz,
        edit_state=edit_state,
        pick_interactor=SimpleNamespace(
            install=lambda: calls.append("install"),
            remove=lambda: calls.append("remove"),
        ),
        data_directory="/tmp/data",
        apply_edit_coloring=lambda target: calls.append(("apply_edit_coloring", target)),
        render_and_push=lambda: calls.append("render"),
        update_selection_actor=lambda selection, dataset, actor, mapper: calls.append(
            ("update_selection_actor", set(selection), dataset, actor, mapper)
        ),
        assign_id_to_selection=lambda edit_state_obj, array_name, value: calls.append(
            ("assign_id_to_selection", array_name, value)
        ),
        save_as_vtu=lambda edit_state_obj, output_path: calls.append(("save_as_vtu", output_path)),
        refresh_available_files=lambda: calls.append("refresh_files"),
        update_scalar_bars=lambda lut, array_value: calls.append(
            ("update_scalar_bars", lut, array_value)
        ),
        active_lut_getter=lambda: "active-lut",
        apply_vtk_coloring=lambda array_value: calls.append(("apply_vtk_coloring", array_value)),
        apply_vtk_representation_to_scene=lambda representation: calls.append(
            ("apply_vtk_representation", representation)
        ),
    )
    return state, ctrl, edit_state, calls, viz


def test_edit_mode_change_rejects_non_vtk_backend():
    state, ctrl, edit_state, calls, viz = register_handlers(is_vtk_backend=False)

    state._handlers["edit_mode"](True)

    assert state.edit_mode is False
    assert state.error_message == "Edit mode is not available on the ParaView backend yet."
    assert calls == []


def test_edit_mode_change_enables_and_disables_vtk_editing():
    state, ctrl, edit_state, calls, viz = register_handlers()

    state._handlers["edit_mode"](True)

    assert state.edit_target == BOUNDARY
    assert state.pick_mode is True
    assert viz.bnd_actor.visibility == 0
    assert calls[:3] == [("apply_edit_coloring", BOUNDARY), "install", "render"]

    calls.clear()
    state._handlers["edit_mode"](False)

    assert edit_state.merged_bnd_actor.visibility == 0
    assert edit_state.bnd_selection_actor.visibility == 0
    assert edit_state.vol_selection_actor.visibility == 0
    assert state.selection_count == 0
    assert edit_state.bnd_selection_set == set()
    assert edit_state.vol_selection_set == set()
    assert viz.bnd_actor.visibility == 1
    assert ("update_scalar_bars", "active-lut", "cell:MaterialID") in calls
    assert ("apply_vtk_coloring", "cell:MaterialID") in calls
    assert ("apply_vtk_representation", "Surface") in calls
    assert "remove" in calls
    assert "render" in calls


def test_edit_target_change_clears_both_selection_sets():
    state, ctrl, edit_state, calls, viz = register_handlers()
    state.edit_mode = True

    state._handlers["edit_target"](VOLUME)

    assert edit_state.bnd_selection_set == set()
    assert edit_state.vol_selection_set == set()
    assert state.selection_count == 0
    assert calls[0][0] == "update_selection_actor"
    assert calls[1][0] == "update_selection_actor"
    assert ("apply_edit_coloring", VOLUME) in calls
    assert "render" in calls


def test_clear_selection_and_select_all_cover_boundary_and_volume_paths():
    state, ctrl, edit_state, calls, viz = register_handlers()

    ctrl.handlers["clear_selection"]()
    assert edit_state.bnd_selection_set == set()
    assert state.selection_count == 0
    assert calls[-1] == "render"

    calls.clear()
    ctrl.handlers["select_all"]()
    assert edit_state.bnd_selection_set == {0, 1, 2, 3}
    assert state.selection_count == 4
    assert calls[-1] == "render"

    calls.clear()
    state.edit_target = VOLUME
    ctrl.handlers["clear_selection"]()
    assert edit_state.vol_selection_set == set()
    assert state.selection_count == 0

    calls.clear()
    ctrl.handlers["select_all"]()
    assert edit_state.vol_selection_set == {0, 1, 2}
    assert state.selection_count == 3


def test_assign_id_handles_invalid_value_and_boundary_and_volume_paths():
    state, ctrl, edit_state, calls, viz = register_handlers()
    state.assign_id_value = "bad"

    ctrl.handlers["assign_id"]()

    assert state.error_message == "Invalid ID value — must be an integer"

    state.error_message = ""
    state.assign_id_value = "9"
    ctrl.handlers["assign_id"]()

    assert ("assign_id_to_selection", MATERIAL_ID_ARRAY, 9) in calls
    assert ("apply_edit_coloring", BOUNDARY) in calls
    assert edit_state.bnd_selection_set == set()
    assert state.selection_count == 0

    calls.clear()
    state.edit_target = VOLUME
    edit_state.vol_selection_set = {0, 2}
    ctrl.handlers["assign_id"]()

    assert edit_state.vol_dataset.array.values == [9, 0, 9]
    assert edit_state.vol_dataset.modified == 1
    assert ("apply_edit_coloring", VOLUME) in calls
    assert edit_state.vol_selection_set == set()
    assert state.selection_count == 0


def test_save_vtu_handles_backend_guard_missing_data_success_and_failure():
    state, ctrl, edit_state, calls, viz = register_handlers(is_vtk_backend=False)

    ctrl.handlers["save_vtu"]()
    assert state.save_status == "Save is not available on the ParaView backend yet"
    assert state.save_status_type == "error"

    state, ctrl, edit_state, calls, viz = register_handlers()
    edit_state.full_dataset = None

    ctrl.handlers["save_vtu"]()
    assert state.save_status == "No data to save"
    assert state.save_status_type == "error"

    state, ctrl, edit_state, calls, viz = register_handlers()
    ctrl.handlers["save_vtu"]()
    assert ("save_as_vtu", "/tmp/data/edited.vtu") in calls
    assert "refresh_files" in calls
    assert state.save_status.endswith("edited.vtu")
    assert state.save_status_type == "success"

    state, ctrl, edit_state, calls, viz = register_handlers()
    ctrl = FakeCtrl()
    calls = []
    register_vtk_handlers(
        state,
        ctrl,
        is_vtk_backend=lambda: True,
        viz_getter=lambda: viz,
        edit_state=edit_state,
        pick_interactor=SimpleNamespace(install=lambda: None, remove=lambda: None),
        data_directory="/tmp/data",
        apply_edit_coloring=lambda target: None,
        render_and_push=lambda: None,
        update_selection_actor=lambda *args: None,
        assign_id_to_selection=lambda *args: None,
        save_as_vtu=lambda *args: (_ for _ in ()).throw(RuntimeError("cannot write")),
        refresh_available_files=lambda: None,
        update_scalar_bars=lambda *args: None,
        active_lut_getter=lambda: None,
        apply_vtk_coloring=lambda *args: None,
        apply_vtk_representation_to_scene=lambda *args: None,
    )

    ctrl.handlers["save_vtu"]()
    assert state.save_status == "Error: cannot write"
    assert state.save_status_type == "error"
