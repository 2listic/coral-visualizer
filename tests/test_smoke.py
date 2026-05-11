from paraview_backend import ParaViewBackend, is_paraview_available


def test_paraview_availability_probe():
    """ParaView backend availability check should always return a boolean."""
    assert isinstance(is_paraview_available(), bool)


def test_paraview_representation_mapping():
    """UI representation labels should map to ParaView labels."""
    assert (
        ParaViewBackend._normalize_representation("Surface with Edges")
        == "Surface With Edges"
    )
