"""Integration tests for the application factory."""

import asyncio
import pathlib
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app_config import AppConfig
from constants import ARRAY_SOLID
from factory import (
    AppComponents,
    create_app,
    make_open_file_handler,
    resolve_requested_vtk_file,
)
from file_operations import FileOperationService
from paraview_runtime import ParaViewRuntime
from view_controls import ViewControllerProxy

DATA_DIR = pathlib.Path(__file__).parent.parent / "test_data"


def _config(data_dir, *, file=None):
    return AppConfig(
        file=file,
        data_directory=str(data_dir),
        devtools_enabled=False,
        show_experimental_filters=False,
    )


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    """Fully wired app against an empty data directory. Shared across tests — treat as read-only."""
    data_dir = tmp_path_factory.mktemp("factory_data")
    return create_app(config=_config(data_dir))


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_create_app_returns_app_components(app):
    assert isinstance(app, AppComponents)


def test_create_app_component_types(app):
    assert isinstance(app.view_controls, ViewControllerProxy)
    assert isinstance(app.paraview_runtime, ParaViewRuntime)
    assert isinstance(app.file_operations, FileOperationService)


def test_two_create_app_calls_use_independent_servers(tmp_path):
    """Each create_app() call gets its own Trame server instance."""
    a = create_app(config=_config(tmp_path))
    b = create_app(config=_config(tmp_path))
    assert a.server is not b.server
    assert a.state is not b.state


# ---------------------------------------------------------------------------
# Wiring consistency — object identity across the assembled stack
# ---------------------------------------------------------------------------


def test_pv_backend_is_shared_across_components(app):
    """ParaViewRuntime and FileOperationService must hold the same backend instance."""
    assert app.paraview_runtime.pv_backend is app.runtime_context.pv_backend
    assert app.file_operations.pv_backend is app.runtime_context.pv_backend


def test_edit_session_is_shared_across_components(app):
    """ParaViewRuntime and FileOperationService must hold the same EditSession."""
    assert app.paraview_runtime.edit_session is app.runtime_context.edit_session
    assert app.file_operations.edit_session is app.runtime_context.edit_session


def test_file_operations_data_directory_matches_config(app):
    assert app.file_operations.data_directory == app.config.data_directory


# ---------------------------------------------------------------------------
# State defaults — initialised from the real backend on startup
# ---------------------------------------------------------------------------


def test_state_color_defaults(app):
    assert app.state.selected_array == ARRAY_SOLID
    assert app.state.color_bar_visible is False
    assert app.state.orientation_axes_visible is True


def test_state_edit_defaults(app):
    assert app.state.edit_session_active is False
    assert app.state.edit_geometry_mode == "volume"
    assert app.state.edit_selection_mode == "replace"


def test_state_empty_data_dir_has_no_files(app):
    assert app.state.available_files == []
    assert app.state.selected_file is None


def test_filter_catalog_populated_from_real_backend(app):
    """Real ParaView filter discovery must produce at least one supported filter."""
    assert len(app.state.filter_supported_options) > 0


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def test_create_app_with_data_dir_picks_up_files():
    config = AppConfig(
        file=None,
        data_directory=str(DATA_DIR),
        devtools_enabled=False,
        show_experimental_filters=False,
    )
    components = create_app(config=config)
    assert len(components.state.available_files) > 0


def test_create_app_with_initial_file():
    initial = str(DATA_DIR / "cube.vtk")
    config = AppConfig(
        file=initial,
        data_directory=str(DATA_DIR),
        devtools_enabled=False,
        show_experimental_filters=False,
    )
    components = create_app(config=config)
    assert components.state.selected_file == initial


@pytest.fixture
def vtk_data_dir(tmp_path):
    """A data directory holding results/solution.vtu, plus a VTK file beside it."""
    data_dir = tmp_path / "data"
    vtk_file = data_dir / "results" / "solution.vtu"
    vtk_file.parent.mkdir(parents=True)
    vtk_file.write_text("vtk")
    (tmp_path / "outside.vtu").write_text("vtk")
    return data_dir


