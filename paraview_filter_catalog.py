"""Filter catalog helpers for the ParaView backend."""

SUPPORTED_FILTERS = {
    "calculator": {
        "label": "Calculator",
        "factory": "Calculator",
        "icon": "mdi-calculator-variant-outline",
    },
    "cell_centers": {
        "label": "Cell Centers",
        "factory": "CellCenters",
        "icon": "mdi-crosshairs-gps",
    },
    "clip": {"label": "Clip", "factory": "Clip", "icon": "mdi-content-cut"},
    "contour": {
        "label": "Contour",
        "factory": "Contour",
        "icon": "mdi-chart-bell-curve",
    },
    "coordinates": {
        "label": "Coordinates",
        "factory": "Coordinates",
        "icon": "mdi-axis-arrow-info",
    },
    "glyph": {"label": "Glyph", "factory": "Glyph", "icon": "mdi-vector-point"},
    "reflect": {
        "label": "Reflect",
        "factory": "Reflect",
        "icon": "mdi-reflect-horizontal",
    },
    "slice": {"label": "Slice", "factory": "Slice", "icon": "mdi-content-cut"},
    "stream_tracer": {
        "label": "Streamline",
        "factory": "StreamTracer",
        "icon": "mdi-chart-bell-curve-cumulative",
    },
    "threshold": {
        "label": "Threshold",
        "factory": "Threshold",
        "icon": "mdi-filter-outline",
    },
    "transform": {
        "label": "Transform",
        "factory": "Transform",
        "icon": "mdi-axis-arrow",
    },
    "tube": {"label": "Tube", "factory": "Tube", "icon": "mdi-cylinder"},
    "warp_by_scalar": {
        "label": "Warp by Scalar",
        "factory": "WarpByScalar",
        "icon": "mdi-image-filter-center-focus-strong",
    },
    "warp_by_vector": {
        "label": "Warp by Vector",
        "factory": "WarpByVector",
        "icon": "mdi-axis-arrow",
    },
}

FILTER_DISCOVERY_KEYWORDS = {
    "append",
    "calculator",
    "cell",
    "clean",
    "clip",
    "connectivity",
    "contour",
    "convert",
    "decimate",
    "extract",
    "glyph",
    "ghost",
    "ids",
    "interpolate",
    "mask",
    "merge",
    "normal",
    "point",
    "probe",
    "reflect",
    "slice",
    "stream",
    "subdivide",
    "threshold",
    "transform",
    "triangulate",
    "tube",
    "warp",
}

FILTER_DISCOVERY_EXCLUDE = {
    "CreateExtractor",
    "CreateXYPointPlotView",
    "FindExtractor",
    "GetExtractors",
    "LoadDistributedPlugin",
    "SaveExtracts",
    "SaveExtractsUsingCatalystOptions",
}

FILTER_DISCOVERY_EXCLUDE_SUBSTRINGS = {
    "amr",
    "block ids",
    "cellgrid",
    "composite",
    "extractor",
    "feature edges region ids",
    "ghost",
    "global ids",
    "global point and cell ids",
    "hierarchical",
    "hypertreegrid",
    "ids",
    "idselection",
    "ioss",
    "molecule",
    "octree",
    "pedigree",
    "process ids",
    "quadrature",
    "reader",
    "remove ghost",
    "select ",
    "selection",
    "source",
    "statistical model",
    "table",
}

EXPERIMENTAL_FILTER_ICON_RULES = [
    ("clip", "mdi-content-cut"),
    ("slice", "mdi-content-cut"),
    ("contour", "mdi-chart-bell-curve"),
    ("threshold", "mdi-filter-outline"),
    ("calculator", "mdi-calculator-variant-outline"),
    ("transform", "mdi-axis-arrow"),
    ("reflect", "mdi-reflect-horizontal"),
    ("tube", "mdi-cylinder"),
    ("glyph", "mdi-vector-point"),
    ("stream", "mdi-chart-bell-curve-cumulative"),
    ("warp", "mdi-axis-arrow"),
    ("extract", "mdi-select-drag"),
    ("clean", "mdi-broom"),
    ("triangulate", "mdi-triangle-outline"),
    ("connect", "mdi-graph-outline"),
    ("merge", "mdi-source-merge"),
    ("append", "mdi-plus-box-multiple-outline"),
]


def humanize_paraview_name(name):
    """Convert a ParaView proxy/property name into a readable label."""
    label = []
    for idx, char in enumerate(name):
        if idx > 0 and char.isupper() and not name[idx - 1].isupper():
            label.append(" ")
        label.append(char)
    return "".join(label)


class ParaViewFilterCatalog:
    """Own supported and experimental filter metadata for the backend."""

    def __init__(self, simple, *, show_experimental_filters=True):
        self.simple = simple
        self.show_experimental_filters = show_experimental_filters
        self.supported_filters = SUPPORTED_FILTERS
        self.experimental_filter_specs = (
            self._discover_experimental_filters() if show_experimental_filters else []
        )

    def get_available_filters(self):
        """Return supported and experimental filter lists for the UI."""
        return {
            "supported": [
                {"text": spec["label"], "value": key, "icon": spec["icon"]}
                for key, spec in self.supported_filters.items()
            ],
            "experimental": [
                {
                    "text": spec["label"],
                    "value": spec["value"],
                    "icon": spec["icon"],
                }
                for spec in self.experimental_filter_specs
            ],
        }

    def experimental_filter_spec(self, filter_key):
        """Return the discovered experimental filter spec matching the given UI key."""
        for spec in self.experimental_filter_specs:
            if spec["value"] == filter_key:
                return {
                    "label": spec["label"],
                    "factory": spec["factory"],
                    "icon": spec["icon"],
                }
        return None

    def pipeline_icon(self, node):
        """Return a kind-aware icon for a pipeline entry."""
        if node.get("kind") == "filter":
            filter_key = node.get("filter_key")
            if filter_key in self.supported_filters:
                return self.supported_filters[filter_key]["icon"]
            return "mdi-filter-outline"
        return "mdi-database-outline"

    def _discover_experimental_filters(self):
        """Discover additional filter factories from `paraview.simple`."""
        supported_factories = {
            spec["factory"] for spec in self.supported_filters.values()
        }
        discovered = []
        for name in sorted(dir(self.simple)):
            if (
                not name
                or not name[0].isupper()
                or name in FILTER_DISCOVERY_EXCLUDE
                or name in supported_factories
            ):
                continue
            attr = getattr(self.simple, name, None)
            if not callable(attr):
                continue
            lower_name = name.lower()
            if not any(keyword in lower_name for keyword in FILTER_DISCOVERY_KEYWORDS):
                continue
            if any(
                token in lower_name for token in FILTER_DISCOVERY_EXCLUDE_SUBSTRINGS
            ):
                continue
            discovered.append(
                {
                    "value": f"factory:{name}",
                    "label": humanize_paraview_name(name),
                    "factory": name,
                    "icon": self._experimental_filter_icon(name),
                }
            )
        return discovered

    @staticmethod
    def _experimental_filter_icon(factory_name):
        """Choose a best-effort icon for an experimental filter from its factory name."""
        lower_name = factory_name.lower()
        for keyword, icon in EXPERIMENTAL_FILTER_ICON_RULES:
            if keyword in lower_name:
                return icon
        return "mdi-flask-outline"
