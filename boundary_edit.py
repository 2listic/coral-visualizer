"""
Mesh cell editing: extraction, selection, ID assignment, and save.

Provides the logic for:
- Extracting all exterior boundary cells from a deal.II mesh (including those
  not explicitly present in the file), selecting them interactively, and
  assigning BoundaryID (MaterialID) values.
- Selecting volume cells interactively and assigning MaterialID values.

The result can be saved as .vtu. ManifoldID values are preserved (read and
written back) but not edited here.
"""

from vtkmodules.vtkCommonCore import vtkIdList, vtkIntArray
from vtkmodules.vtkCommonDataModel import vtkUnstructuredGrid, vtkCellTypes
from vtkmodules.vtkFiltersCore import vtkExtractCells
from vtkmodules.vtkIOXML import vtkXMLUnstructuredGridWriter
from vtkmodules.vtkRenderingCore import vtkActor, vtkDataSetMapper

from constants import (
    MATERIAL_ID_ARRAY,
    MANIFOLD_ID_ARRAY,
    BOUNDARY_ID_DEFAULT,
    MANIFOLD_ID_DEFAULT,
)


# ---------------------------------------------------------------------------
# State container
# ---------------------------------------------------------------------------


class BoundaryEditState:
    """Holds all mutable state for boundary cell editing."""

    def __init__(self):
        self.full_dataset = None
        self.vol_dataset = None
        self.vol_cell_indices = []
        self.file_bnd_cell_indices = []
        self.merged_bnd_dataset = None
        self.merged_bnd_actor = None
        self.merged_bnd_mapper = None
        self.bnd_selection_set = set()
        self.bnd_selection_actor = None
        self.bnd_selection_mapper = None
        self.bnd_picker = None
        self.adjacency = None
        self.cell_normals = None
        self.vol_selection_set = set()
        self.vol_selection_actor = None
        self.vol_selection_mapper = None
        self.vol_picker = None
        self._observer_tag = None
        self._release_observer_tag = None

    def clear(self):
        self.full_dataset = None
        self.vol_dataset = None
        self.vol_cell_indices = []
        self.file_bnd_cell_indices = []
        self.merged_bnd_dataset = None
        self.merged_bnd_actor = None
        self.merged_bnd_mapper = None
        self.bnd_selection_set = set()
        self.bnd_selection_actor = None
        self.bnd_selection_mapper = None
        self.bnd_picker = None
        self.adjacency = None
        self.cell_normals = None
        self.vol_selection_set = set()
        self.vol_selection_actor = None
        self.vol_selection_mapper = None
        self.vol_picker = None
        self._observer_tag = None
        self._release_observer_tag = None


# ---------------------------------------------------------------------------
# Boundary extraction
# ---------------------------------------------------------------------------


def extract_all_boundary_subcells(full_dataset):
    """
    Extract all exterior boundary sub-cells from the full dataset.

    In 2D meshes the boundary sub-cells are *edges* (lines); in 3D they are
    *faces* (quads / triangles).  A sub-cell is on the geometric boundary
    when it is shared by exactly one volume cell.

    Returns
    -------
    vol_cell_indices : list[int]
        Cell indices in *full_dataset* that are volume cells (max dimension).
    file_bnd_cell_indices : list[int]
        Cell indices in *full_dataset* that are lower-dimension cells already
        present in the file.
    boundary_subcells : list[dict]
        Each dict has keys ``point_ids`` (tuple[int]), ``cell_type`` (int),
        and ``key`` (frozenset[int]).
    """
    n = full_dataset.GetNumberOfCells()
    if n == 0:
        return [], [], []

    max_dim = max(full_dataset.GetCell(i).GetCellDimension() for i in range(n))

    vol_indices = []
    bnd_indices = []
    for i in range(n):
        if full_dataset.GetCell(i).GetCellDimension() == max_dim:
            vol_indices.append(i)
        else:
            bnd_indices.append(i)

    # Count how many volume cells share each sub-cell (edge in 2D, face in 3D)
    subcell_count = {}  # frozenset(pt_ids) -> count
    subcell_info = {}  # frozenset(pt_ids) -> (cell_type, ordered_pt_ids)

    for ci in vol_indices:
        cell = full_dataset.GetCell(ci)
        if max_dim == 2:
            n_sub = cell.GetNumberOfEdges()
            get_sub = cell.GetEdge
        elif max_dim == 3:
            n_sub = cell.GetNumberOfFaces()
            get_sub = cell.GetFace
        else:
            continue

        for s in range(n_sub):
            sub = get_sub(s)
            ordered = tuple(
                int(sub.GetPointId(p)) for p in range(sub.GetNumberOfPoints())
            )
            key = frozenset(ordered)
            subcell_count[key] = subcell_count.get(key, 0) + 1
            if key not in subcell_info:
                subcell_info[key] = (sub.GetCellType(), ordered)

    # Exterior boundary = shared by exactly 1 volume cell
    boundary_subcells = []
    for key, count in subcell_count.items():
        if count == 1:
            cell_type, ordered = subcell_info[key]
            boundary_subcells.append(
                {
                    "point_ids": ordered,
                    "cell_type": cell_type,
                    "key": key,
                }
            )

    return vol_indices, bnd_indices, boundary_subcells