def _open_request(query):
    return SimpleNamespace(path="/api/open", rel_url=SimpleNamespace(query=query))


def _run_handler(handler, request):
    # pytest-playwright leaves an event loop running on the main thread.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, handler(request)).result()


def test_resolve_requested_vtk_file_stays_inside_configured_data_directory(
    vtk_data_dir,
):
    assert resolve_requested_vtk_file(str(vtk_data_dir), "results/solution.vtu") == str(
        vtk_data_dir / "results" / "solution.vtu"
    )


def test_resolve_requested_vtk_file_rejects_traversal(vtk_data_dir):
    with pytest.raises(PermissionError, match="remain inside"):
        resolve_requested_vtk_file(str(vtk_data_dir), "../outside.vtu")


def test_resolve_requested_vtk_file_rejects_absolute_path(vtk_data_dir):
    absolute = str(vtk_data_dir / "results" / "solution.vtu")
    with pytest.raises(ValueError, match="relative"):
        resolve_requested_vtk_file(str(vtk_data_dir), absolute)


@pytest.mark.parametrize(
    "working_directory",
    ["same-as-data-dir", "/app/shared-data", "", None],
    ids=["data-dir", "platform-mount", "empty", "absent"],
)
def test_open_file_handler_ignores_working_directory(vtk_data_dir, working_directory):
    query = {"file": "results/solution.vtu"}
    if working_directory == "same-as-data-dir":
        query["working_directory"] = str(vtk_data_dir)
    elif working_directory is not None:
        query["working_directory"] = working_directory
    state = SimpleNamespace(selected_file=None)

    handler = make_open_file_handler(str(vtk_data_dir), state)
    response = _run_handler(handler, _open_request(query))

    assert response.status == 302
    assert response.location == "/"
    assert state.selected_file == str(vtk_data_dir / "results" / "solution.vtu")


@pytest.mark.parametrize(
    ("file", "status"),
    [("../outside.vtu", 403), ("/etc/passwd", 400)],
    ids=["escaping", "absolute"],
)
def test_open_file_handler_refuses_files_outside_data_directory(
    vtk_data_dir, file, status
):
    state = SimpleNamespace(selected_file=None)

    handler = make_open_file_handler(str(vtk_data_dir), state)
    response = _run_handler(
        handler, _open_request({"working_directory": "/app/shared-data", "file": file})
    )

    assert response.status == status
    assert state.selected_file is None


# ---------------------------------------------------------------------------
# Direct method integration — real ParaViewRuntime + real ParaViewBackend
#
# These tests call methods on the wired components directly, bypassing the
# Trame state-change callback path (which requires a running event loop).
# The goal is to verify that the real backend contract matches what
# ParaViewRuntime expects — something mock-based tests in test_paraview_runtime
# cannot catch when FakeParaViewBackend drifts from the real implementation.
# ---------------------------------------------------------------------------


def test_load_file_creates_pipeline_entry(tmp_path):
    """load_file on the real backend must populate pipeline_items and reset derived state."""
    app = create_app(config=_config(tmp_path))
    app.paraview_runtime.load_file(str(DATA_DIR / "cube.vtk"))

    assert len(app.state.pipeline_items) > 0
    assert app.state.has_boundary is False
    assert app.state.selection_count == 0
    assert app.state.representation == "Surface with Edges"
    assert app.state.selected_array == ARRAY_SOLID


def test_load_file_exposes_arrays_for_files_with_data(tmp_path):
    """Loading a file that carries field arrays must surface them in available_arrays."""
    app = create_app(config=_config(tmp_path))
    app.paraview_runtime.load_file(str(DATA_DIR / "cube_with_boundary_id.vtk"))

    array_values = [item["value"] for item in app.state.available_arrays]
    assert ARRAY_SOLID in array_values
    assert len(app.state.available_arrays) > 1


def test_load_file_does_not_fire_notification_on_success(tmp_path):
    """A successful load must not trigger a notification."""
    app = create_app(config=_config(tmp_path))

    app.paraview_runtime.load_file(str(DATA_DIR / "cube.vtk"))

    assert app.state.notification_show is False
