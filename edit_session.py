"""Edit-session scaffolding for the ParaView-backed workflow."""

from pathlib import Path

from vtkmodules.vtkCommonCore import vtkDoubleArray, vtkIdList
from vtkmodules.vtkCommonDataModel import vtkUnstructuredGrid
from vtkmodules.vtkFiltersCore import vtkArrayCalculator, vtkCellCenters, vtkExtractCells
from vtkmodules.vtkIOLegacy import vtkUnstructuredGridWriter
from vtkmodules.vtkIOXML import vtkXMLUnstructuredGridWriter


class EditSession:
    """Owns the temporary editable dataset derived from the active pipeline node."""

    def __init__(self):
        self.active = False
        self.source_node_id = None
        self.source_label = ""
        self.source_filename = ""
        self.working_dataset = None
        self.dirty = False
        self.geometry_mode = "volume"
        self.field_name = ""
        self.expression = ""
        self.default_value = "0"
        self.selected_cell_ids = set()
        self.selected_surface_keys = set()
        self._volume_adjacency = None
        self._surface_boundary_map = None

    def clear(self):
        """Reset the session to an inactive state."""
        self.active = False
        self.source_node_id = None
        self.source_label = ""
        self.source_filename = ""
        self.working_dataset = None
        self.dirty = False
        self.geometry_mode = "volume"
        self.field_name = ""
        self.expression = ""
        self.default_value = "0"
        self.selected_cell_ids = set()
        self.selected_surface_keys = set()
        self._volume_adjacency = None
        self._surface_boundary_map = None

    def begin(self, node_id, source_label, source_filename, dataset):
        """Start a new edit session from a fetched VTK dataset copy."""
        if not self.is_supported_dataset(dataset):
            raise TypeError(
                "Edit mode currently supports only vtkUnstructuredGrid datasets."
            )

        working_copy = vtkUnstructuredGrid()
        working_copy.DeepCopy(dataset)

        self.active = True
        self.source_node_id = node_id
        self.source_label = source_label or ""
        self.source_filename = source_filename or ""
        self.working_dataset = working_copy
        self.dirty = False
        self.geometry_mode = "volume"
        self.field_name = "field_1"
        self.expression = ""
        self.default_value = "0"
        self.selected_cell_ids = set()
        self.selected_surface_keys = set()
        self._volume_adjacency = None
        self._surface_boundary_map = None
        self._ensure_cell_centers_array()
        return self.working_dataset

    def default_output_filename(self):
        """Return a suggested filename for the current edit-session output."""
        label = self.source_label or Path(self.source_filename or "edited").stem or "edited"
        safe_label = "".join(
            char if char.isalnum() or char in {"-", "_"} else "_" for char in label
        ).strip("_")
        if not safe_label:
            safe_label = "edited"
        if not safe_label.endswith("_edited"):
            safe_label = f"{safe_label}_edited"
        return safe_label + ".vtu"

    def save(self, output_path):
        """Persist the working dataset to disk."""
        if not self.active or self.working_dataset is None:
            raise RuntimeError("No active edit session to save")

        if self.geometry_mode == "surface":
            self.materialize_surface_selection()

        suffix = Path(output_path).suffix.lower()
        if suffix == ".vtk":
            writer = vtkUnstructuredGridWriter()
        elif suffix == ".vtu":
            writer = vtkXMLUnstructuredGridWriter()
        else:
            raise ValueError(
                "Unsupported edit output format. Use .vtu or .vtk for edit-session saves."
            )
        writer.SetFileName(str(output_path))
        writer.SetInputData(self.working_dataset)
        if writer.Write() != 1:
            raise RuntimeError(f"Failed to write edited dataset to {output_path}")
        return str(output_path)

    def available_cell_variables(self):
        """Return cell-data variable names available to the edit calculator."""
        if not self.active or self.working_dataset is None:
            return []
        self._ensure_cell_centers_array()
        cell_data = self.working_dataset.GetCellData()
        return [
            cell_data.GetArrayName(i)
            for i in range(cell_data.GetNumberOfArrays())
            if cell_data.GetArrayName(i)
        ]

    def has_cell_field(self, field_name):
        """Return True when a cell-data field with ``field_name`` already exists."""
        if not self.active or self.working_dataset is None:
            return False
        name = (field_name or "").strip()
        if not name:
            return False
        return self.working_dataset.GetCellData().GetArray(name) is not None

    def selected_count(self):
        """Return the number of currently selected cells."""
        if self.geometry_mode == "surface":
            return len(self.selected_surface_keys)
        return len(self.selected_cell_ids)

    def clear_selection(self):
        """Drop the current volume-cell selection."""
        self.selected_cell_ids.clear()
        self.selected_surface_keys.clear()

    def select_all_cells(self):
        """Select every cell in the working dataset."""
        if not self.active or self.working_dataset is None:
            return 0
        if self.geometry_mode == "surface":
            self.selected_surface_keys = set(self._surface_boundary_map_for_top_cells())
            return len(self.selected_surface_keys)
        self.selected_cell_ids = set(range(self.working_dataset.GetNumberOfCells()))
        return len(self.selected_cell_ids)

    def toggle_cell_selection(self, cell_id, grow=False):
        """Toggle a single picked cell, optionally growing by adjacency."""
        if not self.active or self.working_dataset is None:
            return 0

        if self.geometry_mode == "surface":
            surface_keys = self._surface_keys_from_top_cells([cell_id])
            for key in surface_keys:
                if key in self.selected_surface_keys:
                    self.selected_surface_keys.discard(key)
                else:
                    self.selected_surface_keys.add(key)
            return len(self.selected_surface_keys)

        try:
            cell_id = int(cell_id)
        except (TypeError, ValueError):
            return len(self.selected_cell_ids)

        if cell_id < 0 or cell_id >= self.working_dataset.GetNumberOfCells():
            return len(self.selected_cell_ids)

        if grow:
            group = self._grow_volume_selection({cell_id})
            if cell_id in self.selected_cell_ids:
                self.selected_cell_ids -= group
            else:
                self.selected_cell_ids |= group
        else:
            if cell_id in self.selected_cell_ids:
                self.selected_cell_ids.discard(cell_id)
            else:
                self.selected_cell_ids.add(cell_id)

        return len(self.selected_cell_ids)

    def replace_selection(self, cell_ids, grow=False):
        """Replace the current selection with the provided cell IDs."""
        if not self.active or self.working_dataset is None:
            return 0

        if self.geometry_mode == "surface":
            self.selected_surface_keys = self._surface_keys_from_top_cells(cell_ids)
            return len(self.selected_surface_keys)

        normalized = {
            int(cell_id)
            for cell_id in (cell_ids or [])
            if isinstance(cell_id, (int, float)) and 0 <= int(cell_id) < self.working_dataset.GetNumberOfCells()
        }
        if grow:
            normalized = self._grow_volume_selection(normalized)
        self.selected_cell_ids = normalized
        return len(self.selected_cell_ids)

    def add_selection(self, cell_ids, grow=False):
        """Union the provided cell IDs into the current selection."""
        if not self.active or self.working_dataset is None:
            return 0

        if self.geometry_mode == "surface":
            self.selected_surface_keys |= self._surface_keys_from_top_cells(cell_ids)
            return len(self.selected_surface_keys)

        normalized = {
            int(cell_id)
            for cell_id in (cell_ids or [])
            if isinstance(cell_id, (int, float)) and 0 <= int(cell_id) < self.working_dataset.GetNumberOfCells()
        }
        if grow:
            normalized = self._grow_volume_selection(normalized)
        self.selected_cell_ids |= normalized
        return len(self.selected_cell_ids)

    def subtract_selection(self, cell_ids, grow=False):
        """Remove the provided cell IDs from the current selection."""
        if not self.active or self.working_dataset is None:
            return 0

        if self.geometry_mode == "surface":
            self.selected_surface_keys -= self._surface_keys_from_top_cells(cell_ids)
            return len(self.selected_surface_keys)

        normalized = {
            int(cell_id)
            for cell_id in (cell_ids or [])
            if isinstance(cell_id, (int, float))
            and 0 <= int(cell_id) < self.working_dataset.GetNumberOfCells()
        }
        if grow:
            normalized = self._grow_volume_selection(normalized)
        self.selected_cell_ids -= normalized
        return len(self.selected_cell_ids)

    def flip_selection(self, cell_ids, grow=False):
        """Toggle the provided cell IDs against the current selection."""
        if not self.active or self.working_dataset is None:
            return 0

        if self.geometry_mode == "surface":
            for key in self._surface_keys_from_top_cells(cell_ids):
                if key in self.selected_surface_keys:
                    self.selected_surface_keys.discard(key)
                else:
                    self.selected_surface_keys.add(key)
            return len(self.selected_surface_keys)

        normalized = {
            int(cell_id)
            for cell_id in (cell_ids or [])
            if isinstance(cell_id, (int, float))
            and 0 <= int(cell_id) < self.working_dataset.GetNumberOfCells()
        }
        if grow:
            normalized = self._grow_volume_selection(normalized)

        for cell_id in normalized:
            if cell_id in self.selected_cell_ids:
                self.selected_cell_ids.discard(cell_id)
            else:
                self.selected_cell_ids.add(cell_id)
        return len(self.selected_cell_ids)

    def apply_volume_field(self, field_name, expression, default_value, overwrite=False):
        """Create or update a scalar cell-data field on selected volume cells."""
        if not self.active or self.working_dataset is None:
            raise RuntimeError("No active edit session")

        field_name = (field_name or "").strip()
        if not field_name:
            raise ValueError("Field name is required")

        default_numeric = float(default_value)
        expression = (expression or "").strip()

        dataset = self.working_dataset
        self._ensure_cell_centers_array()
        cell_count = dataset.GetNumberOfCells()
        if cell_count == 0:
            raise RuntimeError("The working dataset has no cells")

        selected_ids = (
            sorted(self.selected_cell_ids)
            if self.selected_cell_ids
            else list(range(cell_count))
        )
        result_values = [default_numeric] * cell_count
        if expression:
            calculator = vtkArrayCalculator()
            calculator.SetInputData(dataset)
            calculator.SetAttributeTypeToCellData()
            calculator.SetResultArrayName("__edit_result__")

            cell_data = dataset.GetCellData()
            for index in range(cell_data.GetNumberOfArrays()):
                array = cell_data.GetArray(index)
                name = cell_data.GetArrayName(index)
                if array is None or not name:
                    continue
                num_components = array.GetNumberOfComponents()
                if num_components == 1:
                    calculator.AddScalarArrayName(name)
                elif num_components == 3:
                    calculator.AddVectorArrayName(name)

            calculator.SetFunction(expression)
            calculator.Update()
            output = calculator.GetOutput()
            result_array = output.GetCellData().GetArray("__edit_result__")
            if result_array is None:
                raise RuntimeError(
                    "Calculator did not produce a result array for the current expression."
                )
            if result_array.GetNumberOfComponents() != 1:
                raise RuntimeError(
                    "Only scalar edit fields are supported in Volume mode right now."
                )
            calculated = [result_array.GetTuple1(i) for i in range(cell_count)]
            for cell_id in selected_ids:
                result_values[cell_id] = calculated[cell_id]

        cell_data = dataset.GetCellData()
        existing = cell_data.GetArray(field_name)
        if existing is not None and not overwrite:
            raise RuntimeError(
                f"Field '{field_name}' already exists. Confirm overwrite to replace it."
            )

        if existing is not None:
            cell_data.RemoveArray(field_name)

        target = vtkDoubleArray()
        target.SetName(field_name)
        target.SetNumberOfComponents(1)
        target.SetNumberOfTuples(cell_count)
        cell_data.AddArray(target)

        for cell_id, value in enumerate(result_values):
            target.SetValue(cell_id, value)

        dataset.GetCellData().SetActiveScalars(field_name)
        dataset.Modified()
        self.field_name = field_name
        self.expression = expression
        self.default_value = str(default_value)
        self.dirty = True
        return field_name

    def build_selected_volume_dataset(self):
        """Return a lightweight dataset containing the currently selected cells."""
        return self.build_selected_dataset()

    def build_selected_dataset(self):
        """Return a lightweight dataset containing currently selected editable entities."""
        if (
            not self.active
            or self.working_dataset is None
        ):
            return None

        if self.geometry_mode == "surface":
            if not self.selected_surface_keys:
                return None
            return self._build_surface_dataset(self.selected_surface_keys)

        if not self.selected_cell_ids:
            return None

        id_list = vtkIdList()
        for cell_id in sorted(self.selected_cell_ids):
            id_list.InsertNextId(int(cell_id))

        extractor = vtkExtractCells()
        extractor.SetInputData(self.working_dataset)
        extractor.SetCellList(id_list)
        extractor.Update()

        output = vtkUnstructuredGrid()
        output.DeepCopy(extractor.GetOutput())
        return output

    def materialize_surface_selection(self):
        """Append selected boundary faces/edges as missing codim-1 cells."""
        if not self.active or self.working_dataset is None:
            return 0
        if self.geometry_mode != "surface":
            return 0
        if not self.selected_surface_keys:
            return 0

        dataset = self.working_dataset
        top_dim = self._top_dimension()
        if top_dim < 2:
            return 0

        boundary_map = self._surface_boundary_map_for_top_cells()
        existing = self._existing_codim_keys(top_dim - 1)
        missing_keys = [
            key for key in sorted(self.selected_surface_keys) if key in boundary_map and key not in existing
        ]
        if not missing_keys:
            return 0

        old_cell_count = dataset.GetNumberOfCells()
        for key in missing_keys:
            cell_type, point_ids = boundary_map[key]
            id_list = vtkIdList()
            for point_id in point_ids:
                id_list.InsertNextId(int(point_id))
            dataset.InsertNextCell(int(cell_type), id_list)

        self._extend_cell_data_for_new_cells(dataset, old_cell_count)

        dataset.Modified()
        self.dirty = True
        self._invalidate_geometry_caches()
        return len(missing_keys)

    def _grow_volume_selection(self, seed_ids):
        """Expand a set of cells by shared-face/shared-edge adjacency."""
        seeds = set(seed_ids or [])
        if not seeds:
            return set()

        adjacency = self._ensure_volume_adjacency()
        pending = list(seeds)
        visited = set(seeds)

        while pending:
            current = pending.pop()
            for neighbor in adjacency.get(current, set()):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                pending.append(neighbor)

        return visited

    def _top_dimension(self):
        if self.working_dataset is None:
            return 0
        return max(
            (
                self.working_dataset.GetCell(cell_id).GetCellDimension()
                for cell_id in range(self.working_dataset.GetNumberOfCells())
            ),
            default=0,
        )

    @staticmethod
    def _cell_key(cell):
        return tuple(
            sorted(int(cell.GetPointId(point_id)) for point_id in range(cell.GetNumberOfPoints()))
        )

    def _surface_boundary_map_for_top_cells(self):
        if self._surface_boundary_map is not None:
            return self._surface_boundary_map

        dataset = self.working_dataset
        if dataset is None:
            self._surface_boundary_map = {}
            return self._surface_boundary_map

        top_dim = self._top_dimension()
        if top_dim < 2:
            self._surface_boundary_map = {}
            return self._surface_boundary_map

        counts = {}
        metadata = {}
        for cell_id in range(dataset.GetNumberOfCells()):
            cell = dataset.GetCell(cell_id)
            if cell.GetCellDimension() != top_dim:
                continue

            if top_dim == 3:
                subcell_count = cell.GetNumberOfFaces()
                getter = cell.GetFace
            else:
                subcell_count = cell.GetNumberOfEdges()
                getter = cell.GetEdge

            for subcell_id in range(subcell_count):
                subcell = getter(subcell_id)
                key = self._cell_key(subcell)
                counts[key] = counts.get(key, 0) + 1
                if key not in metadata:
                    point_ids = tuple(
                        int(subcell.GetPointId(point_id))
                        for point_id in range(subcell.GetNumberOfPoints())
                    )
                    metadata[key] = (int(subcell.GetCellType()), point_ids)

        self._surface_boundary_map = {
            key: metadata[key] for key, count in counts.items() if count == 1
        }
        return self._surface_boundary_map

    def _surface_keys_from_top_cells(self, cell_ids):
        dataset = self.working_dataset
        if dataset is None:
            return set()

        boundary_map = self._surface_boundary_map_for_top_cells()
        top_dim = self._top_dimension()
        if top_dim < 2:
            return set()

        keys = set()
        top_cell_ids = set()
        existing_keys = self._existing_codim_keys(top_dim - 1)

        for item in (cell_ids or []):
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                try:
                    key = tuple(sorted(int(value) for value in item))
                except (TypeError, ValueError):
                    continue
                if key in boundary_map or key in existing_keys:
                    keys.add(key)
                continue

            if not isinstance(item, (int, float)):
                continue
            cell_id = int(item)
            if cell_id < 0 or cell_id >= dataset.GetNumberOfCells():
                continue

            cell = dataset.GetCell(cell_id)
            cell_dim = cell.GetCellDimension()
            if cell_dim == top_dim - 1:
                keys.add(self._cell_key(cell))
            elif cell_dim == top_dim:
                top_cell_ids.add(cell_id)

        for cell_id in top_cell_ids:
            cell = dataset.GetCell(int(cell_id))
            if top_dim == 3:
                subcell_count = cell.GetNumberOfFaces()
                getter = cell.GetFace
            else:
                subcell_count = cell.GetNumberOfEdges()
                getter = cell.GetEdge
            for subcell_id in range(subcell_count):
                key = self._cell_key(getter(subcell_id))
                if key in boundary_map:
                    keys.add(key)
        return keys

    def _existing_codim_keys(self, codim_dimension):
        dataset = self.working_dataset
        if dataset is None:
            return set()
        keys = set()
        for cell_id in range(dataset.GetNumberOfCells()):
            cell = dataset.GetCell(cell_id)
            if cell.GetCellDimension() != codim_dimension:
                continue
            keys.add(self._cell_key(cell))
        return keys

    def _build_surface_dataset(self, surface_keys):
        dataset = self.working_dataset
        if dataset is None:
            return None
        boundary_map = self._surface_boundary_map_for_top_cells()
        if not boundary_map:
            return None

        selected = [key for key in sorted(surface_keys) if key in boundary_map]
        if not selected:
            return None

        output = vtkUnstructuredGrid()
        output.SetPoints(dataset.GetPoints())
        for key in selected:
            cell_type, point_ids = boundary_map[key]
            id_list = vtkIdList()
            for point_id in point_ids:
                id_list.InsertNextId(int(point_id))
            output.InsertNextCell(int(cell_type), id_list)
        return output

    def _invalidate_geometry_caches(self):
        self._volume_adjacency = None
        self._surface_boundary_map = None

    @staticmethod
    def _extend_cell_data_for_new_cells(dataset, old_cell_count):
        """Resize existing cell-data arrays after appending new cells."""
        new_cell_count = dataset.GetNumberOfCells()
        if new_cell_count <= old_cell_count:
            return

        cell_data = dataset.GetCellData()
        for array_index in range(cell_data.GetNumberOfArrays()):
            array = cell_data.GetArray(array_index)
            if array is None:
                continue

            components = max(int(array.GetNumberOfComponents()), 1)
            array.SetNumberOfTuples(new_cell_count)
            for cell_id in range(old_cell_count, new_cell_count):
                for component in range(components):
                    try:
                        array.SetComponent(cell_id, component, 0.0)
                    except Exception:
                        # Best effort: keep tuple resize even if component assignment is unsupported.
                        break

    def _ensure_volume_adjacency(self):
        """Build and cache a face/edge adjacency graph for top-dimensional cells."""
        if self._volume_adjacency is not None:
            return self._volume_adjacency

        dataset = self.working_dataset
        if dataset is None:
            self._volume_adjacency = {}
            return self._volume_adjacency

        cell_count = dataset.GetNumberOfCells()
        max_dimension = max(
            (dataset.GetCell(cell_id).GetCellDimension() for cell_id in range(cell_count)),
            default=0,
        )
        shared_subcells = {}
        adjacency = {cell_id: set() for cell_id in range(cell_count)}

        for cell_id in range(cell_count):
            cell = dataset.GetCell(cell_id)
            if cell.GetCellDimension() != max_dimension:
                continue

            if max_dimension == 3:
                num_subcells = cell.GetNumberOfFaces()
                getter = cell.GetFace
            elif max_dimension == 2:
                num_subcells = cell.GetNumberOfEdges()
                getter = cell.GetEdge
            elif max_dimension == 1:
                num_subcells = cell.GetNumberOfPoints()
                getter = lambda idx, c=cell: c.GetPointId(idx)
            else:
                continue

            for subcell_id in range(num_subcells):
                if max_dimension == 1:
                    key = (int(getter(subcell_id)),)
                else:
                    subcell = getter(subcell_id)
                    key = tuple(
                        sorted(
                            int(subcell.GetPointId(point_id))
                            for point_id in range(subcell.GetNumberOfPoints())
                        )
                    )
                shared_subcells.setdefault(key, []).append(cell_id)

        for touching_cells in shared_subcells.values():
            if len(touching_cells) < 2:
                continue
            for source in touching_cells:
                adjacency[source].update(
                    target for target in touching_cells if target != source
                )

        self._volume_adjacency = adjacency
        return self._volume_adjacency

    def _ensure_cell_centers_array(self):
        """Ensure the working dataset exposes ``CellCenters`` in cell data."""
        if self.working_dataset is None:
            return

        cell_data = self.working_dataset.GetCellData()
        if cell_data.GetArray("CellCenters") is not None:
            return

        array = vtkDoubleArray()
        array.SetName("CellCenters")
        array.SetNumberOfComponents(3)
        array.SetNumberOfTuples(self.working_dataset.GetNumberOfCells())

        centers = vtkCellCenters()
        centers.SetInputData(self.working_dataset)
        centers.Update()
        center_points = centers.GetOutput().GetPoints()

        for cell_id in range(self.working_dataset.GetNumberOfCells()):
            center = center_points.GetPoint(cell_id)
            array.SetTuple3(cell_id, center[0], center[1], center[2])

        cell_data.AddArray(array)
        self.working_dataset.Modified()

    @staticmethod
    def is_supported_dataset(dataset):
        """Return True when the dataset type is currently editable."""
        return isinstance(dataset, vtkUnstructuredGrid)