# ---------------------------------------------------------------------------
# Merged boundary dataset
# ---------------------------------------------------------------------------


def build_merged_boundary_dataset(full_dataset, file_bnd_indices, extracted_subcells):
    """
    Build a ``vtkUnstructuredGrid`` containing *all* boundary cells.

    This includes:
    - All exterior sub-cells extracted from volume cells (edges in 2D, faces
      in 3D).  Those that match a file boundary cell inherit its IDs;
      otherwise they receive default values.
    - File boundary cells that are *interior* (shared by 2 volume cells) —
      these are deal.II interior boundary markers and must be preserved.

    The returned grid shares the same point array as *full_dataset* so point
    IDs are consistent.
    """
    # Build lookup from file boundary cells
    mat_arr = full_dataset.GetCellData().GetArray(MATERIAL_ID_ARRAY)
    man_arr = full_dataset.GetCellData().GetArray(MANIFOLD_ID_ARRAY)

    # file_bnd_info: list of (key, cell_type, ordered_pts, mat_val, man_val)
    file_bnd_info = []
    file_bnd_keys = set()
    for ci in file_bnd_indices:
        cell = full_dataset.GetCell(ci)
        ordered = tuple(
            int(cell.GetPointId(p)) for p in range(cell.GetNumberOfPoints())
        )
        key = frozenset(ordered)
        mat_val = int(mat_arr.GetValue(ci)) if mat_arr else BOUNDARY_ID_DEFAULT
        man_val = int(man_arr.GetValue(ci)) if man_arr else MANIFOLD_ID_DEFAULT
        file_bnd_info.append((key, cell.GetCellType(), ordered, mat_val, man_val))
        file_bnd_keys.add(key)

    # Lookup for matching extracted subcells against file boundary cells
    file_ids_lookup = {info[0]: (info[3], info[4]) for info in file_bnd_info}

    # Extracted keys (exterior sub-cells)
    extracted_keys = {sc["key"] for sc in extracted_subcells}

    # Interior file boundary cells = in file but not among extracted exterior
    interior_bnd = [info for info in file_bnd_info if info[0] not in extracted_keys]

    total = len(extracted_subcells) + len(interior_bnd)

    # Build the merged grid
    bnd_grid = vtkUnstructuredGrid()
    bnd_grid.SetPoints(full_dataset.GetPoints())
    bnd_grid.Allocate(total)

    mat_id_arr = vtkIntArray()
    mat_id_arr.SetName(MATERIAL_ID_ARRAY)
    man_id_arr = vtkIntArray()
    man_id_arr.SetName(MANIFOLD_ID_ARRAY)

    # 1) Exterior sub-cells (from volume cell edges/faces)
    for sc in extracted_subcells:
        id_list = vtkIdList()
        for pid in sc["point_ids"]:
            id_list.InsertNextId(pid)
        bnd_grid.InsertNextCell(sc["cell_type"], id_list)

        if sc["key"] in file_ids_lookup:
            mat_val, man_val = file_ids_lookup[sc["key"]]
        else:
            mat_val = BOUNDARY_ID_DEFAULT
            man_val = MANIFOLD_ID_DEFAULT

        mat_id_arr.InsertNextValue(mat_val)
        man_id_arr.InsertNextValue(man_val)

    # 2) Interior file boundary cells (deal.II interior markers)
    for key, cell_type, ordered, mat_val, man_val in interior_bnd:
        id_list = vtkIdList()
        for pid in ordered:
            id_list.InsertNextId(pid)
        bnd_grid.InsertNextCell(cell_type, id_list)
        mat_id_arr.InsertNextValue(mat_val)
        man_id_arr.InsertNextValue(man_val)

    bnd_grid.GetCellData().AddArray(mat_id_arr)
    bnd_grid.GetCellData().AddArray(man_id_arr)

    return bnd_grid


