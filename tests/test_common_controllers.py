from types import SimpleNamespace

import common_controllers


class FakeCtrl:
    def __init__(self):
        self.handlers = {}

    def add(self, name):
        def decorator(fn):
            self.handlers[name] = fn
            return fn

        return decorator


class FakeClientFile:
    def __init__(self, payload):
        self.name = payload.get("name")
        self.content = payload.get("content", b"")
        self.is_empty = payload.get("is_empty", False)


def _register(ctrl, state, **overrides):
    defaults = dict(
        pv_backend=SimpleNamespace(
            reset_camera=lambda: None,
            reset_view=lambda: None,
        ),
        call_view_update=lambda **kwargs: None,
        persist_uploaded_file=lambda client_file: "unused",
        refresh_available_files=lambda: None,
        persist_uploaded_state_file=lambda client_file: "unused",
        refresh_available_state_files=lambda: None,
    )
    defaults.update(overrides)
    common_controllers.register_common_controllers(ctrl, state, **defaults)


def test_reset_controllers_call_pv_backend_and_view_update():
    ctrl = FakeCtrl()
    state = SimpleNamespace()
    calls = []

    _register(
        ctrl,
        state,
        pv_backend=SimpleNamespace(
            reset_camera=lambda: calls.append("pv_reset_camera"),
            reset_view=lambda: calls.append("pv_reset_view"),
        ),
        call_view_update=lambda **kwargs: calls.append(("update", kwargs)),
    )

    ctrl.handlers["reset_camera"]()
    ctrl.handlers["reset_view"]()

    assert calls == [
        "pv_reset_camera",
        ("update", {}),
        "pv_reset_view",
        ("update", {"reset_camera": True}),
    ]


def test_upload_dataset_updates_state_on_success(monkeypatch):
    ctrl = FakeCtrl()
    state = SimpleNamespace(upload_status="", upload_status_type="", selected_file=None)
    calls = []

    monkeypatch.setattr(common_controllers, "ClientFile", FakeClientFile)

    _register(
        ctrl,
        state,
        persist_uploaded_file=lambda client_file: calls.append(client_file.name)
        or "/tmp/data/upload.vtu",
        refresh_available_files=lambda: calls.append("refresh"),
    )

    ctrl.handlers["upload_dataset"]([{"name": "upload.vtu", "content": b"vtk"}])

    assert calls == ["upload.vtu", "refresh"]
    assert state.selected_file == "/tmp/data/upload.vtu"
    assert state.upload_status == "Loaded upload.vtu"
    assert state.upload_status_type == "success"


def test_upload_dataset_reports_empty_and_failed_uploads(monkeypatch):
    ctrl = FakeCtrl()
    state = SimpleNamespace(upload_status="", upload_status_type="", selected_file=None)

    monkeypatch.setattr(common_controllers, "ClientFile", FakeClientFile)

    _register(
        ctrl,
        state,
        persist_uploaded_file=lambda client_file: (_ for _ in ()).throw(
            RuntimeError("disk full")
        ),
    )

    ctrl.handlers["upload_dataset"]([{"name": "empty.vtu", "is_empty": True}])
    assert state.upload_status == "Uploaded file was empty"
    assert state.upload_status_type == "error"

    ctrl.handlers["upload_dataset"]([{"name": "broken.vtu", "content": b"vtk"}])
    assert state.upload_status == "Upload failed: disk full"
    assert state.upload_status_type == "error"


def test_open_remote_file_updates_state_selection():
    ctrl = FakeCtrl()
    state = SimpleNamespace(remote_browser_dialog=True, selected_file=None)

    _register(ctrl, state)

    ctrl.handlers["open_remote_file"]("/tmp/mesh.vtu")

    assert state.remote_browser_dialog is False
    assert state.selected_file == "/tmp/mesh.vtu"


def test_open_remote_browsers_refresh_and_show_dialogs():
    ctrl = FakeCtrl()
    state = SimpleNamespace(
        remote_browser_dialog=False,
        remote_search_term="mesh",
        state_browser_dialog=False,
        state_browser_search_term="session",
    )
    calls = []

    _register(
        ctrl,
        state,
        refresh_available_files=lambda: calls.append("refresh_files"),
        refresh_available_state_files=lambda: calls.append("refresh_state_files"),
    )

    ctrl.handlers["open_remote_browser"]()
    ctrl.handlers["open_remote_state_browser"]()

    assert calls == ["refresh_files", "refresh_state_files"]
    assert state.remote_search_term == ""
    assert state.remote_browser_dialog is True
    assert state.state_browser_search_term == ""
    assert state.state_browser_dialog is True
