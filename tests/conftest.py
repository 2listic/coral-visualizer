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


@pytest.fixture(scope="session")
def shared_browser(request):
    show_browser = request.config.getoption("--show-browser")
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=not show_browser)
    yield browser
    browser.close()
    playwright.stop()


@pytest.fixture
def tmp_renderer():
    """Bare vtkRenderer used as a render target; no window or interactor needed."""
    return vtkRenderer()