# ---------------------------------------------------------------------------
# Adjacency and normals for group selection
# ---------------------------------------------------------------------------


def build_adjacency_graph(bnd_dataset):
    """Build a cell adjacency graph for the boundary dataset.

    Two cells are adjacent if they share an edge (2 common points for 2-D
    cells) or a point (for 1-D line cells).

    Returns ``dict[int, set[int]]`` mapping each cell ID to its neighbors.
    """
    n_cells = bnd_dataset.GetNumberOfCells()
    edge_to_cells = {}

    for ci in range(n_cells):
        cell = bnd_dataset.GetCell(ci)
        n_pts = cell.GetNumberOfPoints()
        pts = [int(cell.GetPointId(p)) for p in range(n_pts)]

        if cell.GetCellDimension() >= 2:
            # Adjacency via shared edges (pairs of consecutive points)
            for i in range(n_pts):
                edge = frozenset((pts[i], pts[(i + 1) % n_pts]))
                edge_to_cells.setdefault(edge, []).append(ci)
        elif cell.GetCellDimension() == 1:
            # Line cells: adjacency via shared points
            for pid in pts:
                edge_to_cells.setdefault(pid, []).append(ci)

    adjacency = {ci: set() for ci in range(n_cells)}
    for cells_sharing in edge_to_cells.values():
        for i in range(len(cells_sharing)):
            for j in range(i + 1, len(cells_sharing)):
                adjacency[cells_sharing[i]].add(cells_sharing[j])
                adjacency[cells_sharing[j]].add(cells_sharing[i])

    return adjacency


def compute_cell_normals(bnd_dataset):
    """Compute a unit normal vector for each cell in the boundary dataset.

    For 2-D cells (triangles, quads): cross product of two edge vectors.
    For 1-D cells (lines): 90-degree perpendicular in the XY plane.

    Returns a list of ``(nx, ny, nz)`` tuples, one per cell.
    """
    import math

    normals = []
    points = bnd_dataset.GetPoints()

    for ci in range(bnd_dataset.GetNumberOfCells()):
        cell = bnd_dataset.GetCell(ci)
        n_pts = cell.GetNumberOfPoints()

        if cell.GetCellDimension() >= 2 and n_pts >= 3:
            p0 = points.GetPoint(cell.GetPointId(0))
            p1 = points.GetPoint(cell.GetPointId(1))
            p2 = points.GetPoint(cell.GetPointId(2))

            v1 = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
            v2 = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])

            nx = v1[1] * v2[2] - v1[2] * v2[1]
            ny = v1[2] * v2[0] - v1[0] * v2[2]
            nz = v1[0] * v2[1] - v1[1] * v2[0]

            length = math.sqrt(nx * nx + ny * ny + nz * nz)
            if length > 1e-12:
                normals.append((nx / length, ny / length, nz / length))
            else:
                normals.append((0.0, 0.0, 1.0))

        elif cell.GetCellDimension() == 1 and n_pts >= 2:
            p0 = points.GetPoint(cell.GetPointId(0))
            p1 = points.GetPoint(cell.GetPointId(1))
            dx, dy = p1[0] - p0[0], p1[1] - p0[1]
            length = math.sqrt(dx * dx + dy * dy)
            if length > 1e-12:
                normals.append((-dy / length, dx / length, 0.0))
            else:
                normals.append((0.0, 1.0, 0.0))
        else:
            normals.append((0.0, 0.0, 1.0))

    return normals


