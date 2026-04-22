import pathlib

import pytest
from vtkmodules.vtkRenderingCore import vtkRenderer

DATA_DIR = pathlib.Path(__file__).parent.parent / "test_data"


@pytest.fixture
def tmp_renderer():
    """Bare vtkRenderer used as a render target; no window or interactor needed."""
    return vtkRenderer()
