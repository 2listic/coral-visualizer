"""Edit-session scaffolding for the ParaView-backed workflow."""

from __future__ import annotations

from pathlib import Path
from math import acos, degrees, sqrt
from typing import TypedDict

from vtkmodules.vtkCommonCore import vtkDoubleArray, vtkIdList
from vtkmodules.vtkCommonDataModel import vtkUnstructuredGrid, vtkVertex
from vtkmodules.vtkFiltersCore import (
    vtkArrayCalculator,
    vtkCellCenters,
    vtkExtractCells,
)
from vtkmodules.vtkIOLegacy import vtkUnstructuredGridWriter
from vtkmodules.vtkIOXML import vtkXMLUnstructuredGridWriter

from vtk_metadata import strip_data_array_information_keys


class EditSessionSource(TypedDict):
    node_id: str
    label: str
    filename: str
    dataset: vtkUnstructuredGrid


class EditSession:
    """Owns the temporary editable dataset derived from the active pipeline node."""

    def __init__(self):
        self.active: bool = False
        self.source_node_id: str | None = None
        self.source_label: str = ""
        self.source_filename: str = ""
        self.working_dataset: vtkUnstructuredGrid | None = (
            None  # DeepCopy of source, mutation target — see docs/logic_flows.md §5b
        )
        self.dirty: bool = False
        self.geometry_mode: str = "volume"
        self.field_name: str = ""
        self.expression: str = ""
        self.default_value: str = "0"
        self.selected_cell_ids: set[int] = set()
        self.selected_surface_keys: set[tuple[int, ...]] = set()
        self.selected_point_ids: set[int] = set()
        self._volume_adjacency: dict[int, set[int]] | None = None
        self._surface_boundary_map: dict[tuple[int, ...], tuple] | None = None
        self._existing_codim_keys_cache: dict[int, set[tuple[int, ...]]] = {}
        self._surface_adjacency: dict[tuple[int, ...], set[tuple[int, ...]]] | None = (
            None
        )
        self._surface_element_vectors: (
            dict[tuple[int, ...], tuple[float, float, float]] | None
        ) = None

    def clear(self) -> None:
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
        self.selected_point_ids = set()
        self._volume_adjacency = None
        self._surface_boundary_map = None
        self._existing_codim_keys_cache = {}
        self._surface_adjacency = None
        self._surface_element_vectors = None

    def begin(
        self,
        node_id: str,
        source_label: str,
        source_filename: str,
        dataset: vtkUnstructuredGrid,
    ) -> None:
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
        self.field_name = ""
        self.expression = ""
        self.default_value = "0"
        self.selected_cell_ids = set()
        self.selected_surface_keys = set()
        self.selected_point_ids = set()
        self._volume_adjacency = None
        self._surface_boundary_map = None
        self._existing_codim_keys_cache = {}
        self._surface_adjacency = None
        self._surface_element_vectors = None
        self._ensure_cell_centers_array()

    def default_output_filename(self) -> str:
        """Return a suggested filename for the current edit-session output."""
        label = (
            self.source_label or Path(self.source_filename or "edited").stem or "edited"
        )
        safe_label = "".join(
            char if char.isalnum() or char in {"-", "_"} else "_" for char in label
        ).strip("_")
        if not safe_label:
            safe_label = "edited"
        if not safe_label.endswith("_edited"):
            safe_label = f"{safe_label}_edited"
        return safe_label + ".vtu"

    def save(self, output_path: str | Path) -> str:
        """Persist the working dataset to disk."""
        if not self.active or self.working_dataset is None:
            raise RuntimeError("No active edit session to save")

        if self.geometry_mode == "surface":
            self.materialize_surface_selection()
        self._remove_internal_edit_arrays()

        suffix = Path(output_path).suffix.lower()
        if suffix == ".vtk":
            writer = vtkUnstructuredGridWriter()
        elif suffix == ".vtu":
            writer = vtkXMLUnstructuredGridWriter()
        else:
            raise ValueError(
                "Unsupported edit output format. Use .vtu or .vtk for edit-session saves."
            )
        strip_data_array_information_keys(self.working_dataset)
        writer.SetFileName(str(output_path))
        writer.SetInputData(self.working_dataset)
        if writer.Write() != 1:
            raise RuntimeError(f"Failed to write edited dataset to {output_path}")
        return str(output_path)

    def available_cell_variables(self) -> list[str]:
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

    def available_point_variables(self) -> list[str]:
        """Return point-data variable names available to the edit calculator."""
        if not self.active or self.working_dataset is None:
            return []
        point_data = self.working_dataset.GetPointData()
        return [
            point_data.GetArrayName(i)
            for i in range(point_data.GetNumberOfArrays())
            if point_data.GetArrayName(i)
        ]

    def available_fields(self) -> list[dict[str, str]]:
        """Return both point and cell scalar/vector arrays for field selection."""
        fields = []
        for name in self.available_cell_variables():
            fields.append({"text": f"{name} (Cell)", "value": f"cell:{name}"})
        for name in self.available_point_variables():
            fields.append({"text": f"{name} (Point)", "value": f"point:{name}"})
        fields.sort(key=lambda item: item["text"].lower())
        return fields

    def has_cell_field(self, field_name: str) -> bool:
        """Return True when a cell-data field with ``field_name`` already exists."""
        if not self.active or self.working_dataset is None:
            return False
        name = (field_name or "").strip()
        if not name:
            return False
        return self.working_dataset.GetCellData().GetArray(name) is not None

    def has_field(self, field_name: str, association: str) -> bool:
        """Return True when the requested data array already exists."""
        array = self._get_data_array((field_name or "").strip(), association)
        return array is not None

    def infer_field_association(self, field_name: str) -> str | None:
        """Best-effort association lookup for an existing field name."""
        name = (field_name or "").strip()
        if not name or not self.active or self.working_dataset is None:
            return None
        if self.working_dataset.GetCellData().GetArray(name) is not None:
            return "cell"
        if self.working_dataset.GetPointData().GetArray(name) is not None:
            return "point"
        return None

    def selected_count(self) -> int:
        """Return the number of currently selected cells."""
        if self.geometry_mode == "surface":
            return len(self.selected_surface_keys)
        if self.geometry_mode == "point":
            return len(self.selected_point_ids)
        return len(self.selected_cell_ids)

    def clear_selection(self) -> None:
        """Drop the current volume-cell selection."""
        self.selected_cell_ids.clear()
        self.selected_surface_keys.clear()
        self.selected_point_ids.clear()

    def select_all_cells(self) -> int:
        """Select every cell in the working dataset."""
        if not self.active or self.working_dataset is None:
            return 0
        if self.geometry_mode == "point":
            self.selected_point_ids = set(
                range(self.working_dataset.GetNumberOfPoints())
            )
            return len(self.selected_point_ids)
        if self.geometry_mode == "surface":
            self.selected_surface_keys = set(self._surface_boundary_map_for_top_cells())
            return len(self.selected_surface_keys)
        self.selected_cell_ids = set(range(self.working_dataset.GetNumberOfCells()))
        return len(self.selected_cell_ids)

    def toggle_cell_selection(
        self,
        cell_id: int | float | tuple[int, ...],
        grow: bool = False,
        angle_threshold: float | None = None,
    ) -> int:
        """Toggle a single picked cell, optionally growing by adjacency."""
        if not self.active or self.working_dataset is None:
            return 0

        if self.geometry_mode == "point":
            try:
                point_id = int(cell_id)
            except (TypeError, ValueError):
                return len(self.selected_point_ids)
            if point_id < 0 or point_id >= self.working_dataset.GetNumberOfPoints():
                return len(self.selected_point_ids)
            if point_id in self.selected_point_ids:
                self.selected_point_ids.discard(point_id)
            else:
                self.selected_point_ids.add(point_id)
            return len(self.selected_point_ids)

        if self.geometry_mode == "surface":
            surface_keys = self._surface_keys_from_top_cells([cell_id])
            if grow:
                surface_keys = self._grow_surface_selection(
                    surface_keys, angle_threshold=angle_threshold
                )
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

    def replace_selection(
        self, cell_ids: list, grow: bool = False, angle_threshold: float | None = None
    ) -> int:
        """Replace the current selection with the provided cell IDs."""
        if not self.active or self.working_dataset is None:
            return 0

        if self.geometry_mode == "point":
            point_count = self.working_dataset.GetNumberOfPoints()
            self.selected_point_ids = {
                int(point_id)
                for point_id in (cell_ids or [])
                if isinstance(point_id, (int, float))
                and 0 <= int(point_id) < point_count
            }
            return len(self.selected_point_ids)

        if self.geometry_mode == "surface":
            selected = self._surface_keys_from_top_cells(cell_ids)
            if grow:
                selected = self._grow_surface_selection(
                    selected, angle_threshold=angle_threshold
                )
            self.selected_surface_keys = selected
            return len(self.selected_surface_keys)

        normalized = {
            int(cell_id)
            for cell_id in (cell_ids or [])
            if isinstance(cell_id, (int, float))
            and 0 <= int(cell_id) < self.working_dataset.GetNumberOfCells()
        }
        if grow:
            normalized = self._grow_volume_selection(normalized)
        self.selected_cell_ids = normalized
        return len(self.selected_cell_ids)

    def add_selection(
        self, cell_ids: list, grow: bool = False, angle_threshold: float | None = None
    ) -> int:
        """Union the provided cell IDs into the current selection."""
        if not self.active or self.working_dataset is None:
            return 0

        if self.geometry_mode == "point":
            point_count = self.working_dataset.GetNumberOfPoints()
            selected = {
                int(point_id)
                for point_id in (cell_ids or [])
                if isinstance(point_id, (int, float))
                and 0 <= int(point_id) < point_count
            }
            self.selected_point_ids |= selected
            return len(self.selected_point_ids)

        if self.geometry_mode == "surface":
            selected = self._surface_keys_from_top_cells(cell_ids)
            if grow:
                selected = self._grow_surface_selection(
                    selected, angle_threshold=angle_threshold
                )
            self.selected_surface_keys |= selected
            return len(self.selected_surface_keys)

        normalized = {
            int(cell_id)
            for cell_id in (cell_ids or [])
            if isinstance(cell_id, (int, float))
            and 0 <= int(cell_id) < self.working_dataset.GetNumberOfCells()
        }
        if grow:
            normalized = self._grow_volume_selection(normalized)
        self.selected_cell_ids |= normalized
        return len(self.selected_cell_ids)

    def subtract_selection(
        self, cell_ids: list, grow: bool = False, angle_threshold: float | None = None
    ) -> int:
        """Remove the provided cell IDs from the current selection."""
        if not self.active or self.working_dataset is None:
            return 0

        if self.geometry_mode == "point":
            point_count = self.working_dataset.GetNumberOfPoints()
            selected = {
                int(point_id)
                for point_id in (cell_ids or [])
                if isinstance(point_id, (int, float))
                and 0 <= int(point_id) < point_count
            }
            self.selected_point_ids -= selected
            return len(self.selected_point_ids)

        if self.geometry_mode == "surface":
            selected = self._surface_keys_from_top_cells(cell_ids)
            if grow:
                selected = self._grow_surface_selection(
                    selected, angle_threshold=angle_threshold
                )
            self.selected_surface_keys -= selected
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

    def flip_selection(
        self, cell_ids: list, grow: bool = False, angle_threshold: float | None = None
    ) -> int:
        """Toggle the provided cell IDs against the current selection."""
        if not self.active or self.working_dataset is None:
            return 0

        if self.geometry_mode == "point":
            point_count = self.working_dataset.GetNumberOfPoints()
            normalized = {
                int(point_id)
                for point_id in (cell_ids or [])
                if isinstance(point_id, (int, float))
                and 0 <= int(point_id) < point_count
            }
            for point_id in normalized:
                if point_id in self.selected_point_ids:
                    self.selected_point_ids.discard(point_id)
                else:
                    self.selected_point_ids.add(point_id)
            return len(self.selected_point_ids)

        if self.geometry_mode == "surface":
            selected = self._surface_keys_from_top_cells(cell_ids)
            if grow:
                selected = self._grow_surface_selection(
                    selected, angle_threshold=angle_threshold
                )
            for key in selected:
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

    def create_field(
        self,
        field_name: str,
        association: str,
        default_value: float | str,
        overwrite: bool = False,
    ) -> str:
        """Create a scalar field across all tuples in the chosen association."""
        if not self.active or self.working_dataset is None:
            raise RuntimeError("No active edit session")

        field_name = (field_name or "").strip()
        if not field_name:
            raise ValueError("Field name is required")
        association = self._normalize_association(association)
        target_data = self._dataset_data_for_association(association)
        tuple_count = self._tuple_count_for_association(association)
        if tuple_count <= 0:
            raise RuntimeError("The working dataset has no editable tuples")

        default_numeric = float(default_value)
        existing = target_data.GetArray(field_name)
        if existing is not None and not overwrite:
            raise RuntimeError(
                f"Field '{field_name}' already exists. Confirm overwrite to replace it."
            )
        if existing is not None:
            target_data.RemoveArray(field_name)

        target = vtkDoubleArray()
        target.SetName(field_name)
        target.SetNumberOfComponents(1)
        target.SetNumberOfTuples(tuple_count)
        for idx in range(tuple_count):
            target.SetValue(idx, default_numeric)
        target_data.AddArray(target)
        target_data.SetActiveScalars(field_name)
        self.working_dataset.Modified()
        self.field_name = field_name
        self.default_value = str(default_value)
        self.dirty = True
        return field_name

    def assign_to_selected(
        self, field_name: str, association: str, expression: str
    ) -> str:
        """Assign the expression value to selected entities in the target field."""
        if not self.active or self.working_dataset is None:
            raise RuntimeError("No active edit session")
        field_name = (field_name or "").strip()
        if not field_name:
            raise ValueError("Field name is required")
        expression = (expression or "").strip()
        if not expression:
            raise ValueError("A value or calculator expression is required")
        association = self._normalize_association(association)

        target_data = self._dataset_data_for_association(association)
        existing = target_data.GetArray(field_name)
        if existing is None:
            raise RuntimeError(f"Field '{field_name}' does not exist. Create it first.")
        if existing.GetNumberOfComponents() != 1:
            raise RuntimeError("Only scalar fields can be assigned in edit mode.")

        selected_ids = self._selected_ids_for_association(association)
        if not selected_ids:
            raise RuntimeError("No selected entities to assign.")

        computed = self._evaluate_expression(association, expression)
        tuple_count = self._tuple_count_for_association(association)
        for idx in selected_ids:
            if 0 <= idx < tuple_count:
                existing.SetComponent(int(idx), 0, float(computed[int(idx)]))

        target_data.SetActiveScalars(field_name)
        self.working_dataset.Modified()
        self.field_name = field_name
        self.expression = expression
        self.dirty = True
        return field_name

    def _evaluate_expression(self, association, expression):
        """Evaluate expression and return one scalar value per tuple."""
        association = self._normalize_association(association)
        dataset = self.working_dataset
        tuple_count = self._tuple_count_for_association(association)
        values = [0.0] * tuple_count

        calculator = vtkArrayCalculator()
        calculator.SetInputData(dataset)
        if association == "point":
            calculator.SetAttributeTypeToPointData()
            source_data = dataset.GetPointData()
        else:
            self._ensure_cell_centers_array()
            calculator.SetAttributeTypeToCellData()
            source_data = dataset.GetCellData()

        calculator.SetResultArrayName("__edit_result__")
        for index in range(source_data.GetNumberOfArrays()):
            array = source_data.GetArray(index)
            name = source_data.GetArrayName(index)
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
        if association == "point":
            result_array = output.GetPointData().GetArray("__edit_result__")
        else:
            result_array = output.GetCellData().GetArray("__edit_result__")
        if result_array is None:
            raise RuntimeError(
                "Calculator did not produce a result array for the current expression."
            )
        if result_array.GetNumberOfComponents() != 1:
            raise RuntimeError("Only scalar edit fields are supported.")
        for idx in range(tuple_count):
            values[idx] = float(result_array.GetTuple1(idx))
        return values

    def build_selected_volume_dataset(self) -> vtkUnstructuredGrid | None:
        """Return a lightweight dataset containing the currently selected cells."""
        return self.build_selected_dataset()

    def build_selected_dataset(self) -> vtkUnstructuredGrid | None:
        """Return a lightweight dataset containing currently selected editable entities."""
        if not self.active or self.working_dataset is None:
            return None

        if self.geometry_mode == "surface":
            if not self.selected_surface_keys:
                return None
            return self._build_surface_dataset(self.selected_surface_keys)

        if self.geometry_mode == "point":
            if not self.selected_point_ids:
                return None
            output = vtkUnstructuredGrid()
            output.SetPoints(self.working_dataset.GetPoints())
            for point_id in sorted(self.selected_point_ids):
                vertex = vtkVertex()
                vertex.GetPointIds().SetId(0, int(point_id))
                output.InsertNextCell(vertex.GetCellType(), vertex.GetPointIds())
            return output

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

    def materialize_surface_selection(self) -> int:
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

        self._remove_internal_edit_arrays()
        boundary_map = self._surface_boundary_map_for_top_cells()
        existing = self._existing_codim_keys(top_dim - 1)
        missing_keys = [
            key
            for key in sorted(self.selected_surface_keys)
            if key in boundary_map and key not in existing
        ]
        if not missing_keys:
            return 0

        old_cell_count = dataset.GetNumberOfCells()
        owner_cell_ids = {}
        for key in missing_keys:
            cell_type, point_ids, owner_cell_id = boundary_map[key]
            id_list = vtkIdList()
            for point_id in point_ids:
                id_list.InsertNextId(int(point_id))
            dataset.InsertNextCell(int(cell_type), id_list)
            owner_cell_ids[dataset.GetNumberOfCells() - 1] = int(owner_cell_id)

        self._extend_cell_data_for_new_cells(dataset, old_cell_count, owner_cell_ids)

        dataset.Modified()
        self.dirty = True
        self._invalidate_geometry_caches()
        return len(missing_keys)

    @staticmethod
    def _normalize_association(association: str) -> str:
        value = (association or "cell").strip().lower()
        if value not in {"cell", "point"}:
            raise ValueError("Field association must be 'cell' or 'point'")
        return value

    def _dataset_data_for_association(self, association):
        association = self._normalize_association(association)
        return (
            self.working_dataset.GetPointData()
            if association == "point"
            else self.working_dataset.GetCellData()
        )

    def _tuple_count_for_association(self, association: str) -> int:
        association = self._normalize_association(association)
        if association == "point":
            return self.working_dataset.GetNumberOfPoints()
        return self.working_dataset.GetNumberOfCells()

    def _get_data_array(self, field_name, association):
        if not self.active or self.working_dataset is None:
            return None
        name = (field_name or "").strip()
        if not name:
            return None
        target_data = self._dataset_data_for_association(association)
        return target_data.GetArray(name)

    def _selected_ids_for_association(self, association):
        association = self._normalize_association(association)
        if association == "point":
            return sorted(int(point_id) for point_id in self.selected_point_ids)

        if self.geometry_mode == "surface":
            self.materialize_surface_selection()
            return sorted(self._selected_surface_cell_ids())
        return sorted(int(cell_id) for cell_id in self.selected_cell_ids)

    def _grow_volume_selection(self, seed_ids) -> set[int]:
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

    def _grow_surface_selection(
        self, seed_keys, angle_threshold: float | None = None
    ) -> set[tuple[int, ...]]:
        """Expand surface keys transitively while respecting neighbor-angle threshold."""
        seeds = {tuple(key) for key in (seed_keys or [])}
        if not seeds:
            return set()

        adjacency = self._ensure_surface_adjacency()
        threshold = self._normalized_angle_threshold(angle_threshold)
        grown = set(seeds)
        pending = list(seeds)

        while pending:
            key = pending.pop()
            for neighbor in adjacency.get(key, set()):
                if neighbor in grown:
                    continue
                if threshold is not None:
                    angle = self._surface_neighbor_angle_degrees(key, neighbor)
                    if angle > threshold:
                        continue
                grown.add(neighbor)
                pending.append(neighbor)
        return grown

    def _top_dimension(self) -> int:
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
            sorted(
                int(cell.GetPointId(point_id))
                for point_id in range(cell.GetNumberOfPoints())
            )
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
                    metadata[key] = (
                        int(subcell.GetCellType()),
                        point_ids,
                        int(cell_id),
                    )

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
        existing_keys = None

        for item in cell_ids or []:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                try:
                    key = tuple(sorted(int(value) for value in item))
                except (TypeError, ValueError):
                    continue
                if key in boundary_map:
                    keys.add(key)
                    continue
                if existing_keys is None:
                    existing_keys = self._existing_codim_keys(top_dim - 1)
                if key in existing_keys:
                    keys.add(key)
                    continue
                # Native ParaView surface picks may already provide canonical
                # boundary-like keys even when local topology checks diverge.
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
        cached = self._existing_codim_keys_cache.get(codim_dimension)
        if cached is not None:
            return cached

        dataset = self.working_dataset
        if dataset is None:
            return set()
        keys = set()
        for cell_id in range(dataset.GetNumberOfCells()):
            cell = dataset.GetCell(cell_id)
            if cell.GetCellDimension() != codim_dimension:
                continue
            keys.add(self._cell_key(cell))
        self._existing_codim_keys_cache[codim_dimension] = keys
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
            cell_type, point_ids, _owner_cell_id = boundary_map[key]
            id_list = vtkIdList()
            for point_id in point_ids:
                id_list.InsertNextId(int(point_id))
            output.InsertNextCell(int(cell_type), id_list)
        return output

    def _selected_surface_cell_ids(self):
        """Return ids of codim-1 cells matching selected surface keys."""
        dataset = self.working_dataset
        if dataset is None:
            return set()

        top_dim = self._top_dimension()
        if top_dim < 2:
            return set()
        codim_dim = top_dim - 1

        key_to_ids = {}
        for cell_id in range(dataset.GetNumberOfCells()):
            cell = dataset.GetCell(cell_id)
            if cell.GetCellDimension() != codim_dim:
                continue
            key = self._cell_key(cell)
            key_to_ids.setdefault(key, set()).add(int(cell_id))

        selected_ids = set()
        for key in self.selected_surface_keys:
            selected_ids |= key_to_ids.get(tuple(key), set())
        return selected_ids

    def _invalidate_geometry_caches(self):
        self._volume_adjacency = None
        self._surface_boundary_map = None
        self._existing_codim_keys_cache = {}
        self._surface_adjacency = None
        self._surface_element_vectors = None

    def _ensure_surface_adjacency(self) -> dict[tuple[int, ...], set[tuple[int, ...]]]:
        """Build and cache codim-1 adjacency graph for surface-mode grow selection."""
        if self._surface_adjacency is not None:
            return self._surface_adjacency

        dataset = self.working_dataset
        if dataset is None:
            self._surface_adjacency = {}
            return self._surface_adjacency

        top_dim = self._top_dimension()
        if top_dim < 2:
            self._surface_adjacency = {}
            return self._surface_adjacency
        codim_dim = top_dim - 1

        selectable_keys = set(self._surface_boundary_map_for_top_cells().keys())
        selectable_keys |= self._existing_codim_keys(codim_dim)
        adjacency = {tuple(key): set() for key in selectable_keys}
        if not selectable_keys:
            self._surface_adjacency = adjacency
            return self._surface_adjacency

        # Faces in 3D are adjacent by shared edge (2 vertices), edges in 2D by shared point (1 vertex).
        min_shared = max(1, codim_dim)
        point_to_keys = {}
        for key in selectable_keys:
            normalized = tuple(key)
            for point_id in normalized:
                point_to_keys.setdefault(int(point_id), set()).add(normalized)

        for key in selectable_keys:
            normalized = tuple(key)
            candidates = set()
            for point_id in normalized:
                candidates |= point_to_keys.get(int(point_id), set())
            candidates.discard(normalized)
            for candidate in candidates:
                if len(set(normalized).intersection(candidate)) >= min_shared:
                    adjacency[normalized].add(candidate)

        self._surface_adjacency = adjacency
        return self._surface_adjacency

    @staticmethod
    def _normalized_angle_threshold(angle_threshold) -> float | None:
        if angle_threshold is None:
            return None
        try:
            threshold = float(angle_threshold)
        except (TypeError, ValueError):
            return None
        if threshold < 0.0:
            return 0.0
        if threshold > 180.0:
            return 180.0
        return threshold

    def _surface_neighbor_angle_degrees(
        self, key_a: tuple[int, ...], key_b: tuple[int, ...]
    ) -> float:
        """Return angle between surface element directions in degrees."""
        vectors = self._ensure_surface_element_vectors()
        va = vectors.get(tuple(key_a))
        vb = vectors.get(tuple(key_b))
        if va is None or vb is None:
            return 180.0
        dot = va[0] * vb[0] + va[1] * vb[1] + va[2] * vb[2]
        dot = max(-1.0, min(1.0, abs(dot)))
        return degrees(acos(dot))

    def _ensure_surface_element_vectors(
        self,
    ) -> dict[tuple[int, ...], tuple[float, float, float]]:
        """Build and cache representative unit vectors for selectable surface elements."""
        if self._surface_element_vectors is not None:
            return self._surface_element_vectors

        dataset = self.working_dataset
        if dataset is None:
            self._surface_element_vectors = {}
            return self._surface_element_vectors

        top_dim = self._top_dimension()
        if top_dim < 2:
            self._surface_element_vectors = {}
            return self._surface_element_vectors
        codim_dim = top_dim - 1

        selectable_keys = set(self._surface_boundary_map_for_top_cells().keys())
        selectable_keys |= self._existing_codim_keys(codim_dim)

        vectors = {}
        for key in selectable_keys:
            point_ids = [int(point_id) for point_id in key]
            points = [dataset.GetPoint(point_id) for point_id in point_ids]
            vector = self._surface_element_vector(points)
            if vector is not None:
                vectors[tuple(key)] = vector

        self._surface_element_vectors = vectors
        return self._surface_element_vectors

    @staticmethod
    def _surface_element_vector(points):
        """Return a unit normal (faces) or tangent (edges) vector for a surface element."""
        if not points:
            return None
        if len(points) == 1:
            return None
        if len(points) == 2:
            dx = points[1][0] - points[0][0]
            dy = points[1][1] - points[0][1]
            dz = points[1][2] - points[0][2]
            norm = sqrt(dx * dx + dy * dy + dz * dz)
            if norm <= 1e-12:
                return None
            return (dx / norm, dy / norm, dz / norm)

        p0 = points[0]
        for i in range(1, len(points) - 1):
            p1 = points[i]
            p2 = points[i + 1]
            ux = p1[0] - p0[0]
            uy = p1[1] - p0[1]
            uz = p1[2] - p0[2]
            vx = p2[0] - p0[0]
            vy = p2[1] - p0[1]
            vz = p2[2] - p0[2]
            nx = uy * vz - uz * vy
            ny = uz * vx - ux * vz
            nz = ux * vy - uy * vx
            norm = sqrt(nx * nx + ny * ny + nz * nz)
            if norm > 1e-12:
                return (nx / norm, ny / norm, nz / norm)
        return None

    @staticmethod
    def _extend_cell_data_for_new_cells(dataset, old_cell_count, owner_cell_ids=None):
        """Resize cell-data arrays after appending cells and inherit owner tuples."""
        new_cell_count = dataset.GetNumberOfCells()
        if new_cell_count <= old_cell_count:
            return

        owner_cell_ids = owner_cell_ids or {}
        cell_data = dataset.GetCellData()
        for array_index in range(cell_data.GetNumberOfArrays()):
            array = cell_data.GetArray(array_index)
            if array is None:
                continue

            components = max(int(array.GetNumberOfComponents()), 1)
            original_tuples = [
                array.GetTuple(cell_id)
                for cell_id in range(min(old_cell_count, array.GetNumberOfTuples()))
            ]
            array.SetNumberOfTuples(new_cell_count)
            for cell_id, values in enumerate(original_tuples):
                try:
                    array.SetTuple(cell_id, values)
                except Exception:
                    for component, value in enumerate(values[:components]):
                        array.SetComponent(cell_id, component, value)
            for cell_id in range(old_cell_count, new_cell_count):
                owner_cell_id = owner_cell_ids.get(cell_id)
                if owner_cell_id is not None and 0 <= owner_cell_id < len(
                    original_tuples
                ):
                    try:
                        array.SetTuple(cell_id, original_tuples[owner_cell_id])
                        continue
                    except Exception:
                        pass
                for component in range(components):
                    try:
                        array.SetComponent(cell_id, component, 0.0)
                    except Exception:
                        # Best effort: keep tuple resize even if component assignment is unsupported.
                        break

    def _ensure_volume_adjacency(self) -> dict[int, set[int]]:
        """Build and cache a face/edge adjacency graph for top-dimensional cells."""
        if self._volume_adjacency is not None:
            return self._volume_adjacency

        dataset = self.working_dataset
        if dataset is None:
            self._volume_adjacency = {}
            return self._volume_adjacency

        cell_count = dataset.GetNumberOfCells()
        max_dimension = max(
            (
                dataset.GetCell(cell_id).GetCellDimension()
                for cell_id in range(cell_count)
            ),
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

                def getter(idx, _cell=cell):
                    return _cell.GetPointId(idx)

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

    def _ensure_cell_centers_array(self) -> None:
        """Ensure the working dataset exposes ``CellCenters`` in cell data."""
        if self.working_dataset is None:
            return

        cell_data = self.working_dataset.GetCellData()
        existing = cell_data.GetArray("CellCenters")
        if (
            existing is not None
            and existing.GetNumberOfComponents() == 3
            and existing.GetNumberOfTuples() == self.working_dataset.GetNumberOfCells()
        ):
            return
        if existing is not None:
            cell_data.RemoveArray("CellCenters")

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

    def _remove_internal_edit_arrays(self) -> None:
        """Drop edit-only helper arrays before persisting user data."""
        if self.working_dataset is None:
            return
        cell_data = self.working_dataset.GetCellData()
        if cell_data.GetArray("CellCenters") is not None:
            cell_data.RemoveArray("CellCenters")
            self.working_dataset.Modified()

    @staticmethod
    def is_supported_dataset(dataset) -> bool:
        """Return True when the dataset type is currently editable."""
        return isinstance(dataset, vtkUnstructuredGrid)

    @staticmethod
    def is_supported_dataset_type(type_string: str) -> bool:
        """Return True when a DataInformation type string is currently editable.

        Used for the cheap probe in can_edit_active_node() — avoids a Fetch.
        """
        return type_string == "vtkUnstructuredGrid"