def flood_select(start_cell, adjacency, normals, angle_threshold_deg):
    """BFS flood-fill selecting connected cells within an angle threshold.

    Expands from *start_cell* to neighbors whose normal angle relative to
    the **start cell's** normal is within *angle_threshold_deg* degrees.
    Uses ``abs(dot)`` to handle inconsistent winding order.

    Returns a ``set`` of selected cell IDs (always includes *start_cell*).
    """
    import math
    from collections import deque

    cos_threshold = math.cos(math.radians(angle_threshold_deg))
    ref = normals[start_cell]

    visited = {start_cell}
    queue = deque([start_cell])

    while queue:
        current = queue.popleft()
        for neighbor in adjacency.get(current, set()):
            if neighbor in visited:
                continue
            n = normals[neighbor]
            dot = ref[0] * n[0] + ref[1] * n[1] + ref[2] * n[2]
            if abs(dot) >= cos_threshold:
                visited.add(neighbor)
                queue.append(neighbor)

    return visited


# ---------------------------------------------------------------------------
# Actors
# ---------------------------------------------------------------------------


def create_boundary_actor(bnd_dataset):
    """Create actor + mapper for the merged boundary dataset (initially hidden)."""
    mapper = vtkDataSetMapper()
    mapper.SetInputData(bnd_dataset)
    mapper.ScalarVisibilityOff()

    actor = vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetLineWidth(3.0)
    # actor.GetProperty().SetColor(0.2, 0.6, 1.0)
    actor.SetVisibility(0)

    return actor, mapper


def create_selection_actor():
    """Create an initially-hidden actor for highlighting selected cells."""
    mapper = vtkDataSetMapper()
    mapper.ScalarVisibilityOff()

    actor = vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(1.0, 1.0, 0.0)  # yellow
    actor.GetProperty().SetLineWidth(5.0)
    actor.GetProperty().SetPointSize(8)
    actor.SetVisibility(0)

    return actor, mapper


def update_selection_actor(
    selection_set, bnd_dataset, selection_actor, selection_mapper
):
    """Rebuild the selection highlight actor from the current selection set."""
    if not selection_set:
        selection_actor.SetVisibility(0)
        return

    id_list = vtkIdList()
    for idx in sorted(selection_set):
        id_list.InsertNextId(idx)

    ext = vtkExtractCells()
    ext.SetInputData(bnd_dataset)
    ext.SetCellList(id_list)
    ext.Update()

    selection_mapper.SetInputData(ext.GetOutput())
    selection_actor.SetVisibility(1)


# ---------------------------------------------------------------------------
# Picking
# ---------------------------------------------------------------------------


def create_cell_picker(bnd_actor):
    """Create a vtkCellPicker restricted to *bnd_actor*."""
    from vtkmodules.vtkRenderingCore import vtkCellPicker

    picker = vtkCellPicker()
    picker.SetTolerance(0.005)
    picker.PickFromListOn()
    picker.InitializePickList()
    picker.AddPickList(bnd_actor)
    return picker


def handle_bnd_pick(
    x, y, renderer, edit_state, group_select=False, angle_threshold=15.0
):
    """
    Pick at screen coordinates *(x, y)* and toggle the cell in *selection_set*.

    When *group_select* is ``True`` and adjacency/normals are available, a
    flood-fill selects (or deselects) all connected cells within
    *angle_threshold* degrees of the picked cell's normal.

    Returns the cell ID that was picked, or ``None`` if nothing was hit.
    """
    result = edit_state.bnd_picker.Pick(x, y, 0, renderer)
    if result == 0:
        return None

    cell_id = edit_state.bnd_picker.GetCellId()
    if cell_id < 0:
        return None

    if group_select and edit_state.adjacency and edit_state.cell_normals:
        group = flood_select(
            cell_id, edit_state.adjacency, edit_state.cell_normals, angle_threshold
        )
        if cell_id in edit_state.bnd_selection_set:
            edit_state.bnd_selection_set -= group
        else:
            edit_state.bnd_selection_set |= group
    else:
        if cell_id in edit_state.bnd_selection_set:
            edit_state.bnd_selection_set.discard(cell_id)
        else:
            edit_state.bnd_selection_set.add(cell_id)

    update_selection_actor(
        edit_state.bnd_selection_set,
        edit_state.merged_bnd_dataset,
        edit_state.bnd_selection_actor,
        edit_state.bnd_selection_mapper,
    )
    return cell_id


