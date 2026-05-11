# Representation modes
REPR_SURFACE = "Surface"
REPR_SURFACE_EDGES = "Surface with Edges"
REPR_WIREFRAME = "Wireframe"
REPR_POINTS = "Points"

# Array value sentinels and prefixes
ARRAY_SOLID = "__solid__"
POINT_PREFIX = "point:"
CELL_PREFIX = "cell:"

# Cell dimension categories
VOLUME = "volume"
BOUNDARY = "boundary"

# Known array names
MATERIAL_ID_ARRAY = "MaterialID"
MANIFOLD_ID_ARRAY = "ManifoldID"

# Cell arrays that should use categorical (indexed) coloring instead of continuous
CATEGORICAL_CELL_ARRAYS = [MATERIAL_ID_ARRAY, MANIFOLD_ID_ARRAY]

# Scalar bar slot names
SCALAR_BAR_ACTIVE_ARRAY = "bar_active_array"
SCALAR_BAR_BOUNDARY = "bar_boundary"

# deal.II default ID values
BOUNDARY_ID_DEFAULT = 0
MANIFOLD_ID_DEFAULT = -1

# Remote rendering interaction presets
INTERACTION_QUALITY_PRESETS = {
    "fast": {"interactive_quality": 60, "interactive_ratio": 0.7},
    "balanced": {"interactive_quality": 80, "interactive_ratio": 0.85},
    "high": {"interactive_quality": 95, "interactive_ratio": 1},
}
