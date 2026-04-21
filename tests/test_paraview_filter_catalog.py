from paraview_filter_catalog import (
    ParaViewFilterCatalog,
    humanize_paraview_name,
)


class FakeSimple:
    AppendGeometry = staticmethod(lambda: None)
    CreateExtractor = staticmethod(lambda: None)
    Threshold = staticmethod(lambda: None)
    WarpCustom = staticmethod(lambda: None)
    SelectCells = staticmethod(lambda: None)
    readerHelper = staticmethod(lambda: None)
    not_callable = "ignore-me"


def test_humanize_paraview_name_splits_camel_case():
    assert humanize_paraview_name("WarpByVector") == "Warp By Vector"
    assert humanize_paraview_name("XMLReader") == "XMLReader"


def test_filter_catalog_discovers_only_valid_experimental_filters():
    catalog = ParaViewFilterCatalog(FakeSimple())

    discovered = {item["factory"]: item for item in catalog.experimental_filter_specs}

    assert "AppendGeometry" in discovered
    assert "WarpCustom" in discovered
    assert "Threshold" not in discovered
    assert "CreateExtractor" not in discovered
    assert "readerHelper" not in discovered
    assert discovered["AppendGeometry"]["icon"] == "mdi-plus-box-multiple-outline"
    assert discovered["WarpCustom"]["icon"] == "mdi-axis-arrow"


def test_filter_catalog_can_disable_experimental_filters():
    catalog = ParaViewFilterCatalog(FakeSimple(), show_experimental_filters=False)

    assert catalog.experimental_filter_specs == []
    assert catalog.get_available_filters()["experimental"] == []


def test_filter_catalog_exposes_supported_and_experimental_options():
    catalog = ParaViewFilterCatalog(FakeSimple())
    available = catalog.get_available_filters()

    assert any(item["value"] == "clip" for item in available["supported"])
    assert any(item["value"] == "factory:AppendGeometry" for item in available["experimental"])
    assert catalog.experimental_filter_spec("factory:AppendGeometry") == {
        "label": "Append Geometry",
        "factory": "AppendGeometry",
        "icon": "mdi-plus-box-multiple-outline",
    }
    assert catalog.experimental_filter_spec("missing") is None


def test_pipeline_icon_uses_filter_metadata_when_available():
    catalog = ParaViewFilterCatalog(FakeSimple(), show_experimental_filters=False)

    assert catalog.pipeline_icon({"kind": "filter", "filter_key": "clip"}) == "mdi-content-cut"
    assert catalog.pipeline_icon({"kind": "filter", "filter_key": "unknown"}) == "mdi-filter-outline"
    assert catalog.pipeline_icon({"kind": "source"}) == "mdi-database-outline"