def handle_vol_pick(x, y, renderer, edit_state):
    """
    Pick a volume cell at screen coordinates *(x, y)* and toggle it in
    *vol_selection_set*.

    Returns the cell ID that was picked (local index in *vol_dataset*), or
    ``None`` if nothing was hit.
    """
    result = edit_state.vol_picker.Pick(x, y, 0, renderer)
    if result == 0:
        return None

    cell_id = edit_state.vol_picker.GetCellId()
    if cell_id < 0:
        return None

    if cell_id in edit_state.vol_selection_set:
        edit_state.vol_selection_set.discard(cell_id)
    else:
        edit_state.vol_selection_set.add(cell_id)

    update_selection_actor(
        edit_state.vol_selection_set,
        edit_state.vol_dataset,
        edit_state.vol_selection_actor,
        edit_state.vol_selection_mapper,
    )
    return cell_id


# ---------------------------------------------------------------------------
# ID assignment
# ---------------------------------------------------------------------------


def assign_id_to_selection(edit_state, array_name, value):
    """Set *value* on every selected cell in *array_name*."""
    arr = edit_state.merged_bnd_dataset.GetCellData().GetArray(array_name)
    if arr is None:
        return

    for cell_idx in edit_state.bnd_selection_set:
        arr.SetValue(cell_idx, value)

    # Bump MTime so the mapper knows the data changed (SetValue bypasses the pipeline).
    edit_state.merged_bnd_dataset.Modified()


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


def save_as_vtu(edit_state, output_path):
    """
    Reconstruct a full mesh (volume + edited boundary cells) and write *.vtu*.
    """
    full_ds = edit_state.full_dataset
    merged_bnd = edit_state.merged_bnd_dataset

    output = vtkUnstructuredGrid()
    output.SetPoints(full_ds.GetPoints())

    n_vol = len(edit_state.vol_cell_indices)
    n_bnd = merged_bnd.GetNumberOfCells()
    output.Allocate(n_vol + n_bnd)

    mat_arr = vtkIntArray()
    mat_arr.SetName(MATERIAL_ID_ARRAY)
    man_arr = vtkIntArray()
    man_arr.SetName(MANIFOLD_ID_ARRAY)

    # Volume cells — read MaterialID from vol_dataset (may have user edits),
    # ManifoldID from full_dataset (never edited).
    orig_man = full_ds.GetCellData().GetArray(MANIFOLD_ID_ARRAY)
    vol_ds = edit_state.vol_dataset
    vol_mat = vol_ds.GetCellData().GetArray(MATERIAL_ID_ARRAY) if vol_ds else None

    for local_idx, ci in enumerate(edit_state.vol_cell_indices):
        cell = full_ds.GetCell(ci)
        id_list = vtkIdList()
        for p in range(cell.GetNumberOfPoints()):
            id_list.InsertNextId(cell.GetPointId(p))
        output.InsertNextCell(cell.GetCellType(), id_list)
        mat_arr.InsertNextValue(int(vol_mat.GetValue(local_idx)) if vol_mat else 0)
        man_arr.InsertNextValue(
            int(orig_man.GetValue(ci)) if orig_man else MANIFOLD_ID_DEFAULT
        )

    # Boundary cells (with edits)
    bnd_mat = merged_bnd.GetCellData().GetArray(MATERIAL_ID_ARRAY)
    bnd_man = merged_bnd.GetCellData().GetArray(MANIFOLD_ID_ARRAY)

    for i in range(n_bnd):
        cell = merged_bnd.GetCell(i)
        id_list = vtkIdList()
        for p in range(cell.GetNumberOfPoints()):
            id_list.InsertNextId(cell.GetPointId(p))
        output.InsertNextCell(cell.GetCellType(), id_list)
        mat_arr.InsertNextValue(int(bnd_mat.GetValue(i)))
        man_arr.InsertNextValue(int(bnd_man.GetValue(i)))

    output.GetCellData().AddArray(mat_arr)
    output.GetCellData().AddArray(man_arr)

    # Preserve point data arrays (e.g. solution)
    for i in range(full_ds.GetPointData().GetNumberOfArrays()):
        output.GetPointData().AddArray(full_ds.GetPointData().GetArray(i))

    writer = vtkXMLUnstructuredGridWriter()
    writer.SetFileName(output_path)
    writer.SetInputData(output)
    writer.Write()
