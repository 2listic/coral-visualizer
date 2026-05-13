import pathlib
import sys
import pytest

try:
    from vtkmodules.vtkRenderingCore import vtkRenderer
except ModuleNotFoundError:
    print(
        "\n[conftest] ParaView/vtkmodules not found. "
        "Deactivate any virtualenv first, then: conda activate coral-paraview. "
        "If the pre-commit hook is broken, reinstall it from the conda env: "
        "conda run -n coral-paraview pre-commit install\n",
        file=sys.stderr,
    )
    sys.exit(1)

DATA_DIR = pathlib.Path(__file__).parent.parent / "test_data"


def pytest_addoption(parser):
    parser.addoption(
        "--show-browser",
        action="store_true",
        default=False,
        help="Run E2E tests with visible browser (disables headless mode)",
    )
    parser.addoption(
        "--slow-mo",
        type=int,
        default=0,
        help="Milliseconds to wait between Playwright actions (useful with --show-browser)",
    )


@pytest.fixture(scope="session")
def shared_browser(request):
    show_browser = request.config.getoption("--show-browser")
    slow_mo = request.config.getoption("--slow-mo")
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=not show_browser, slow_mo=slow_mo)
    yield browser
    browser.close()
    playwright.stop()


@pytest.fixture
def tmp_renderer():
    """Bare vtkRenderer used as a render target; no window or interactor needed."""
    return vtkRenderer()
