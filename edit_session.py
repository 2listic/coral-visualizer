"""Edit-session scaffolding for the ParaView-backed workflow."""

from pathlib import Path

from vtkmodules.vtkCommonCore import vtkDoubleArray, vtkIdList
from vtkmodules.vtkCommonDataModel import vtkUnstructuredGrid
from vtkmodules.vtkFiltersCore import vtkArrayCalculator, vtkCellCenters, vtkExtractCells
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
        self._volume_adjacency = None

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
        self._volume_adjacency = None

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
        self._volume_adjacency = None
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

        writer = vtkXMLUnstructuredGridWriter()
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

    def selected_count(self):
        """Return the number of currently selected cells."""
        return len(self.selected_cell_ids)

    def clear_selection(self):
        """Drop the current volume-cell selection."""
        self.selected_cell_ids.clear()

    def select_all_cells(self):
        """Select every cell in the working dataset."""
        if not self.active or self.working_dataset is None:
            return 0
        self.selected_cell_ids = set(range(self.working_dataset.GetNumberOfCells()))
        return len(self.selected_cell_ids)

    def toggle_cell_selection(self, cell_id, grow=False):
        """Toggle a single picked cell, optionally growing by adjacency."""
        if not self.active or self.working_dataset is None:
            return 0

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

        normalized = {
            int(cell_id)
            for cell_id in (cell_ids or [])
            if isinstance(cell_id, (int, float)) and 0 <= int(cell_id) < self.working_dataset.GetNumberOfCells()
        }
        if grow:
            normalized = self._grow_volume_selection(normalized)
        self.selected_cell_ids |= normalized
        return len(self.selected_cell_ids)

    def apply_volume_field(self, field_name, expression, default_value):
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

        target = dataset.GetCellData().GetArray(field_name)
        if target is None:
            target = vtkDoubleArray()
            target.SetName(field_name)
            target.SetNumberOfComponents(1)
            target.SetNumberOfTuples(cell_count)
            dataset.GetCellData().AddArray(target)
        elif target.GetNumberOfComponents() != 1:
            raise RuntimeError(
                f"Existing field '{field_name}' is not scalar and cannot be overwritten in Volume mode."
            )
        else:
            target.SetNumberOfTuples(cell_count)

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
        if (
            not self.active
            or self.working_dataset is None
            or not self.selected_cell_ids
        ):
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
