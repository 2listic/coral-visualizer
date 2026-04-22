import pathlib
import pytest
from vtkmodules.vtkRenderingCore import vtkRenderer

DATA_DIR = pathlib.Path(__file__).parent.parent / "test_data"

def pytest_addoption(parser):
    parser.addoption(
        "--show-browser",
        action="store_true",
        default=False,
        help="Run E2E tests with visible browser (disables headless mode)",
    )

@pytest.fixture
def show_browser(request):
    return request.config.getoption("--show-browser")

@pytest.fixture
def tmp_renderer():
    """Bare vtkRenderer used as a render target; no window or interactor needed."""
    return vtkRenderer()
