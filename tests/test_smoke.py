from conftest import DATA_DIR

from mesh_edit import BoundaryEditState, setup_edit_state
from pv_backend import ParaViewBackend, is_paraview_available
from vtk_pipeline import apply_coloring, build_visualization

SIMPLE_VTK = str(DATA_DIR / "hyper_cube-2ref.vtk")


def test_imports():
    """All modules import without errors (catches missing deps or syntax errors)."""
    import vtk_pipeline  # noqa: F401


def test_build_visualization(tmp_renderer):
    """Pipeline reads a file and produces a volume actor."""
    result = build_visualization(SIMPLE_VTK, tmp_renderer)
    assert result.vol_actor is not None


def test_apply_coloring(tmp_renderer):
    """Categorical coloring by MaterialID returns a non-null LUT."""
    result = build_visualization(SIMPLE_VTK, tmp_renderer)
    lut = apply_coloring(
        result.vol_actor,
        result.vol_mapper,
        result.vol_dataset,
        "cell:MaterialID",
        result.vol_luts,
    )
    assert lut is not None


def test_setup_edit_state(tmp_renderer):
    """Edit state setup extracts boundary sub-cells from a loaded mesh."""
    result = build_visualization(SIMPLE_VTK, tmp_renderer)
    edit = BoundaryEditState()
    setup_edit_state(edit, result, tmp_renderer)
    assert edit.merged_bnd_dataset is not None


def test_paraview_availability_probe():
    """ParaView backend availability check should always return a boolean."""
    assert isinstance(is_paraview_available(), bool)


def test_paraview_representation_mapping():
    """UI representation labels should map to ParaView labels."""
    assert (
        ParaViewBackend._normalize_representation("Surface with Edges")
        == "Surface With Edges"
    )
