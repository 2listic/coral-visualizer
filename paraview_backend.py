"""ParaView backend adapter for the Trame visualizer."""

from __future__ import annotations

import bisect
import importlib.util
import os
import time
from math import isfinite
from typing import Any, TypedDict

from constants import ARRAY_SOLID, CELL_PREFIX, MATERIAL_ID_ARRAY, POINT_PREFIX
from diagnostics import debug_log
from edit_session import EditSession
from paraview_filter_catalog import ParaViewFilterCatalog, SUPPORTED_FILTERS
from paraview_property_inspector import ParaViewPropertyInspector
from vtk_metadata import sanitized_vtk_xml_path, strip_data_array_information_keys

try:
    from vtkmodules.vtkCommonDataModel import (
        vtkCellTypeUtilities,
        vtkCellTypes,
        vtkDataSet,
    )
except Exception:
    # Fallback minimal stubs for environments without full VTK support
    class _DummyCellTypeUtilities:
        @staticmethod
        def GetDimension(cell_type):
            return 0

        @staticmethod
        def GetClassNameFromTypeId(cell_type):
            return ""

    vtkCellTypeUtilities = _DummyCellTypeUtilities

    class _DummyCellTypes:
        def __init__(self):
            pass

        def GetNumberOfTypes(self):
            return 0

        def GetCellType(self, index):
            return 0

        @staticmethod
        def GetClassNameFromTypeId(cell_type):
            return ""

    vtkCellTypes = _DummyCellTypes

    class vtkDataSet:
        pass


from vtkmodules.vtkIOLegacy import vtkDataSetWriter

POINT_COORDINATE_DECIMALS = (12, 10, 8)


def is_paraview_available():
    """Return True when both ParaView and the trame ParaView widget are importable."""
    try:
        return all(
            importlib.util.find_spec(name) is not None
            for name in ("paraview", "trame.widgets.paraview")
        )
    except ModuleNotFoundError:
        return False


class PipelineNode(TypedDict, total=False):
    id: str
    source: Any
    display: Any
    filename: str
    kind: str
    label: str
    parent_id: str | None
    filter_key: str | None
    visibility: bool
    cell_dimension_visibility: dict[str, bool]
    cell_dimension_extracts: dict


class ParaViewBackend:
    """Thin adapter around ``paraview.simple`` with lightweight pipeline state."""

    def __init__(self, data_directory=None, show_experimental_filters=True, state=None):
        if not is_paraview_available():
            raise RuntimeError(
                "ParaView backend requested but 'paraview' or 'trame.widgets.paraview' "
                "is not available in this Python environment."
            )

        from paraview import simple
        from paraview import servermanager

        self.simple = simple
        self.servermanager = servermanager
        self.view = None
        self.pipeline_nodes: list[PipelineNode] = []
        self.active_node_id = None
        self.data_directory = (
            os.path.abspath(data_directory) if data_directory else None
        )
        self._filter_counts = {key: 0 for key in SUPPORTED_FILTERS}
        self.filter_catalog = ParaViewFilterCatalog(
            self.simple, show_experimental_filters=show_experimental_filters
        )
        self.state = state  # Store the state object

        self.property_inspector = ParaViewPropertyInspector()
        self._edit_selection_overlay = None
        self._edit_selection_display = None
        self._scalar_bar_visible = False
        self._edit_target_dataset = None
        self._surface_selection_helper = None
        self._last_selection_backend_timing = []
        self._boundary_cache = {}
        self._cell_type_name_aliases = {
            "Quad": "Quadrilateral",
            "Tetra": "Tetrahedron",
            "QuadraticTetra": "QuadraticTetrahedron",
        }

    def set_edit_target_dataset(self, dataset):
        """Set the edit-session dataset used to normalize picker IDs."""
        self._edit_target_dataset = dataset
        self._clear_surface_selection_helper()
        self._clear_boundary_cache()

    def clear_edit_target_dataset(self):
        """Clear edit-session dataset normalization context."""
        self._edit_target_dataset = None
        self._clear_surface_selection_helper()
        self._clear_boundary_cache()

    def consume_selection_backend_timing(self):
        """Return and clear detailed timing from the last backend selection."""
        timing = list(getattr(self, "_last_selection_backend_timing", []) or [])
        self._last_selection_backend_timing = []
        return timing

    @property
    def source(self):
        """Return the active ParaView source proxy."""
        node = self._get_active_node()
        return None if node is None else node["source"]

    @property
    def display(self):
        """Return the active ParaView display proxy."""
        node = self._get_active_node()
        return None if node is None else node["display"]

    def initialize_view(self):
        """Create the render view used by Trame."""
        self.simple._DisableFirstRenderCameraReset()
        self.view = self.simple.GetActiveViewOrCreate("RenderView")
        self._set_white_background()
        self.view.MakeRenderWindowInteractor(True)
        self.simple.SetActiveView(self.view)
        return self.view

    @staticmethod
    def _preview_values(values, limit=12):
        seq = list(values or [])
        if len(seq) <= limit:
            return seq
        return seq[:limit] + [f"...(+{len(seq) - limit})"]

    def _set_white_background(self):
        """Force a plain white render background across ParaView versions."""
        # Some builds keep the color palette in control unless explicitly disabled.
        try:
            if hasattr(self.simple, "LoadPalette"):
                self.simple.LoadPalette("WhiteBackground")
        except Exception:
            pass

        if self.view is None:
            return

        for name, value in (
            ("UseColorPaletteForBackground", 0),
            ("BackgroundColorMode", "Single Color"),
            ("UseGradientBackground", 0),
            ("Background", [1.0, 1.0, 1.0]),
            ("Background2", [1.0, 1.0, 1.0]),
        ):
            try:
                setattr(self.view, name, value)
            except Exception:
                pass

    def load_file(self, filename):
        """Load a dataset into the current view and make it active."""
        if self.view is None:
            self.initialize_view()

        reader_filename = sanitized_vtk_xml_path(filename)
        source = self.simple.OpenDataFile(reader_filename)
        if source is None:
            raise RuntimeError(f"ParaView could not open file: {filename}")

        scene = self.simple.GetAnimationScene()
        if hasattr(scene, "UpdateAnimationUsingDataTimeSteps"):
            scene.UpdateAnimationUsingDataTimeSteps()

        # Explicitly check and set time information if available
        time_values = self._coerce_time_values(
            getattr(scene.TimeKeeper, "TimestepValues", None)
        )
        is_time_dependent = len(time_values) > 1
        total_timesteps = len(time_values)
        current_time = time_values[0] if time_values else 0.0
        time_index = 0

        # Update the backend state directly which should be synced to frontend
        if self.state is not None:
            self.state.is_time_dependent = is_time_dependent
            self.state.total_timesteps = total_timesteps
            self.state.time_values = time_values
            self.state.current_time = current_time
            self.state.time_index = time_index
            self.state.time_playing = False

        print(
            "DEBUG load_file: Time detection result - "
            f"is_time_dependent={is_time_dependent}, "
            f"total_timesteps={total_timesteps}, times={time_values}"
        )

        debug_log("[view-debug] load_file: calling Show()")
        display = self.simple.Show(source, self.view)
        debug_log("[view-debug] load_file: Show() returned — disabling auto-coloring")
        # Disable any auto-coloring ParaView assigned during Show() so that
        # the first render (triggered by ResetCamera below) never tries to
        # look up a LUT that hasn't been explicitly bound yet.
        self._disable_scalar_coloring(display, hide_unused_scalar_bars=False)
        debug_log("[view-debug] load_file: auto-coloring cleared")
        display.SetRepresentationType(
            self._normalize_representation("Surface with Edges")
        )
        debug_log("[view-debug] load_file: SetRepresentationType done")

        node = self._make_node(
            source=source,
            display=display,
            filename=filename,
            kind="source",
            label=os.path.basename(
                self._relative_path(filename) or filename or "source"
            ),
        )
        self.pipeline_nodes.append(node)

        self.set_active_node(node["id"])
        if self.view is not None:
            self._sync_view_center(source)
            reset_camera = getattr(self.view, "ResetCamera", None)
            if callable(reset_camera):
                debug_log("[view-debug] load_file: calling ResetCamera()")
                reset_camera()
                debug_log("[view-debug] load_file: ResetCamera() returned")

        arrays = self.get_available_arrays()
        default_array = next(
            (
                item["value"]
                for item in arrays
                if item["value"] == f"{CELL_PREFIX}{MATERIAL_ID_ARRAY}"
            ),
            arrays[1]["value"] if len(arrays) > 1 else ARRAY_SOLID,
        )
        return arrays, default_array

    def get_available_filters(self):
        """Return supported and experimental filter lists for the UI."""
        return self.filter_catalog.get_available_filters()

    def add_filter(self, filter_key):
        """Create a new filter node from the active pipeline node."""
        node = self._get_active_node()
        if node is None:
            raise RuntimeError("No active source available for filtering")

        spec = SUPPORTED_FILTERS.get(filter_key)
        if spec is None:
            spec = self.filter_catalog.experimental_filter_spec(filter_key)
        if spec is None:
            raise ValueError(f"Unsupported filter: {filter_key}")

        source = node["source"]
        display = node["display"]
        selected_array = self._get_selected_array()
        representation = self._get_representation()
        visible = bool(display.Visibility) if display is not None else True

        filter_proxy = getattr(self.simple, spec["factory"])(Input=source)
        filter_proxy.UpdatePipeline()
        self.simple.SetActiveSource(filter_proxy)
        filter_display = self.simple.Show(filter_proxy, self.view)
        filter_node = self._make_node(
            source=filter_proxy,
            display=filter_display,
            filename=node["filename"],
            kind="filter",
            label=f"{spec['label']} {self._filter_counts.get(filter_key, 0) + 1}",
            parent_id=node["id"],
            filter_key=filter_key,
        )
        filter_node["visibility"] = visible
        filter_display.Visibility = 1 if visible else 0
        filter_display.SetRepresentationType(
            self._normalize_representation(representation)
        )
        if display is not None:
            display.Visibility = 0

        self._filter_counts[filter_key] = self._filter_counts.get(filter_key, 0) + 1
        self.pipeline_nodes.append(filter_node)
        self.set_active_node(filter_node["id"])
        self.apply_coloring(self._resolve_available_array_value(selected_array))
        self.render()
        return filter_node["id"]

    def default_output_filename(self):
        """Return a suggested output filename for the active pipeline node."""
        node = self._get_active_node()
        if node is None:
            return "output" + self.default_output_extension()
        label = node.get("label") or "output"
        safe_label = "".join(
            char if char.isalnum() or char in {"-", "_"} else "_" for char in label
        ).strip("_")
        if not safe_label:
            safe_label = "output"
        return safe_label + self.default_output_extension()

    def default_output_extension(self):
        """Return the default output extension for saved pipeline results."""
        return self._default_output_extension()

    def save_active_data(self, output_path):
        """Save the currently active pipeline result to a new file."""
        source = self.source
        if source is None:
            raise RuntimeError("No active pipeline item to save")
        source.UpdatePipeline()
        suffix = os.path.splitext(str(output_path))[1].lower()
        if suffix == ".vtk":
            dataset = self.servermanager.Fetch(source)
            if isinstance(dataset, vtkDataSet):
                strip_data_array_information_keys(dataset)
                writer = vtkDataSetWriter()
                writer.SetFileName(str(output_path))
                writer.SetInputData(dataset)
                if writer.Write() != 1:
                    raise RuntimeError(
                        f"Failed to write legacy VTK dataset to {output_path}"
                    )
            else:
                # Fallback for unsupported/non-dataset pipeline outputs.
                self.simple.SaveData(output_path, proxy=source)
        else:
            self.simple.SaveData(output_path, proxy=source)
        return output_path

    def export_active_dataset_for_editing(self):
        """Fetch the active pipeline result as a local VTK dataset for editing."""
        source = self.source
        node = self._get_active_node()
        if source is None or node is None:
            raise RuntimeError("No active pipeline item available for editing")

        from paraview import servermanager

        source.UpdatePipeline()
        dataset = servermanager.Fetch(source)
        if not EditSession.is_supported_dataset(dataset):
            data_type = type(dataset).__name__ if dataset is not None else "Unknown"
            raise TypeError(
                f"Edit mode currently supports only vtkUnstructuredGrid outputs, got {data_type}."
            )
        return {
            "node_id": node["id"],
            "label": node.get("label")
            or os.path.basename(node.get("filename") or "source"),
            "filename": node.get("filename") or "",
            "dataset": dataset,
        }

    def set_active_node(self, node_id):
        """Make the given pipeline node active."""
        node = self._find_node(node_id)
        if node is None:
            return False

        self.active_node_id = node_id
        self.simple.SetActiveSource(node["source"])
        if self.view is not None:
            self.simple.SetActiveView(self.view)
            self._sync_view_center(node["source"])
        return True

    def reload_node_file(self, node_id):
        """Reload the file backing a pipeline node as a fresh source."""
        node = self._find_node(node_id)
        if node is None:
            raise RuntimeError("No active pipeline item to reload")

        filename = node.get("filename")
        if not filename:
            raise RuntimeError("Active pipeline item has no backing file")

        root = node
        parent_id = root.get("parent_id")
        while parent_id:
            parent = self._find_node(parent_id)
            if parent is None:
                break
            root = parent
            parent_id = root.get("parent_id")

        arrays, default_array = self.load_file(filename)
        self.delete_node(root["id"])
        return arrays, default_array

    def set_visibility(self, node_id, visible):
        """Show or hide the display associated with a pipeline node."""
        node = self._find_node(node_id)
        if node is None or node["display"] is None:
            return False

        node["visibility"] = bool(visible)
        self._apply_cell_dimension_visibility(node)
        self.render()
        return True

    def get_visibility(self, node_id):
        """Return the visibility of a pipeline node, or ``None`` if unavailable."""
        node = self._find_node(node_id)
        if node is None or node["display"] is None:
            return None
        return bool(node.get("visibility", node["display"].Visibility))

    def set_cell_face_visibility(self, cells_visible=True, faces_visible=True):
        """Show/hide semantic cells and faces on the active node.

        ParaView/VTK call every top-level entity a cell, regardless of whether
        it is a vertex, segment, triangle, quad, tet, hex, and so on. In this
        UI, "cell" means the highest intrinsic cell dimension present in the
        active dataset, while "face" means explicit top-level cells one
        dimension lower. Faces are never generated from higher-dimensional
        cells here; they are shown only when the file/source already exposes
        cells with the face dimension.
        """
        node = self._get_active_node()
        if node is None or node["display"] is None:
            return False

        node["cell_dimension_visibility"] = {
            "cells": bool(cells_visible),
            "faces": bool(faces_visible),
        }
        self._apply_cell_dimension_visibility(node)
        self.render()
        return True

    def set_cell_dimension_visibility(self, volume_visible=True, surface_visible=True):
        """Backward-compatible wrapper for older controller/test names."""
        return self.set_cell_face_visibility(volume_visible, surface_visible)

    def delete_node(self, node_id):
        """Delete a pipeline node and adjust active selection."""
        node = self._find_node(node_id)
        if node is None:
            return False
        self._clear_surface_selection_helper()
        self._clear_boundary_cache()

        node_ids = {entry["id"] for entry in self._collect_descendants(node_id)}
        node_ids.add(node_id)
        nodes_to_delete = [
            entry for entry in self.pipeline_nodes if entry["id"] in node_ids
        ]
        for entry in reversed(nodes_to_delete):
            if entry["display"] is not None and self.view is not None:
                self.simple.Hide(entry["source"], self.view)
                self._delete_cell_dimension_extracts(entry)
            self.simple.Delete(entry["source"])

        self.pipeline_nodes = [
            entry for entry in self.pipeline_nodes if entry["id"] not in node_ids
        ]

        if not self.pipeline_nodes:
            self.active_node_id = None
            self.render()
            return True

        next_active = self.pipeline_nodes[-1]["id"]
        self.set_active_node(next_active)
        self.render()
        return True

    def clear_pipeline(self):
        """Delete every pipeline node and reset the active selection."""
        for node in list(reversed(self.pipeline_nodes)):
            if self._find_node(node["id"]) is not None:
                self.delete_node(node["id"])

        self.pipeline_nodes = []
        self.active_node_id = None
        self.clear_active_selection()
        self.clear_edit_selection_overlay()
        self.render()

    def export_app_state(self):
        """Return a JSON-serializable snapshot of the current ParaView app state."""
        saved_active_id = self.active_node_id
        nodes = []

        for node in list(self.pipeline_nodes):
            self.set_active_node(node["id"])
            display = node.get("display")
            nodes.append(
                {
                    "id": node["id"],
                    "kind": node.get("kind") or "source",
                    "filename": self._relative_path(node.get("filename") or ""),
                    "parent_id": node.get("parent_id"),
                    "filter_key": node.get("filter_key"),
                    "visibility": bool(
                        node.get(
                            "visibility",
                            bool(display.Visibility) if display is not None else True,
                        )
                    ),
                    "selected_array": self._get_selected_array(),
                    "representation": self._get_representation(),
                    "cell_dimension_visibility": dict(
                        node.get("cell_dimension_visibility")
                        or {"cells": True, "faces": True}
                    ),
                    "source_properties": self.property_inspector.tag_property_scope(
                        self.property_inspector.collect_proxy_properties(
                            node.get("source"), scope="source"
                        ),
                        "source",
                    ),
                    "display_properties": self.property_inspector.tag_property_scope(
                        self.property_inspector.collect_proxy_properties(
                            display, scope="display"
                        ),
                        "display",
                    ),
                }
            )

        if saved_active_id:
            self.set_active_node(saved_active_id)

        return {
            "version": 1,
            "active_node_id": saved_active_id,
            "camera": self._capture_view_camera_state(),
            "nodes": nodes,
            "time": self.get_time_state(),
            "active_color_controls": {
                **self.get_color_control_state(),
                "color_map_preset": (
                    getattr(self.state, "color_map_preset", "")
                    if self.state is not None
                    else ""
                ),
            },
            "inspector_tab": (
                getattr(self.state, "inspector_tab", 0) if self.state is not None else 0
            ),
        }

    def import_app_state(self, snapshot):
        """Restore a previously saved application state snapshot."""
        if not isinstance(snapshot, dict):
            raise ValueError("Invalid application state payload")

        node_entries = list(snapshot.get("nodes") or [])
        id_map = {}
        self.clear_pipeline()

        for entry in node_entries:
            if not isinstance(entry, dict):
                continue

            kind = (entry.get("kind") or "source").strip().lower()
            if kind == "source":
                filename = self._resolve_snapshot_filename(entry.get("filename") or "")
                self.load_file(filename)
                new_id = self.active_node_id
            elif kind == "filter":
                parent_id = id_map.get(entry.get("parent_id"))
                if not parent_id:
                    raise ValueError(
                        "Saved state references a filter without a restored parent"
                    )
                filter_key = (entry.get("filter_key") or "").strip()
                if not filter_key:
                    raise ValueError("Saved state filter entry is missing filter_key")
                self.set_active_node(parent_id)
                new_id = self.add_filter(filter_key)
            else:
                raise ValueError(f"Unsupported saved pipeline node kind: {kind}")

            id_map[entry.get("id") or new_id] = new_id

        for entry in node_entries:
            saved_id = entry.get("id")
            restored_id = id_map.get(saved_id)
            if not restored_id:
                continue

            self.set_active_node(restored_id)
            self.apply_property_changes(
                entry.get("source_properties") or [],
                entry.get("display_properties") or [],
            )
            self.apply_representation(
                entry.get("representation") or "Surface with Edges"
            )
            self.apply_coloring(entry.get("selected_array") or ARRAY_SOLID)

            dimension_visibility = entry.get("cell_dimension_visibility") or {}
            self.set_cell_face_visibility(
                dimension_visibility.get("cells", True),
                dimension_visibility.get("faces", True),
            )
            self.set_visibility(restored_id, entry.get("visibility", True))

        active_node_id = id_map.get(snapshot.get("active_node_id"))
        if active_node_id:
            self.set_active_node(active_node_id)

        time_state = snapshot.get("time") or {}
        if time_state.get("is_time_dependent") and time_state.get("time_values"):
            try:
                self.set_time(
                    time_state.get("current_time", time_state["time_values"][0])
                )
            except Exception:
                pass

        controls = snapshot.get("active_color_controls") or {}
        if controls:
            if self._get_selected_array() != ARRAY_SOLID:
                preset = (controls.get("color_map_preset") or "").strip()
                if preset:
                    try:
                        self.apply_color_map_preset(preset)
                    except Exception:
                        pass

                if controls.get("categorical_coloring"):
                    self.set_categorical_coloring(True)

                range_min = controls.get("color_range_min", "")
                range_max = controls.get("color_range_max", "")
                if range_min not in {"", None} and range_max not in {"", None}:
                    try:
                        self.apply_color_range(range_min, range_max)
                    except Exception:
                        pass

                self.set_scalar_bar_visible(
                    bool(controls.get("color_bar_visible", False))
                )

            self.set_orientation_axes_visible(
                bool(controls.get("orientation_axes_visible", True))
            )

        camera_state = snapshot.get("camera")
        self._restore_view_camera_state(camera_state)
        self.render()
        return id_map

    def get_available_arrays(self):
        """Return Trame select items for point and cell arrays."""
        source = self.source
        if source is None:
            return [{"text": "Solid Color", "value": ARRAY_SOLID}]

        arrays = [{"text": "Solid Color", "value": ARRAY_SOLID}]
        data_information = source.GetDataInformation()
        arrays.extend(
            self._collect_array_items(
                data_information.GetPointDataInformation(), "POINTS"
            )
        )
        arrays.extend(
            self._collect_array_items(
                data_information.GetCellDataInformation(), "CELLS"
            )
        )
        return arrays

    def apply_coloring(self, array_value: str | None) -> None:
        """Apply solid or scalar coloring to the active representation."""
        display = self.display
        if display is None:
            return

        array_value = self._resolve_available_array_value(array_value)
        displays = self._active_display_targets()

        if array_value == ARRAY_SOLID or array_value is None:
            for target_display in displays:
                self._disable_scalar_coloring(target_display)
            self._scalar_bar_visible = False
            self.render()
            return

        if array_value.startswith(POINT_PREFIX):
            name = array_value[len(POINT_PREFIX) :]
            association = "POINTS"
        elif array_value.startswith(CELL_PREFIX):
            name = array_value[len(CELL_PREFIX) :]
            association = "CELLS"
        else:
            raise ValueError(
                f"Unsupported array value for ParaView backend: {array_value}"
            )

        for target_display in displays:
            if getattr(self, "_scalar_bar_visible", False):
                self._hide_current_scalar_bar(target_display)
            self.simple.ColorBy(target_display, (association, name))
            # Always rebind LookupTable after ColorBy
            lut = self._ensure_display_lookup_table(target_display, name)
            if getattr(target_display, "LookupTable", None) is None and lut is not None:
                try:
                    target_display.LookupTable = lut
                except Exception:
                    pass
            # Warn if still missing
            if getattr(target_display, "LookupTable", None) is None:
                import warnings

                warnings.warn(
                    "[coral] Warning: LookupTable is still None after ColorBy and _ensure_display_lookup_table. This may cause ParaView warning."
                )
            target_display.RescaleTransferFunctionToDataRange(True, False)

        can_show_scalar_bar = self._display_has_lookup_table(display, array_value)
        if can_show_scalar_bar and display is not None:
            try:
                display.SetScalarBarVisibility(self.view, True)
            except Exception:
                can_show_scalar_bar = False
        elif not can_show_scalar_bar:
            try:
                self.simple.HideUnusedScalarBars(self.view)
            except Exception:
                pass

        self._scalar_bar_visible = bool(can_show_scalar_bar)
        self.render()

    def get_color_control_state(self):
        """Return UI state for scalar color-map controls on the active display."""
        selected_array = self._get_selected_array()
        enabled = selected_array != ARRAY_SOLID and self.display is not None
        range_min = ""
        range_max = ""
        categorical = False
        if enabled:
            lut = self._active_lookup_table()
            range_min, range_max = self._lookup_table_range(lut)
            categorical = self._lookup_table_categorical(lut)
        return {
            "color_controls_enabled": enabled,
            "color_range_min": range_min,
            "color_range_max": range_max,
            "color_bar_visible": bool(
                enabled and getattr(self, "_scalar_bar_visible", enabled)
            ),
            "orientation_axes_visible": self._orientation_axes_visible(),
            "categorical_coloring": categorical,
        }

    def apply_color_map_preset(self, preset):
        """Apply a named ParaView color preset to the active scalar lookup table."""
        lut = self._active_lookup_table()
        if lut is None or not preset:
            return

        errors = []
        for candidate in self._color_preset_candidates(preset):
            try:
                if hasattr(lut, "ApplyPreset"):
                    lut.ApplyPreset(candidate, True)
                elif hasattr(self.simple, "ApplyColorPreset"):
                    self.simple.ApplyColorPreset(candidate, True)
                else:
                    return
                break
            except Exception as exc:
                errors.append(exc)
        else:
            if errors:
                raise errors[-1]

        self._restore_scalar_bar_visibility()
        self.render()

    def apply_color_range(self, range_min, range_max):
        """Apply a manual scalar color range to the active lookup table."""
        lut = self._active_lookup_table()
        if lut is None:
            return
        range_min = float(range_min)
        range_max = float(range_max)
        if range_min >= range_max:
            raise ValueError("Color range minimum must be less than maximum.")
        if hasattr(lut, "RescaleTransferFunction"):
            lut.RescaleTransferFunction(range_min, range_max)
        self._restore_scalar_bar_visibility()
        self.render()

    def rescale_color_range_to_data(self):
        """Rescale the active display color map to the current data range."""
        display = self.display
        if display is None:
            return
        self._rescale_display_transfer_function_to_data(display)
        self._restore_scalar_bar_visibility()
        self.render()

    def set_scalar_bar_visible(self, visible):
        """Show or hide the scalar color legend for the active display."""
        display = self.display
        if display is None or self.view is None:
            return
        if visible and not self._display_has_lookup_table(display):
            self._scalar_bar_visible = False
            try:
                self.simple.HideUnusedScalarBars(self.view)
            except Exception:
                pass
            self.render()
            return
        for target_display in self._active_display_targets():
            if hasattr(target_display, "SetScalarBarVisibility"):
                target_display.SetScalarBarVisibility(self.view, bool(visible))
        self._scalar_bar_visible = bool(visible)
        if not visible:
            try:
                self.simple.HideUnusedScalarBars(self.view)
            except Exception:
                pass
        self.render()

    def set_orientation_axes_visible(self, visible):
        """Show or hide the ParaView orientation axes in the active view."""
        if self.view is None:
            return
        try:
            self.view.OrientationAxesVisibility = 1 if visible else 0
        except Exception:
            return
        self.render()

    def set_categorical_coloring(self, enabled):
        """Toggle categorical interpretation on the active scalar lookup table."""
        lut = self._active_lookup_table()
        if lut is None:
            return
        if enabled:
            self._configure_categorical_lookup_table(lut)
        for prop_name in ("InterpretValuesAsCategories", "UseCategoricalColors"):
            if hasattr(lut, prop_name):
                try:
                    setattr(lut, prop_name, 1 if enabled else 0)
                except Exception:
                    pass
        if hasattr(lut, "IndexedLookup"):
            try:
                lut.IndexedLookup = 1 if enabled else 0
            except Exception:
                pass
        self.render()

    def _disable_scalar_coloring(self, display, *, hide_unused_scalar_bars=True):
        """Best-effort disable scalar coloring across ParaView version differences."""
        had_lookup_table = getattr(display, "LookupTable", None) is not None
        debug_log(
            f"[view-debug] _disable_scalar_coloring: had_lookup_table={had_lookup_table}"
        )
        # Only hide the scalar bar (and call HideUnusedScalarBars) when the
        # display has an explicitly bound LUT. Calling SetScalarBarVisibility on
        # a display whose LookupTable is None — even when ParaView auto-assigned
        # a color array during Show() — causes vtkSMColorMapEditorHelper to
        # traverse its internal LUT-resolution path and emit "Failed to determine
        # the LookupTable being used". The pre-hide must happen *before*
        # ColorBy(None) so the helper has nothing left to update during that call.
        if had_lookup_table:
            debug_log(
                "[view-debug] _disable_scalar_coloring: hiding scalar bar before ColorBy(None)"
            )
            if hasattr(display, "SetScalarBarVisibility") and self.view is not None:
                try:
                    display.SetScalarBarVisibility(self.view, False)
                except Exception:
                    pass
            try:
                self.simple.HideUnusedScalarBars(self.view)
            except Exception:
                pass
        debug_log("[view-debug] _disable_scalar_coloring: calling ColorBy(None)")
        try:
            self.simple.ColorBy(display, None)
        except Exception:
            pass
        debug_log("[view-debug] _disable_scalar_coloring: ColorBy(None) done")
        # Clear ColorArrayName and LookupTable explicitly so there is no
        # residual auto-assigned state that could confuse later renders.
        if hasattr(display, "ColorArrayName"):
            for value in (("", ""), None, [None, ""], (None, ""), ["", ""]):
                try:
                    display.ColorArrayName = value
                    break
                except Exception:
                    continue
        if hasattr(display, "LookupTable"):
            try:
                display.LookupTable = None
            except Exception:
                pass
        self._scalar_bar_visible = False

    def _hide_current_scalar_bar(self, display):
        """Hide the active display's current scalar bar before switching arrays."""
        if (
            display is not None
            and getattr(display, "LookupTable", None) is not None
            and hasattr(display, "SetScalarBarVisibility")
        ):
            try:
                display.SetScalarBarVisibility(self.view, False)
            except Exception:
                pass
            try:
                self.simple.HideUnusedScalarBars(self.view)
            except Exception:
                pass

    def _restore_scalar_bar_visibility(self):
        """Reapply the user-selected scalar-bar visibility after LUT updates."""
        display = self.display
        if display is None or self.view is None:
            return
        if self._get_selected_array() == ARRAY_SOLID:
            self._scalar_bar_visible = False
        visible = bool(getattr(self, "_scalar_bar_visible", False))
        if visible and not self._display_has_lookup_table(display):
            visible = False
            self._scalar_bar_visible = False
        for target_display in self._active_display_targets():
            if not hasattr(target_display, "SetScalarBarVisibility"):
                continue
            try:
                target_display.SetScalarBarVisibility(self.view, visible)
            except Exception:
                pass
        if not visible:
            try:
                self.simple.HideUnusedScalarBars(self.view)
            except Exception:
                pass

    @staticmethod
    def _rescale_display_transfer_function_to_data(display):
        """Force-rescale an active display LUT to the current data range."""
        rescale = getattr(display, "RescaleTransferFunctionToDataRange", None)
        if not callable(rescale):
            raise RuntimeError(
                "Current ParaView build does not expose data-range rescaling."
            )

        for args in ((False, True), (False,), ()):
            try:
                rescale(*args)
                return
            except TypeError:
                continue

        rescale(False, True)

    def _active_lookup_table(self):
        """Return the active display lookup table, resolving it by array name if needed."""
        display = self.display
        if display is None:
            return None
        lut = getattr(display, "LookupTable", None)
        if lut is not None:
            return lut
        selected_array = self._get_selected_array()
        if selected_array == ARRAY_SOLID:
            return None
        if selected_array.startswith(POINT_PREFIX):
            name = selected_array[len(POINT_PREFIX) :]
        elif selected_array.startswith(CELL_PREFIX):
            name = selected_array[len(CELL_PREFIX) :]
        else:
            return None
        getter = getattr(self.simple, "GetColorTransferFunction", None)
        if callable(getter):
            try:
                return self._ensure_display_lookup_table(display, name)
            except Exception:
                return None
        return None

    def _ensure_display_lookup_table(self, display, array_name):
        """Return and bind the LUT ParaView should use for a display array."""
        lut = getattr(display, "LookupTable", None)
        if lut is not None:
            return lut
        getter = getattr(self.simple, "GetColorTransferFunction", None)
        if not callable(getter) or not array_name:
            return None
        lut = getter(array_name)
        if lut is not None and hasattr(display, "LookupTable"):
            try:
                display.LookupTable = lut
            except Exception:
                pass
        return lut

    def _display_has_lookup_table(self, display, array_value=None):
        """Return True when a display has a LUT bound or one can be resolved safely."""
        if display is None:
            return False

        if getattr(display, "LookupTable", None) is not None:
            return True

        selected_array = array_value or self._get_selected_array()
        if not selected_array or selected_array == ARRAY_SOLID:
            return False

        if selected_array.startswith(POINT_PREFIX):
            name = selected_array[len(POINT_PREFIX) :]
        elif selected_array.startswith(CELL_PREFIX):
            name = selected_array[len(CELL_PREFIX) :]
        else:
            return False

        try:
            lut = self._ensure_display_lookup_table(display, name)
        except Exception:
            return False
        return lut is not None and getattr(display, "LookupTable", None) is not None

    @staticmethod
    def _lookup_table_range(lut):
        """Best-effort min/max extraction from a ParaView lookup table proxy."""
        if lut is None:
            return "", ""
        rgb_points = getattr(lut, "RGBPoints", None)
        if rgb_points and len(rgb_points) >= 8:
            try:
                return f"{float(rgb_points[0]):g}", f"{float(rgb_points[-4]):g}"
            except (TypeError, ValueError):
                pass
        getter = getattr(lut, "GetRange", None)
        if callable(getter):
            try:
                low, high = getter()
                return f"{float(low):g}", f"{float(high):g}"
            except Exception:
                pass
        return "", ""

    @staticmethod
    def _lookup_table_categorical(lut):
        if lut is None:
            return False
        for prop_name in ("InterpretValuesAsCategories", "UseCategoricalColors"):
            if hasattr(lut, prop_name):
                try:
                    return bool(getattr(lut, prop_name))
                except Exception:
                    pass
        return False

    def _configure_categorical_lookup_table(self, lut):
        """Populate annotations and indexed colors for the active scalar array."""
        values = self._active_scalar_unique_values(limit=64)
        if not values:
            return

        annotations = []
        for value in values:
            label = self._format_category_value(value)
            annotations.extend([label, label])

        for prop_name in ("Annotations", "AnnotationsInitialized"):
            if not hasattr(lut, prop_name):
                continue
            try:
                value = annotations if prop_name == "Annotations" else 1
                setattr(lut, prop_name, value)
            except Exception:
                pass

        if hasattr(lut, "IndexedColors"):
            try:
                lut.IndexedColors = self._categorical_palette(len(values))
            except Exception:
                pass

    def _active_scalar_unique_values(self, limit=64):
        """Return sorted unique scalar values for the active color array."""
        selected_array = self._get_selected_array()
        if selected_array == ARRAY_SOLID:
            return []
        if selected_array.startswith(POINT_PREFIX):
            association = "point"
            name = selected_array[len(POINT_PREFIX) :]
        elif selected_array.startswith(CELL_PREFIX):
            association = "cell"
            name = selected_array[len(CELL_PREFIX) :]
        else:
            return []

        fetch = getattr(self.servermanager, "Fetch", None)
        if not callable(fetch) or self.source is None:
            return []

        try:
            dataset = fetch(self.source)
        except Exception:
            return []

        values = set()
        self._collect_scalar_unique_values(dataset, association, name, values, limit)
        return sorted(values, key=lambda item: (float(item), str(item)))

    def _collect_scalar_unique_values(self, dataset, association, name, values, limit):
        if dataset is None or len(values) >= limit:
            return
        if hasattr(dataset, "GetNumberOfBlocks"):
            for index in range(dataset.GetNumberOfBlocks()):
                self._collect_scalar_unique_values(
                    dataset.GetBlock(index), association, name, values, limit
                )
                if len(values) >= limit:
                    return
            return

        data_getter = (
            getattr(dataset, "GetPointData", None)
            if association == "point"
            else getattr(dataset, "GetCellData", None)
        )
        data = data_getter() if callable(data_getter) else None
        array = (
            data.GetArray(name)
            if data is not None and hasattr(data, "GetArray")
            else None
        )
        if array is None:
            return

        tuples = array.GetNumberOfTuples() if hasattr(array, "GetNumberOfTuples") else 0
        components = (
            array.GetNumberOfComponents()
            if hasattr(array, "GetNumberOfComponents")
            else 1
        )
        for index in range(tuples):
            try:
                value = (
                    array.GetTuple1(index)
                    if components == 1 and hasattr(array, "GetTuple1")
                    else array.GetTuple(index)[0]
                )
                values.add(float(value))
            except Exception:
                continue
            if len(values) >= limit:
                return

    @staticmethod
    def _format_category_value(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        if number.is_integer():
            return str(int(number))
        return f"{number:g}"

    @staticmethod
    def _categorical_palette(count):
        base = [
            (0.1216, 0.4667, 0.7059),
            (1.0, 0.4980, 0.0549),
            (0.1725, 0.6275, 0.1725),
            (0.8392, 0.1529, 0.1569),
            (0.5804, 0.4039, 0.7412),
            (0.5490, 0.3373, 0.2941),
            (0.8902, 0.4667, 0.7608),
            (0.4980, 0.4980, 0.4980),
            (0.7373, 0.7412, 0.1333),
            (0.0902, 0.7451, 0.8118),
        ]
        colors = []
        for index in range(max(0, count)):
            colors.extend(base[index % len(base)])
        return colors

    @staticmethod
    def _color_preset_candidates(preset):
        """Return compatible ParaView preset names for a UI preset value."""
        candidates = [preset]
        aliases = {
            "Viridis (matplotlib)": "Viridis",
        }
        alias = aliases.get(preset)
        if alias and alias not in candidates:
            candidates.append(alias)
        return candidates

    def _orientation_axes_visible(self):
        if self.view is None:
            return True
        try:
            return bool(getattr(self.view, "OrientationAxesVisibility", True))
        except Exception:
            return True

    def _active_display_targets(self):
        """Return active original/extracted displays that need styling updates."""
        node = self._get_active_node()
        if node is None:
            return []

        displays = [node["display"]] if node.get("display") is not None else []
        for entry in (node.get("cell_dimension_extracts") or {}).values():
            display = entry.get("display") if isinstance(entry, dict) else None
            if display is not None and display not in displays:
                displays.append(display)
        return displays

    def _apply_cell_dimension_visibility(self, node: PipelineNode):
        """Apply stored cell/face flags using per-dimension extract displays."""
        if node is None or node.get("display") is None:
            return

        node_visible = bool(node.get("visibility", True))
        flags = node.get("cell_dimension_visibility") or {
            "cells": True,
            "faces": True,
        }
        cells_visible = bool(flags.get("cells", flags.get("volume", True)))
        faces_visible = bool(flags.get("faces", flags.get("surface", True)))
        dataset_dimensions = self._available_cell_dimensions(node["source"])
        dimension_roles = self._semantic_cell_dimension_roles(node, dataset_dimensions)
        requested_dimensions = set()
        if cells_visible and "cells" in dimension_roles:
            requested_dimensions.add(dimension_roles["cells"])
        if faces_visible and "faces" in dimension_roles:
            requested_dimensions.add(dimension_roles["faces"])

        if requested_dimensions and requested_dimensions == dataset_dimensions:
            self._set_proxy_visibility(node["display"], node_visible)
            self._set_extract_displays_visibility(node, False)
            return

        self._set_proxy_visibility(node["display"], False)
        self._set_extract_displays_visibility(node, False)
        for role, dimension in dimension_roles.items():
            visible = node_visible and (
                (role == "cells" and cells_visible)
                or (role == "faces" and faces_visible)
            )
            self._set_extract_visibility_for_dimension(node, dimension, visible)

    def _semantic_cell_dimension_roles(
        self, node: PipelineNode | None, dimensions=None
    ):
        """Return UI cell/face roles mapped to intrinsic VTK cell dimensions."""
        if node is None:
            return {}
        if dimensions is None:
            dimensions = self._available_cell_dimensions(node["source"])
        if not dimensions:
            return {}
        cell_dimension = max(dimensions)
        roles = {"cells": cell_dimension}
        face_dimension = cell_dimension - 1
        if face_dimension in dimensions:
            roles["faces"] = face_dimension
        return roles

    def _available_cell_dimensions(self, source):
        """Return intrinsic dimensions for top-level cells exposed by a source."""
        dimensions = set()
        for dimension in range(4):
            if self._cell_type_names_for_dimension(source, dimension):
                dimensions.add(dimension)
        return dimensions

    def _set_extract_visibility_for_dimension(
        self, node: PipelineNode, dimension_key, visible
    ):
        """Ensure a cell-dimension extract exists when it needs to be visible."""
        entry = (
            self._ensure_cell_dimension_extract(node, dimension_key)
            if visible
            else None
        )
        if entry is None:
            entry = (node.get("cell_dimension_extracts") or {}).get(dimension_key)
        display = entry.get("display") if isinstance(entry, dict) else None
        self._set_proxy_visibility(display, visible)

    def _ensure_cell_dimension_extract(self, node: PipelineNode, dimension_key):
        """Create an ExtractCellsByType display for one intrinsic dimension."""
        extracts = node.setdefault("cell_dimension_extracts", {})
        entry = extracts.get(dimension_key)
        if entry is not None:
            return entry

        factory = getattr(self.simple, "ExtractCellsByType", None)
        if not callable(factory):
            raise RuntimeError(
                "This ParaView build does not expose ExtractCellsByType."
            )

        cell_types = self._cell_type_names_for_dimension(node["source"], dimension_key)
        if not cell_types:
            return None

        camera_state = self._capture_view_camera_state()
        extract = factory(Input=node["source"])
        extract.CellTypes = cell_types
        extract.UpdatePipeline()
        display = self.simple.Show(extract, self.view)
        display.SetRepresentationType(
            self._normalize_representation(self._get_representation())
        )
        self._copy_display_coloring(node["display"], display)
        self._restore_view_camera_state(camera_state)
        extracts[dimension_key] = {"source": extract, "display": display}
        return extracts[dimension_key]

    def _capture_view_camera_state(self):
        """Return a shallow snapshot of view camera properties when available."""
        if self.view is None:
            return None

        state = {}
        for name in (
            "CameraPosition",
            "CameraFocalPoint",
            "CameraViewUp",
            "CameraParallelScale",
            "CenterOfRotation",
        ):
            if not hasattr(self.view, name):
                continue
            try:
                value = getattr(self.view, name)
            except Exception:
                continue
            if isinstance(value, (list, tuple)):
                state[name] = list(value)
            else:
                state[name] = value
        return state or None

    def _restore_view_camera_state(self, camera_state):
        """Restore a previously captured view camera snapshot."""
        if self.view is None or not camera_state:
            return
        for name, value in camera_state.items():
            if not hasattr(self.view, name):
                continue
            try:
                setattr(self.view, name, value)
            except Exception:
                pass

    def _delete_cell_dimension_extracts(self, node: PipelineNode):
        """Remove auxiliary extract proxies for a pipeline node."""
        extracts = node.get("cell_dimension_extracts") or {}
        for entry in list(extracts.values()):
            source = entry.get("source") if isinstance(entry, dict) else None
            if source is None:
                continue
            try:
                if self.view is not None:
                    self.simple.Hide(source, self.view)
            except Exception:
                pass
            try:
                self.simple.Delete(source)
            except Exception:
                pass
        extracts.clear()

    def _set_extract_displays_visibility(self, node: PipelineNode, visible):
        for entry in (node.get("cell_dimension_extracts") or {}).values():
            display = entry.get("display") if isinstance(entry, dict) else None
            self._set_proxy_visibility(display, visible)

    @staticmethod
    def _set_proxy_visibility(display, visible):
        if display is not None and hasattr(display, "Visibility"):
            display.Visibility = 1 if visible else 0

    def _apply_representation_to_extract_displays(
        self, node: PipelineNode, representation
    ):
        for entry in (node.get("cell_dimension_extracts") or {}).values():
            display = entry.get("display") if isinstance(entry, dict) else None
            if display is not None:
                display.SetRepresentationType(
                    self._normalize_representation(representation)
                )

    def _copy_display_coloring(self, source_display, target_display):
        """Copy the active display coloring onto a newly-created extract display."""
        selected_array = self._get_selected_array()
        if selected_array == ARRAY_SOLID:
            self._disable_scalar_coloring(target_display, hide_unused_scalar_bars=False)
            self._copy_solid_display_style(source_display, target_display)
            return
        if selected_array.startswith(POINT_PREFIX):
            association = "POINTS"
            name = selected_array[len(POINT_PREFIX) :]
        elif selected_array.startswith(CELL_PREFIX):
            association = "CELLS"
            name = selected_array[len(CELL_PREFIX) :]
        else:
            return

        self.simple.ColorBy(target_display, (association, name))
        if getattr(source_display, "LookupTable", None) is not None and hasattr(
            target_display, "LookupTable"
        ):
            try:
                target_display.LookupTable = source_display.LookupTable
                return
            except Exception:
                pass
        self._ensure_display_lookup_table(target_display, name)

    @staticmethod
    def _copy_solid_display_style(source_display, target_display):
        """Keep generated cell/face extracts visually consistent in solid color mode."""
        for name in (
            "DiffuseColor",
            "AmbientColor",
            "EdgeColor",
            "Opacity",
            "LineWidth",
            "PointSize",
        ):
            if not hasattr(source_display, name) or not hasattr(target_display, name):
                continue
            try:
                setattr(target_display, name, getattr(source_display, name))
            except Exception:
                pass

    def _cell_type_names_for_dimension(self, source, target_dimension):
        """Return ParaView ExtractCellsByType names present for a cell dimension."""
        try:
            dataset = self.servermanager.Fetch(source)
        except Exception:
            return []
        if dataset is None:
            return []

        names = []
        self._collect_cell_type_names_for_dimension(dataset, target_dimension, names)
        return names

    def _collect_cell_type_names_for_dimension(self, dataset, target_dimension, names):
        """Append ExtractCellsByType names from dataset or composite children."""
        if hasattr(dataset, "GetNumberOfBlocks"):
            for index in range(dataset.GetNumberOfBlocks()):
                block = dataset.GetBlock(index)
                if block is not None:
                    self._collect_cell_type_names_for_dimension(
                        block, target_dimension, names
                    )
            return
        if hasattr(dataset, "IsA") and dataset.IsA("vtkCompositeDataSet"):
            iterator = dataset.NewIterator()
            iterator.InitTraversal()
            while not iterator.IsDoneWithTraversal():
                block = iterator.GetCurrentDataObject()
                if block is not None:
                    self._collect_cell_type_names_for_dimension(
                        block, target_dimension, names
                    )
                iterator.Next()
            return
        if not hasattr(dataset, "GetCellTypes"):
            return

        cell_types = vtkCellTypes()
        try:
            dataset.GetCellTypes(cell_types)
        except Exception:
            return
        for index in range(cell_types.GetNumberOfTypes()):
            cell_type = cell_types.GetCellType(index)
            try:
                dimension = vtkCellTypeUtilities.GetDimension(cell_type)
            except Exception:
                continue
            if dimension != target_dimension:
                continue
            name_getter = getattr(vtkCellTypeUtilities, "GetClassNameFromTypeId", None)
            name = (
                name_getter(cell_type)
                if callable(name_getter)
                else vtkCellTypes.GetClassNameFromTypeId(cell_type)
            )
            if not name:
                continue
            if name.startswith("vtk"):
                name = name[3:]
            name = self._cell_type_name_aliases.get(name, name)
            if name not in names:
                names.append(name)

    def apply_representation(self, representation):
        """Update the representation used by the active display."""
        display = self.display
        if display is None:
            return

        display.SetRepresentationType(self._normalize_representation(representation))
        self._apply_representation_to_extract_displays(
            self._get_active_node(), representation
        )
        self.render()

    def reset_camera(self):
        """Reset camera and render the active view."""
        if self.view is None:
            return

        if self.source is not None:
            self._sync_view_center(self.source)
        self.view.ResetCamera()
        self.render()

    def reset_view(self):
        """Restore a canonical XYZ view and fit the active dataset."""
        if self.view is None:
            return

        source = self.source
        if source is None:
            return

        data_information = source.GetDataInformation()
        bounds = data_information.GetBounds() if data_information is not None else None
        if not bounds:
            self.reset_camera()
            return

        xmin, xmax, ymin, ymax, zmin, zmax = bounds
        center = (
            0.5 * (xmin + xmax),
            0.5 * (ymin + ymax),
            0.5 * (zmin + zmax),
        )
        span_x = max(abs(xmax - xmin), 1e-6)
        span_y = max(abs(ymax - ymin), 1e-6)
        span_z = max(abs(zmax - zmin), 1e-6)
        distance = max(span_x, span_y, span_z) * 2.5

        self.view.CameraFocalPoint = center
        self.view.CameraPosition = (center[0], center[1], center[2] + distance)
        self.view.CameraViewUp = (0.0, 1.0, 0.0)
        self.view.CenterOfRotation = center
        self.view.ResetCamera()
        self.render()

    def render(self):
        """Trigger a ParaView render."""
        if self.view is not None:
            self.simple.Render(self.view)

    def clear_edit_selection_overlay(self):
        """Remove the transient edit-selection overlay from the view."""
        if self._edit_selection_display is not None:
            try:
                self.simple.Hide(self._edit_selection_overlay, self.view)
            except Exception:
                pass
            self._edit_selection_display = None

        if self._edit_selection_overlay is not None:
            try:
                self.simple.Delete(self._edit_selection_overlay)
            except Exception:
                pass
            self._edit_selection_overlay = None

    def clear_active_selection(self):
        """Clear any ParaView-side selection state on the active source."""
        source = self.source
        if source is None:
            return
        self._clear_selection_state(source)

    def _clear_selection_state(self, source=None):
        """Clear ParaView selection state globally and for a specific source."""
        try:
            self.simple.ClearSelection(source)
        except Exception:
            pass
        try:
            self.simple.ClearSelection()
        except Exception:
            pass

    def set_interactor_rotation(self, enabled):
        """Enable or disable grid manipulation on the ParaView server-side view."""
        if self.view is None:
            return

        # Attempt to use modern ParaView 'Interactions' property if available
        if hasattr(self.view, "Interactions"):
            try:
                current = list(self.view.Interactions)
                if enabled:
                    current[0] = "Rotate"
                    current[1] = "Pan"
                    current[2] = "Zoom"
                else:
                    # Disable common interactions
                    current[0] = "None"
                    current[1] = "None"
                    current[2] = "None"
                self.view.Interactions = current
                return
            except Exception:
                pass

        # Fallback for ParaView versions that use Camera3DManipulators / Camera2DManipulators
        if hasattr(self.view, "Camera3DManipulators"):
            try:
                m3d = list(self.view.Camera3DManipulators)
                if enabled:
                    # Restore standard defaults if they appear disabled
                    if m3d[0] == "None":
                        m3d[0] = "Rotate"
                    if m3d[1] == "None":
                        m3d[1] = "Pan"
                    if m3d[2] == "None":
                        m3d[2] = "Zoom"
                else:
                    # Disable everything to prevent accidental rotation/pan during picking
                    m3d = ["None"] * 9
                self.view.Camera3DManipulators = m3d
            except Exception:
                pass

        if hasattr(self.view, "Camera2DManipulators"):
            try:
                m2d = list(self.view.Camera2DManipulators)
                if enabled:
                    if m2d[0] == "None":
                        m2d[0] = "Pan"
                else:
                    m2d = ["None"] * 9
                self.view.Camera2DManipulators = m2d
            except Exception:
                pass

    def update_edit_selection_overlay(self, dataset):
        """Show the selected edit-session cells as a transient ParaView overlay."""
        if self.view is None:
            return

        source = self.source

        if dataset is None or dataset.GetNumberOfCells() == 0:
            self.clear_edit_selection_overlay()
            self.render()
            return

        # Recreate the transient overlay on each update to avoid stale proxy state.
        self.clear_edit_selection_overlay()
        overlay = self.simple.TrivialProducer(registrationName="__edit_selection__")
        overlay.GetClientSideObject().SetOutput(dataset)
        overlay.UpdatePipeline()
        display = self.simple.Show(overlay, self.view)
        # Overlay producers may not expose a stable LUT; skip scalar-bar cleanup to avoid warnings.
        self._disable_scalar_coloring(display, hide_unused_scalar_bars=False)
        display.SetRepresentationType("Surface With Edges")
        display.DiffuseColor = [1.0, 0.92, 0.25]  # Bright Gold
        display.AmbientColor = [1.0, 0.92, 0.25]
        display.EdgeColor = [0.0, 0.0, 0.0]  # Black edges for contrast
        display.Opacity = 1.0
        if hasattr(display, "Pickable"):
            display.Pickable = 0
        pickable_property = display.GetProperty("Pickable")
        if pickable_property is not None and hasattr(pickable_property, "SetData"):
            pickable_property.SetData(0)
        if hasattr(display, "LineWidth"):
            display.LineWidth = 4.0
        if hasattr(display, "PointSize"):
            display.PointSize = 10.0

        # Ensure it's always on top if possible (Polygon Offset)
        if hasattr(display, "RelativeCoincidentTopologyPolygonOffsetParameters"):
            display.RelativeCoincidentTopologyPolygonOffsetParameters = [-2.0, -2.0]

        self._edit_selection_overlay = overlay
        self._edit_selection_display = display

        if source is not None:
            self.simple.SetActiveSource(source)

        self.render()

    def pick_visible_cell_ids(self, x, y, radius=1):
        """Return selected visible cell ids around a display-space click."""
        source = self.source
        if self.view is None or source is None:
            return []

        try:
            x = int(round(float(x)))
            y = int(round(float(y)))
        except (TypeError, ValueError):
            return []

        candidates = self._candidate_pick_positions(x, y)
        self.clear_edit_selection_overlay()
        self.simple.SetActiveView(self.view)
        self.simple.SetActiveSource(source)

        picked_result = []
        for px, py in candidates:
            self._clear_selection_state(source)
            rect = [px - radius, py - radius, px + radius, py + radius]
            self.simple.SelectSurfaceCells(
                Rectangle=rect, View=self.view, Modifier=None
            )
            raw_picked = self._fetch_selected_original_cell_ids(source)
            picked_result = list(raw_picked)
            print(
                "[selection-debug] backend.pick.click "
                f"rect={rect} raw_count={len(raw_picked)} raw={self._preview_values(raw_picked)} "
                f"accepted_count={len(picked_result)} accepted={self._preview_values(picked_result)}"
            )
            if picked_result:
                break

        # Always clear and RENDER to hide the native ParaView purple selection
        self._clear_selection_state(source)
        self.render()
        remapped = self._remap_cell_ids_to_edit_target_dataset(picked_result, source)
        print(
            "[selection-debug] backend.pick.click.result "
            f"final_count={len(remapped)} final={self._preview_values(remapped)}"
        )
        return remapped

    def pick_visible_cell_ids_in_rect(self, x0, y0, x1, y1, behavior="touch"):
        """Return selected visible cell ids inside a display-space rectangle."""
        source = self.source
        if self.view is None or source is None:
            return []

        try:
            x0 = int(round(float(x0)))
            y0 = int(round(float(y0)))
            x1 = int(round(float(x1)))
            y1 = int(round(float(y1)))
        except (TypeError, ValueError):
            return []

        # No Y-inversion here as coordinates from VtkRemoteLocalView are already PV-compatible
        rect = [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
        self.clear_edit_selection_overlay()
        self.simple.SetActiveView(self.view)
        self.simple.SetActiveSource(source)
        self._clear_selection_state(source)
        self.simple.SelectSurfaceCells(Rectangle=rect, View=self.view, Modifier=None)
        raw_picked = self._fetch_selected_original_cell_ids(source)
        picked = list(raw_picked)
        self._clear_selection_state(source)
        self.render()
        print(
            "[selection-debug] backend.pick.box "
            f"behavior={behavior!r} rect={rect} raw_count={len(raw_picked)} raw={self._preview_values(raw_picked)} "
            f"accepted_count={len(picked)} accepted={self._preview_values(picked)}"
        )
        picked = self._remap_cell_ids_to_edit_target_dataset(picked, source)
        print(
            "[selection-debug] backend.pick.box.result "
            f"behavior={behavior!r} final_count={len(picked)} final={self._preview_values(picked)}"
        )
        if not picked or behavior != "inside":
            return picked
        return self._filter_cell_ids_inside_rect(source, picked, rect)

    def pick_visible_point_ids(self, x, y, radius=1):
        """Return selected visible point ids around a display-space click."""
        source = self.source
        if self.view is None or source is None:
            return []
        try:
            x = int(round(float(x)))
            y = int(round(float(y)))
        except (TypeError, ValueError):
            return []

        candidates = self._candidate_pick_positions(x, y)
        self.clear_edit_selection_overlay()
        self.simple.SetActiveView(self.view)
        self.simple.SetActiveSource(source)
        picked_result = []
        for px, py in candidates:
            self._clear_selection_state(source)
            rect = [px - radius, py - radius, px + radius, py + radius]
            self.simple.SelectSurfacePoints(
                Rectangle=rect, View=self.view, Modifier=None
            )
            picked_result = self._fetch_selected_original_point_ids(source)
            if picked_result:
                break
        self._clear_selection_state(source)
        self.render()
        return picked_result

    def pick_visible_point_ids_in_rect(self, x0, y0, x1, y1, behavior="touch"):
        """Return selected visible point ids inside a display-space rectangle."""
        source = self.source
        if self.view is None or source is None:
            return []
        try:
            x0 = int(round(float(x0)))
            y0 = int(round(float(y0)))
            x1 = int(round(float(x1)))
            y1 = int(round(float(y1)))
        except (TypeError, ValueError):
            return []

        rect = [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
        self.clear_edit_selection_overlay()
        self.simple.SetActiveView(self.view)
        self.simple.SetActiveSource(source)
        self._clear_selection_state(source)
        self.simple.SelectSurfacePoints(Rectangle=rect, View=self.view, Modifier=None)
        picked = self._fetch_selected_original_point_ids(source)
        self._clear_selection_state(source)
        self.render()
        return picked

    def pick_visible_surface_keys(self, x, y, radius=2):
        """Return boundary face/edge keys touched by a display-space click."""
        try:
            x = int(round(float(x)))
            y = int(round(float(y)))
            radius = int(round(float(radius)))
        except (TypeError, ValueError):
            return []

        rect = [x - radius, y - radius, x + radius, y + radius]
        return self._pick_surface_keys_in_rect(rect, behavior="touch")

    def pick_visible_surface_keys_in_rect(self, x0, y0, x1, y1, behavior="touch"):
        """Return boundary face/edge keys touched by a display-space rectangle."""
        try:
            x0 = int(round(float(x0)))
            y0 = int(round(float(y0)))
            x1 = int(round(float(x1)))
            y1 = int(round(float(y1)))
        except (TypeError, ValueError):
            return []

        rect = [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
        return self._pick_surface_keys_in_rect(rect, behavior=behavior)

    def _filter_cell_ids_inside_rect(self, source, cell_ids, rect):
        """Return only cells whose projected vertices are fully inside the display rect."""
        try:
            dataset = self.servermanager.Fetch(source)
        except Exception:
            return cell_ids

        if dataset is None or self.view is None:
            return cell_ids

        client_view = self.view.GetClientSideObject()
        renderer = client_view.GetRenderer() if client_view is not None else None
        if renderer is None:
            return cell_ids

        xmin, ymin, xmax, ymax = rect
        selected = []
        for cell_id in cell_ids:
            if cell_id < 0 or cell_id >= dataset.GetNumberOfCells():
                continue
            cell = dataset.GetCell(int(cell_id))
            if cell is None:
                continue

            inside = True
            for point_idx in range(cell.GetNumberOfPoints()):
                point = dataset.GetPoint(cell.GetPointId(point_idx))
                renderer.SetWorldPoint(point[0], point[1], point[2], 1.0)
                renderer.WorldToDisplay()
                dx, dy, dz = renderer.GetDisplayPoint()
                if not (isfinite(dx) and isfinite(dy) and isfinite(dz)):
                    inside = False
                    break
                if dx < xmin or dx > xmax or dy < ymin or dy > ymax:
                    inside = False
                    break

            if inside:
                selected.append(int(cell_id))

        return selected

    def _pick_surface_keys_in_rect(self, rect, behavior="touch"):
        """Return boundary keys whose projected geometry intersects/is inside rect."""
        source = self.source
        if self.view is None or source is None:
            return []

        self._last_selection_backend_timing = []
        self.clear_edit_selection_overlay()

        # Fast path: use native ParaView/VTK surface selection on an extracted
        # boundary-surface representation and map selected cells back to source keys.
        native_keys = self._pick_surface_keys_native(rect, behavior=behavior)
        if native_keys:
            print(
                "[selection-debug] backend.pick.surface.native "
                f"behavior={behavior!r} rect={rect} count={len(native_keys)} keys={self._preview_values(native_keys)}"
            )
            return native_keys

        try:
            dataset = self.servermanager.Fetch(source)
        except Exception:
            return []

        if dataset is None:
            return []

        client_view = self.view.GetClientSideObject()
        renderer = client_view.GetRenderer() if client_view is not None else None
        if renderer is None:
            return []

        boundary = self._cached_boundary_elements(dataset)
        if not boundary:
            return []

        inside_only = behavior == "inside"
        picked = []
        for key, element in boundary.items():
            if not self._surface_element_is_visible(
                dataset, element["point_ids"], renderer
            ):
                continue
            projected = self._project_points_to_display(
                dataset, element["point_ids"], renderer
            )
            if not projected:
                continue
            if inside_only:
                if all(self._point_in_rect(point, rect) for point in projected):
                    picked.append(key)
            else:
                if self._polyline_intersects_rect(projected, rect):
                    picked.append(key)
        remapped = self._remap_surface_keys_to_edit_target_dataset(
            picked, source_dataset=dataset
        )
        print(
            "[selection-debug] backend.pick.surface.fallback "
            f"behavior={behavior!r} rect={rect} raw_count={len(picked)} raw={self._preview_values(picked)} "
            f"final_count={len(remapped)} final={self._preview_values(remapped)}"
        )
        return remapped

    def _pick_surface_keys_native(self, rect, behavior="touch"):
        """Native ParaView selection path for visible boundary faces (3D)."""
        phases = []

        def record_phase(name, start):
            phases.append(
                {"name": name, "ms": round((time.perf_counter() - start) * 1000.0, 3)}
            )

        source = self.source
        if self.view is None or source is None:
            return None

        edit_dataset = self._edit_target_dataset
        phase_start = time.perf_counter()
        source_dataset = None
        if edit_dataset is None:
            try:
                source_dataset = self.servermanager.Fetch(source)
            except Exception:
                return None
            edit_dataset = source_dataset
        record_phase("dataset", phase_start)
        if edit_dataset is None:
            return None
        if not hasattr(edit_dataset, "GetNumberOfCells") or not hasattr(
            edit_dataset, "GetCell"
        ):
            return None

        phase_start = time.perf_counter()
        top_dim = max(
            (
                edit_dataset.GetCell(cell_id).GetCellDimension()
                for cell_id in range(edit_dataset.GetNumberOfCells())
            ),
            default=0,
        )
        record_phase("top_dimension", phase_start)
        # Keep old custom path for 2D/1D where ExtractSurface does not target boundary edges.
        if top_dim != 3:
            return None

        # For "inside" behavior, use native touch selection first and refine with geometric check.
        inside_only = behavior == "inside"
        extract = None
        selected_dataset = None
        original_source = source
        original_display = self.display
        original_visibility = (
            int(original_display.Visibility)
            if original_display is not None and hasattr(original_display, "Visibility")
            else None
        )

        try:
            self.simple.SetActiveView(self.view)
            self.simple.SetActiveSource(source)
            self._clear_selection_state(source)

            phase_start = time.perf_counter()
            helper = self._surface_selection_helper_for(source)
            record_phase("surface_helper", phase_start)
            temp_source = helper["source"]
            temp_display = helper["display"]
            temp_display.Visibility = 1
            if original_display is not None and original_visibility is not None:
                original_display.Visibility = 0

            self.simple.SetActiveSource(temp_source)
            self._clear_selection_state(temp_source)
            phase_start = time.perf_counter()
            self.simple.SelectSurfaceCells(
                Rectangle=rect, View=self.view, Modifier=None
            )
            record_phase("select_surface_cells", phase_start)

            phase_start = time.perf_counter()
            extract = self.simple.ExtractSelection(Input=temp_source)
            extract.UpdatePipeline()
            record_phase("extract_selection", phase_start)
            phase_start = time.perf_counter()
            selected_dataset = self.servermanager.Fetch(extract)
            record_phase("fetch_selection", phase_start)
            if source_dataset is None:
                phase_start = time.perf_counter()
                try:
                    source_dataset = self.servermanager.Fetch(source)
                except Exception:
                    source_dataset = edit_dataset
                record_phase("fetch_source_dataset", phase_start)
            phase_start = time.perf_counter()
            keys = self._surface_keys_from_selected_dataset(
                selected_dataset, source_dataset=source_dataset
            )
            record_phase("map_selection_keys", phase_start)
            if keys is None:
                return None

            if inside_only and keys:
                # Refine to inside-only using existing projected containment on this subset.
                phase_start = time.perf_counter()
                client_view = self.view.GetClientSideObject()
                renderer = (
                    client_view.GetRenderer() if client_view is not None else None
                )
                if renderer is not None:
                    inside_keys = []
                    for key in keys:
                        projected = self._project_points_to_display(
                            source_dataset, key, renderer
                        )
                        if projected and all(
                            self._point_in_rect(point, rect) for point in projected
                        ):
                            inside_keys.append(key)
                    keys = inside_keys
                record_phase("inside_refine", phase_start)
            phase_start = time.perf_counter()
            remapped = self._remap_surface_keys_to_edit_target_dataset(
                keys, source_dataset=source_dataset
            )
            record_phase("remap_to_edit_target", phase_start)
            print(
                "[selection-debug] backend.pick.surface.native.result "
                f"behavior={behavior!r} rect={rect} raw_count={len(keys or [])} raw={self._preview_values(keys or [])} "
                f"final_count={len(remapped)} final={self._preview_values(remapped)}"
            )
            return remapped
        except Exception:
            return None
        finally:
            cleanup_start = time.perf_counter()
            try:
                if original_display is not None and original_visibility is not None:
                    original_display.Visibility = original_visibility
            except Exception:
                pass
            try:
                helper = getattr(self, "_surface_selection_helper", None)
                helper_display = (
                    helper.get("display") if isinstance(helper, dict) else None
                )
                if helper_display is not None:
                    helper_display.Visibility = 0
            except Exception:
                pass
            try:
                self.simple.SetActiveSource(original_source)
            except Exception:
                pass
            try:
                if extract is not None:
                    self.simple.Delete(extract)
            except Exception:
                pass
            try:
                self.render()
            except Exception:
                pass
            record_phase("cleanup_render", cleanup_start)
            self._last_selection_backend_timing = phases

    def _cached_boundary_elements(self, dataset):
        """Return cached boundary codimension‑1 elements for *dataset*.
        The cache key is the object's id; this is safe because the VTK dataset
        instance lives as long as the backend holds a reference. If the dataset
        changes (e.g. a new file is loaded) a new id is produced and a fresh
        computation runs.
        """
        if dataset is None:
            return {}
        cache_key = id(dataset)
        cached = getattr(self, "_boundary_cache", {}).get(cache_key)
        if cached is not None:
            return cached
        # Compute and store
        boundary = self._boundary_codim_elements(dataset)
        # Ensure the cache dict exists (it does from __init__)
        cache = getattr(self, "_boundary_cache", None)
        if cache is None:
            cache = {}
            self._boundary_cache = cache
        cache[cache_key] = boundary
        return boundary

    def _clear_boundary_cache(self):
        """Clear boundary cache for both full and lightweight backend instances."""
        cache = getattr(self, "_boundary_cache", None)
        if cache is None:
            self._boundary_cache = {}
            return
        cache.clear()

    def _surface_selection_helper_for(self, source):
        """Return a cached ExtractSurface proxy used for robust surface selection."""
        self._clear_surface_selection_helper()
        self._clear_boundary_cache()

        temp_source = self.simple.ExtractSurface(Input=source)
        for prop_name, prop_value in (
            ("PassThroughPointIds", 1),
            ("PassThroughCellIds", 1),
            ("PassThroughPointIdsArrayName", "vtkOriginalPointIds"),
            ("PassThroughCellIdsArrayName", "vtkOriginalCellIds"),
        ):
            if hasattr(temp_source, prop_name):
                try:
                    setattr(temp_source, prop_name, prop_value)
                except Exception:
                    pass
        temp_source.UpdatePipeline()

        temp_display = self.simple.Show(temp_source, self.view)
        temp_display.Visibility = 0
        try:
            self._disable_scalar_coloring(temp_display, hide_unused_scalar_bars=False)
        except Exception:
            pass
        self._surface_selection_helper = {
            "input": source,
            "source": temp_source,
            "display": temp_display,
        }
        return self._surface_selection_helper

    def _clear_surface_selection_helper(self):
        """Delete the cached selection-only ExtractSurface proxy, if any."""
        helper = getattr(self, "_surface_selection_helper", None)
        if not isinstance(helper, dict):
            self._surface_selection_helper = None
            return

        source = helper.get("source")
        try:
            if source is not None and self.view is not None:
                self.simple.Hide(source, self.view)
        except Exception:
            pass
        try:
            if source is not None:
                self.simple.Delete(source)
        except Exception:
            pass
        self._surface_selection_helper = None

    @staticmethod
    def _surface_keys_from_selected_dataset(selected_dataset, source_dataset=None):
        """Map selected ExtractSurface cells back to original source point-id keys."""
        selected_blocks = ParaViewBackend._iter_leaf_datasets(selected_dataset)
        if not selected_blocks:
            return []

        source_point_indexes = None
        source_boundary = (
            ParaViewBackend._boundary_codim_elements(source_dataset)
            if source_dataset is not None
            and hasattr(source_dataset, "GetNumberOfCells")
            else {}
        )
        boundary_point_to_keys = {}
        for boundary_key in source_boundary:
            for point_id in boundary_key:
                boundary_point_to_keys.setdefault(int(point_id), set()).add(
                    boundary_key
                )

        def key_matches_source_boundary(key):
            if not key or not source_boundary:
                return True
            if key in source_boundary:
                return True
            key_set = set(key)
            candidate_sets = [
                boundary_point_to_keys.get(int(point_id), set()) for point_id in key_set
            ]
            return bool(set.intersection(*candidate_sets) if candidate_sets else set())

        def coordinate_key(block, cell):
            nonlocal source_point_indexes
            if source_dataset is None or not hasattr(
                source_dataset, "GetNumberOfPoints"
            ):
                return None
            if source_point_indexes is None:
                source_point_indexes = ParaViewBackend._point_coordinate_indexes(
                    source_dataset
                )
            mapped = []
            for point_idx in range(cell.GetNumberOfPoints()):
                point = block.GetPoint(cell.GetPointId(point_idx))
                point_id = ParaViewBackend._lookup_point_coordinate(
                    source_point_indexes, point
                )
                if point_id is None:
                    return None
                mapped.append(int(point_id))
            return tuple(sorted(mapped))

        keys = []
        for block in selected_blocks:
            if block is None or not hasattr(block, "GetNumberOfCells"):
                continue

            point_data = (
                block.GetPointData() if hasattr(block, "GetPointData") else None
            )
            original_point_array = None
            for name in (
                "vtkOriginalPointIds",
                "OriginalPointIds",
                "vtkOriginalPointId",
                "vtkOriginalIds",
            ):
                array = point_data.GetArray(name) if point_data is not None else None
                if array is not None:
                    original_point_array = array
                    break

            if original_point_array is None and source_point_indexes is None:
                if source_dataset is None or not hasattr(
                    source_dataset, "GetNumberOfPoints"
                ):
                    return None
                source_point_indexes = ParaViewBackend._point_coordinate_indexes(
                    source_dataset
                )

            for cell_id in range(block.GetNumberOfCells()):
                cell = block.GetCell(cell_id)
                if cell is None or cell.GetNumberOfPoints() <= 0:
                    continue
                try:
                    if original_point_array is not None:
                        key = tuple(
                            sorted(
                                int(
                                    original_point_array.GetTuple1(
                                        cell.GetPointId(point_idx)
                                    )
                                )
                                for point_idx in range(cell.GetNumberOfPoints())
                            )
                        )
                        if not key_matches_source_boundary(key):
                            mapped_key = coordinate_key(block, cell)
                            if mapped_key is not None:
                                key = mapped_key
                    else:
                        key = coordinate_key(block, cell) or ()
                except Exception:
                    continue
                if key:
                    keys.append(key)

        # Preserve deterministic order while deduplicating.
        seen = set()
        deduped = []
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return ParaViewBackend._normalize_surface_keys_to_source_boundary(
            deduped, source_dataset=source_dataset
        )

    @staticmethod
    def _normalize_surface_keys_to_source_boundary(keys, source_dataset=None):
        """Resolve partial picked keys to canonical source boundary keys when possible."""
        if not keys or source_dataset is None:
            return keys or []

        boundary = ParaViewBackend._boundary_codim_elements(source_dataset)
        if not boundary:
            return keys

        point_to_boundary_keys = {}
        for boundary_key in boundary:
            for point_id in boundary_key:
                point_to_boundary_keys.setdefault(int(point_id), set()).add(
                    boundary_key
                )

        normalized = []
        for key in keys:
            if key in boundary:
                normalized.append(key)
                continue

            key_set = set(key)
            if not key_set:
                continue

            # ParaView may triangulate selected surface faces. Map those partial keys
            # back to the original boundary face key by subset match.
            candidate_sets = [
                point_to_boundary_keys.get(int(point_id), set()) for point_id in key_set
            ]
            candidates = set.intersection(*candidate_sets) if candidate_sets else set()
            if not candidates:
                normalized.append(key)
                continue

            # Prefer the smallest superset (e.g. triangle -> quad) and keep deterministic.
            normalized.append(
                sorted(candidates, key=lambda candidate: (len(candidate), candidate))[0]
            )

        # Preserve order with dedupe.
        deduped = []
        seen = set()
        for key in normalized:
            if key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return deduped

    @staticmethod
    def _boundary_codim_elements(dataset):
        """Return boundary codimension-one entities keyed by sorted point ids."""
        cell_count = dataset.GetNumberOfCells()
        top_dim = max(
            (
                dataset.GetCell(cell_id).GetCellDimension()
                for cell_id in range(cell_count)
            ),
            default=0,
        )
        if top_dim < 2:
            return {}

        counts = {}
        metadata = {}
        for cell_id in range(cell_count):
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
                ordered_ids = tuple(
                    int(subcell.GetPointId(point_id))
                    for point_id in range(subcell.GetNumberOfPoints())
                )
                key = tuple(sorted(ordered_ids))
                counts[key] = counts.get(key, 0) + 1
                if key not in metadata:
                    metadata[key] = {"point_ids": ordered_ids}

        return {key: metadata[key] for key, count in counts.items() if count == 1}

    @staticmethod
    def _project_points_to_display(dataset, point_ids, renderer):
        projected = []
        for point_id in point_ids:
            point = dataset.GetPoint(int(point_id))
            renderer.SetWorldPoint(point[0], point[1], point[2], 1.0)
            renderer.WorldToDisplay()
            dx, dy, dz = renderer.GetDisplayPoint()
            if not (isfinite(dx) and isfinite(dy) and isfinite(dz)):
                return []
            projected.append((float(dx), float(dy)))
        return projected

    def _surface_element_is_visible(self, dataset, point_ids, renderer):
        """Return True when the element centroid is visible in the current depth buffer."""
        if dataset is None or renderer is None or not point_ids:
            return False

        points = []
        for point_id in point_ids:
            try:
                points.append(dataset.GetPoint(int(point_id)))
            except Exception:
                return False
        if not points:
            return False

        count = float(len(points))
        centroid = (
            sum(point[0] for point in points) / count,
            sum(point[1] for point in points) / count,
            sum(point[2] for point in points) / count,
        )
        projected = self._project_world_point_to_display(renderer, centroid)
        if projected is None:
            return False
        return self._is_display_depth_visible(
            renderer, projected[0], projected[1], projected[2]
        )

    def _filter_visible_cell_ids_by_depth(self, source, cell_ids):
        """Keep only cell ids with centroid visible from the current camera."""
        if not cell_ids:
            return []

        renderer = self._get_renderer()
        if renderer is None:
            return list(cell_ids)

        try:
            dataset = self.servermanager.Fetch(source)
        except Exception:
            return list(cell_ids)
        if dataset is None:
            return list(cell_ids)

        visible_ids = []
        for cell_id in cell_ids:
            try:
                cid = int(cell_id)
            except (TypeError, ValueError):
                continue
            if cid < 0 or cid >= dataset.GetNumberOfCells():
                continue

            cell = dataset.GetCell(cid)
            if cell is None or cell.GetNumberOfPoints() <= 0:
                continue

            points = []
            for point_idx in range(cell.GetNumberOfPoints()):
                points.append(dataset.GetPoint(cell.GetPointId(point_idx)))
            count = float(len(points))
            centroid = (
                sum(point[0] for point in points) / count,
                sum(point[1] for point in points) / count,
                sum(point[2] for point in points) / count,
            )
            projected = self._project_world_point_to_display(renderer, centroid)
            if projected is None:
                continue
            if self._is_display_depth_visible(
                renderer, projected[0], projected[1], projected[2]
            ):
                visible_ids.append(cid)

        return visible_ids

    def _get_renderer(self):
        if self.view is None:
            return None
        client_view = self.view.GetClientSideObject()
        if client_view is None:
            return None
        return client_view.GetRenderer()

    @staticmethod
    def _project_world_point_to_display(renderer, point):
        """Project one 3D world point to display coords and return (x, y, z)."""
        try:
            renderer.SetWorldPoint(
                float(point[0]), float(point[1]), float(point[2]), 1.0
            )
            renderer.WorldToDisplay()
            dx, dy, dz = renderer.GetDisplayPoint()
        except Exception:
            return None
        if not (isfinite(dx) and isfinite(dy) and isfinite(dz)):
            return None
        return (float(dx), float(dy), float(dz))

    @staticmethod
    def _is_display_depth_visible(renderer, x, y, z, tolerance=1e-4):
        """Return True when display depth ``z`` is on/near the visible z-buffer value."""
        if renderer is None:
            return True
        try:
            buffer_z = float(renderer.GetZ(int(round(x)), int(round(y))))
        except Exception:
            return True
        if not isfinite(buffer_z):
            return True
        # Smaller z is closer to camera in display coordinates.
        return float(z) <= buffer_z + float(tolerance)

    @staticmethod
    def _point_in_rect(point, rect):
        x, y = point
        xmin, ymin, xmax, ymax = rect
        return xmin <= x <= xmax and ymin <= y <= ymax

    def _polyline_intersects_rect(self, points, rect):
        """Return True if polygon/polyline projected points intersect a screen rect."""
        xmin, ymin, xmax, ymax = rect
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        if max(xs) < xmin or min(xs) > xmax or max(ys) < ymin or min(ys) > ymax:
            return False

        if any(self._point_in_rect(point, rect) for point in points):
            return True

        rect_corners = [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)]
        if len(points) >= 3 and any(
            self._point_in_polygon(corner, points) for corner in rect_corners
        ):
            return True

        edges = list(zip(points, points[1:]))
        if len(points) >= 3:
            edges.append((points[-1], points[0]))

        rect_edges = [
            ((xmin, ymin), (xmax, ymin)),
            ((xmax, ymin), (xmax, ymax)),
            ((xmax, ymax), (xmin, ymax)),
            ((xmin, ymax), (xmin, ymin)),
        ]
        for segment in edges:
            if any(
                self._segments_intersect(segment[0], segment[1], edge[0], edge[1])
                for edge in rect_edges
            ):
                return True

        return False

    @staticmethod
    def _point_in_polygon(point, polygon):
        """Ray-casting point-in-polygon test in 2D."""
        x, y = point
        inside = False
        j = len(polygon) - 1
        for i in range(len(polygon)):
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            intersects = ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            )
            if intersects:
                inside = not inside
            j = i
        return inside

    @staticmethod
    def _segments_intersect(p1, p2, q1, q2):
        """Return True if 2D segments p1-p2 and q1-q2 intersect."""

        def orientation(a, b, c):
            value = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])
            if abs(value) < 1e-9:
                return 0
            return 1 if value > 0 else 2

        def on_segment(a, b, c):
            return (
                min(a[0], c[0]) - 1e-9 <= b[0] <= max(a[0], c[0]) + 1e-9
                and min(a[1], c[1]) - 1e-9 <= b[1] <= max(a[1], c[1]) + 1e-9
            )

        o1 = orientation(p1, p2, q1)
        o2 = orientation(p1, p2, q2)
        o3 = orientation(q1, q2, p1)
        o4 = orientation(q1, q2, p2)

        if o1 != o2 and o3 != o4:
            return True
        if o1 == 0 and on_segment(p1, q1, p2):
            return True
        if o2 == 0 and on_segment(p1, q2, p2):
            return True
        if o3 == 0 and on_segment(q1, p1, q2):
            return True
        if o4 == 0 and on_segment(q1, p2, q2):
            return True
        return False

    def get_pick_debug_info(self, x, y, radius=4):
        """Return debug information for the current click-to-pick attempt."""
        width, height = self.view.ViewSize if self.view is not None else (0, 0)
        try:
            px = int(round(float(x)))
            py = int(round(float(y)))
        except (TypeError, ValueError):
            return {
                "raw_pointer": {"x": x, "y": y},
                "view_size": {"width": int(width or 0), "height": int(height or 0)},
                "pick_radius": int(radius),
                "candidate_positions": [],
            }

        candidates = self._candidate_pick_positions(px, py)
        return {
            "raw_pointer": {"x": px, "y": py},
            "view_size": {"width": int(width or 0), "height": int(height or 0)},
            "pick_radius": int(radius),
            "candidate_positions": [
                {
                    "x": cx,
                    "y": cy,
                    "rect": [cx - radius, cy - radius, cx + radius, cy + radius],
                }
                for cx, cy in candidates
            ],
        }

    def _candidate_pick_positions(self, x, y):
        """Return plausible pixel coordinates for the current event convention."""
        width, height = self.view.ViewSize if self.view is not None else (0, 0)
        width = int(width or 0)
        height = int(height or 0)

        candidates = []

        def add(px, py):
            try:
                px = int(round(float(px)))
                py = int(round(float(py)))
            except (TypeError, ValueError):
                return
            key = (px, py)
            if key not in candidates:
                candidates.append(key)

        # In modern Trame/ParaView, the event Y is often already inverted (0=bottom).
        # We try the raw coordinate first.
        add(x, y)

        # Fallback to inverted if raw fails
        if height > 0:
            add(x, height - y)

        if width > 0 and height > 0 and 0 <= x <= 1 and 0 <= y <= 1:
            # Normalized coordinates fallback
            add(x * width, y * height)
            add(x * width, (1 - y) * height)

        return candidates

    def _fetch_selected_original_cell_ids(self, source):
        """Extract selected original cell ids from the source selection."""
        try:
            extract = self.simple.ExtractSelection(Input=source)
            extract.UpdatePipeline()
            dataset = self.servermanager.Fetch(extract)
        except Exception:
            return []

        if dataset is None:
            return []

        cell_data = dataset.GetCellData()
        candidate_names = [
            "vtkOriginalCellIds",
            "originalCellIds",
            "OriginalCellIds",
        ]

        selected_ids = []
        for name in candidate_names:
            array = cell_data.GetArray(name)
            if array is not None:
                selected_ids = [
                    int(array.GetTuple1(i)) for i in range(array.GetNumberOfTuples())
                ]
                break

        if not selected_ids:
            try:
                source_dataset = self.servermanager.Fetch(source)
            except Exception:
                source_dataset = None
            selected_ids = self._source_cell_ids_from_selected_dataset(
                dataset, source_dataset
            )
        print(
            "[selection-debug] backend.extract.cell_ids "
            f"selected_cells={dataset.GetNumberOfCells()} mapped_count={len(selected_ids)} "
            f"mapped={self._preview_values(selected_ids)}"
        )

        try:
            self.simple.Delete(extract)
        except Exception:
            pass

        return selected_ids

    def _remap_cell_ids_to_edit_target_dataset(self, cell_ids, source):
        """Normalize picked source cell IDs onto the active edit-session dataset."""
        picked_ids = [int(cell_id) for cell_id in (cell_ids or [])]
        target_dataset = getattr(self, "_edit_target_dataset", None)
        if target_dataset is None or not picked_ids:
            return picked_ids

        try:
            source_dataset = self.servermanager.Fetch(source)
        except Exception:
            source_dataset = None
        remapped = self._remap_cell_ids_between_datasets(
            picked_ids, source_dataset, target_dataset
        )
        print(
            "[selection-debug] backend.remap.cells "
            f"input_count={len(picked_ids)} input={self._preview_values(picked_ids)} "
            f"remapped_count={len(remapped)} remapped={self._preview_values(remapped)}"
        )
        return remapped if remapped else picked_ids

    def _remap_surface_keys_to_edit_target_dataset(self, keys, source_dataset=None):
        """Normalize picked source boundary keys onto edit-session point IDs."""
        picked_keys = [tuple(key) for key in (keys or []) if key]
        target_dataset = getattr(self, "_edit_target_dataset", None)
        if target_dataset is None or source_dataset is None or not picked_keys:
            return picked_keys
        if source_dataset is target_dataset:
            return picked_keys

        point_id_map = self._point_id_map_between_datasets(
            source_dataset, target_dataset
        )
        if not point_id_map:
            return picked_keys

        remapped = []
        for key in picked_keys:
            mapped = [point_id_map.get(int(source_point_id)) for source_point_id in key]
            if any(point_id is None for point_id in mapped):
                continue
            remapped.append(tuple(sorted(mapped)))

        if not remapped:
            return picked_keys
        normalized = self._dedupe_ordered(remapped)
        print(
            "[selection-debug] backend.remap.surface "
            f"input_count={len(picked_keys)} input={self._preview_values(picked_keys)} "
            f"remapped_count={len(remapped)} remapped={self._preview_values(remapped)} "
            f"normalized_count={len(normalized)} normalized={self._preview_values(normalized)}"
        )
        return normalized

    @classmethod
    def _point_id_map_between_datasets(cls, source_dataset, target_dataset):
        """Map source point IDs to target point IDs by tolerant coordinates."""
        if source_dataset is None or target_dataset is None:
            return {}
        try:
            source_count = source_dataset.GetNumberOfPoints()
            target_indexes = cls._point_coordinate_indexes(target_dataset)
        except Exception:
            return {}
        if not target_indexes:
            return {}

        point_id_map = {}
        for source_point_id in range(source_count):
            try:
                point = source_dataset.GetPoint(source_point_id)
            except Exception:
                continue
            target_point_id = cls._lookup_point_coordinate(target_indexes, point)
            if target_point_id is not None:
                point_id_map[int(source_point_id)] = int(target_point_id)
        return point_id_map

    @staticmethod
    def _dedupe_ordered(values):
        deduped = []
        seen = set()
        for value in values or []:
            if value in seen:
                continue
            seen.add(value)
            deduped.append(value)
        return deduped

    @staticmethod
    def _safe_dataset_point(dataset, point_id):
        try:
            point = dataset.GetPoint(int(point_id))
        except Exception:
            return None
        if point is None:
            return None
        return ParaViewBackend._rounded_point_key(point)

    @staticmethod
    def _point_coordinate_index(dataset):
        indexes = ParaViewBackend._point_coordinate_indexes(dataset)
        return indexes[0] if indexes else {}

    @staticmethod
    def _point_coordinate_indexes(dataset):
        if dataset is None or not hasattr(dataset, "GetNumberOfPoints"):
            return []
        indexes = [{} for _decimal_places in POINT_COORDINATE_DECIMALS]
        for point_id in range(dataset.GetNumberOfPoints()):
            try:
                point = dataset.GetPoint(point_id)
            except Exception:
                continue
            if point is None:
                continue
            for index, decimal_places in zip(indexes, POINT_COORDINATE_DECIMALS):
                key = ParaViewBackend._rounded_point_key(point, decimal_places)
                index.setdefault(key, int(point_id))
        return indexes

    @staticmethod
    def _lookup_point_coordinate(indexes, point):
        if not indexes or point is None:
            return None
        for index, decimal_places in zip(indexes, POINT_COORDINATE_DECIMALS):
            key = ParaViewBackend._rounded_point_key(point, decimal_places)
            point_id = index.get(key)
            if point_id is not None:
                return int(point_id)
        return None

    @staticmethod
    def _rounded_point_key(point, decimals=12):
        return (
            round(float(point[0]), decimals),
            round(float(point[1]), decimals),
            round(float(point[2]), decimals),
        )

    @staticmethod
    def _iter_leaf_datasets(dataset):
        if dataset is None:
            return []
        if hasattr(dataset, "GetNumberOfBlocks"):
            blocks = []
            try:
                block_count = dataset.GetNumberOfBlocks()
            except Exception:
                return []
            for block_id in range(block_count):
                try:
                    block = dataset.GetBlock(block_id)
                except Exception:
                    continue
                blocks.extend(ParaViewBackend._iter_leaf_datasets(block))
            return blocks
        if not hasattr(dataset, "GetNumberOfCells"):
            return []
        try:
            return [dataset] if dataset.GetNumberOfCells() > 0 else []
        except Exception:
            return []

    @staticmethod
    def _cell_coordinate_key(dataset, cell):
        if dataset is None or cell is None:
            return None
        coords = []
        try:
            num_points = int(cell.GetNumberOfPoints())
        except Exception:
            return None
        for point_idx in range(num_points):
            try:
                point_id = int(cell.GetPointId(point_idx))
            except Exception:
                return None
            point = ParaViewBackend._safe_dataset_point(dataset, point_id)
            if point is None:
                return None
            coords.append(point)
        if not coords:
            return None
        return tuple(sorted(coords))

    @staticmethod
    def _remap_cell_ids_between_datasets(cell_ids, source_dataset, target_dataset):
        """Map source-dataset cell ids to target-dataset ids by cell geometry."""
        if not cell_ids:
            return []
        if source_dataset is None or target_dataset is None:
            return [int(cell_id) for cell_id in cell_ids]
        if not hasattr(source_dataset, "GetCell") or not hasattr(
            target_dataset, "GetCell"
        ):
            return [int(cell_id) for cell_id in cell_ids]

        target_cell_map = {}
        target_count = target_dataset.GetNumberOfCells()
        for target_cell_id in range(target_count):
            target_cell = target_dataset.GetCell(target_cell_id)
            key = ParaViewBackend._cell_coordinate_key(target_dataset, target_cell)
            if key is None:
                continue
            target_cell_map.setdefault(key, int(target_cell_id))

        remapped = []
        for cell_id in cell_ids:
            mapped_id = None
            try:
                source_cell_id = int(cell_id)
            except (TypeError, ValueError):
                continue
            if 0 <= source_cell_id < source_dataset.GetNumberOfCells():
                source_cell = source_dataset.GetCell(source_cell_id)
                source_key = ParaViewBackend._cell_coordinate_key(
                    source_dataset, source_cell
                )
                if source_key is not None:
                    mapped_id = target_cell_map.get(source_key)
            if mapped_id is None and 0 <= source_cell_id < target_count:
                mapped_id = int(source_cell_id)
            if mapped_id is not None:
                remapped.append(int(mapped_id))

        deduped = []
        seen = set()
        for cell_id in remapped:
            if cell_id in seen:
                continue
            seen.add(cell_id)
            deduped.append(cell_id)
        return deduped

    @staticmethod
    def _source_cell_ids_from_selected_dataset(selected_dataset, source_dataset):
        """Best-effort map selected cells back to source cell ids by geometry."""
        if selected_dataset is None or source_dataset is None:
            return []
        if not hasattr(source_dataset, "GetNumberOfCells"):
            return []
        if not hasattr(source_dataset, "GetPoint"):
            return []
        selected_blocks = ParaViewBackend._iter_leaf_datasets(selected_dataset)
        if not selected_blocks:
            return []

        try:
            source_point_count = source_dataset.GetNumberOfPoints()
        except Exception:
            return []
        if source_point_count <= 0:
            return []
        source_point_indexes = ParaViewBackend._point_coordinate_indexes(source_dataset)

        source_cell_count = source_dataset.GetNumberOfCells()
        source_cell_map = {}
        top_dim = 0
        for source_cell_id in range(source_cell_count):
            source_cell = source_dataset.GetCell(source_cell_id)
            if source_cell is None:
                continue
            try:
                top_dim = max(top_dim, int(source_cell.GetCellDimension()))
            except Exception:
                pass
            source_key = tuple(
                sorted(
                    int(source_cell.GetPointId(point_idx))
                    for point_idx in range(source_cell.GetNumberOfPoints())
                )
            )
            source_cell_map[source_key] = int(source_cell_id)

        boundary_to_top_cells = {}
        if top_dim >= 2:
            for source_cell_id in range(source_cell_count):
                source_cell = source_dataset.GetCell(source_cell_id)
                if source_cell is None:
                    continue
                try:
                    cell_dim = int(source_cell.GetCellDimension())
                except Exception:
                    continue
                if cell_dim != top_dim:
                    continue

                if top_dim == 3:
                    subcell_count = source_cell.GetNumberOfFaces()
                    getter = source_cell.GetFace
                else:
                    subcell_count = source_cell.GetNumberOfEdges()
                    getter = source_cell.GetEdge

                for subcell_idx in range(subcell_count):
                    subcell = getter(subcell_idx)
                    if subcell is None:
                        continue
                    boundary_key = tuple(
                        sorted(
                            int(subcell.GetPointId(point_idx))
                            for point_idx in range(subcell.GetNumberOfPoints())
                        )
                    )
                    if not boundary_key:
                        continue
                    boundary_to_top_cells.setdefault(boundary_key, set()).add(
                        int(source_cell_id)
                    )

        mapped = []
        for block in selected_blocks:
            if not hasattr(block, "GetPoint") or not hasattr(block, "GetCell"):
                continue
            for selected_cell_id in range(block.GetNumberOfCells()):
                selected_cell = block.GetCell(selected_cell_id)
                if selected_cell is None:
                    continue

                mapped_point_ids = []
                failed = False
                for point_idx in range(selected_cell.GetNumberOfPoints()):
                    point = block.GetPoint(selected_cell.GetPointId(point_idx))
                    if point is None:
                        failed = True
                        break
                    source_point_id = ParaViewBackend._lookup_point_coordinate(
                        source_point_indexes, point
                    )
                    if source_point_id is None:
                        failed = True
                        break
                    mapped_point_ids.append(int(source_point_id))

                if failed or not mapped_point_ids:
                    continue
                cell_key = tuple(sorted(mapped_point_ids))
                source_cell_id = source_cell_map.get(cell_key)
                if source_cell_id is not None:
                    mapped.append(int(source_cell_id))
                    continue

                owners = boundary_to_top_cells.get(cell_key)
                if owners:
                    mapped.extend(sorted(int(owner) for owner in owners))
                    continue

                # Selected surface can be triangulated while source boundary remains
                # polygonal; resolve by subset match.
                key_set = set(cell_key)
                if key_set:
                    matched = []
                    for boundary_key, owner_ids in boundary_to_top_cells.items():
                        if key_set.issubset(boundary_key):
                            matched.extend(int(owner) for owner in owner_ids)
                    if matched:
                        mapped.extend(sorted(set(matched)))

        # Deduplicate while preserving order.
        deduped = []
        seen = set()
        for cell_id in mapped:
            if cell_id in seen:
                continue
            seen.add(cell_id)
            deduped.append(cell_id)
        return deduped

    def _fetch_selected_original_point_ids(self, source):
        """Extract selected original point ids from the source selection."""
        try:
            extract = self.simple.ExtractSelection(Input=source)
            extract.UpdatePipeline()
            dataset = self.servermanager.Fetch(extract)
        except Exception:
            return []

        if dataset is None:
            return []

        point_data = dataset.GetPointData()
        candidate_names = [
            "vtkOriginalPointIds",
            "originalPointIds",
            "OriginalPointIds",
        ]

        selected_ids = []
        for name in candidate_names:
            array = point_data.GetArray(name)
            if array is not None:
                selected_ids = [
                    int(array.GetTuple1(i)) for i in range(array.GetNumberOfTuples())
                ]
                break

        try:
            self.simple.Delete(extract)
        except Exception:
            pass

        return selected_ids

    def _count_cells_by_dim(self, data, dim_counts):
        """Recursively count cells by dimension in a dataset or composite block."""
        if hasattr(data, "GetNumberOfBlocks"):  # vtkMultiBlockDataSet
            for i in range(data.GetNumberOfBlocks()):
                block = data.GetBlock(i)
                if block:
                    self._count_cells_by_dim(block, dim_counts)
        elif self._count_cells_by_intrinsic_dim(data, dim_counts):
            return
        elif hasattr(data, "IsA") and data.IsA("vtkCompositeDataSet"):
            it = data.NewIterator()
            it.InitTraversal()
            while not it.IsDoneWithTraversal():
                block = it.GetCurrentDataObject()
                if block:
                    self._count_cells_by_dim(block, dim_counts)
                it.Next()
        elif hasattr(data, "IsA") and data.IsA("vtkPolyData"):
            dim_counts[0] += data.GetNumberOfVerts()
            dim_counts[1] += data.GetNumberOfLines()
            dim_counts[2] += data.GetNumberOfPolys() + data.GetNumberOfStrips()
        elif hasattr(data, "IsA") and data.IsA("vtkUnstructuredGrid"):
            ctypes = vtkCellTypes()
            data.GetCellTypes(ctypes)
            for i in range(ctypes.GetNumberOfTypes()):
                ct = ctypes.GetCellType(i)
                count = data.GetNumberOfCellsOfType(ct)
                dim = vtkCellTypeUtilities.GetDimension(ct)
                if dim in dim_counts:
                    dim_counts[dim] += count
        elif hasattr(data, "IsA") and data.IsA("vtkDataSet"):
            # Fallback for ImageData, RectilinearGrid, etc. where all cells are same type
            if data.GetNumberOfCells() > 0:
                ct = data.GetCellType(0)
                dim = vtkCellTypeUtilities.GetDimension(ct)
                if dim in dim_counts:
                    dim_counts[dim] += data.GetNumberOfCells()

    @staticmethod
    def _count_cells_by_intrinsic_dim(data, dim_counts):
        """Count concrete cells using each cell's intrinsic dimension."""
        if not hasattr(data, "GetNumberOfCells") or not hasattr(data, "GetCell"):
            return False

        try:
            cell_count = data.GetNumberOfCells()
        except Exception:
            return False

        counted = False
        for cell_id in range(cell_count):
            try:
                cell = data.GetCell(cell_id)
                dim = int(cell.GetCellDimension())
            except Exception:
                continue
            if dim in dim_counts:
                dim_counts[dim] += 1
                counted = True
        return counted or cell_count == 0

    def _get_detailed_cell_stats(self, source):
        """Return detailed cell breakdown by intrinsic dimension."""
        try:
            data = self.servermanager.Fetch(source)
            if data is None:
                return []

            dim_counts = {0: 0, 1: 0, 2: 0, 3: 0}
            self._count_cells_by_dim(data, dim_counts)

            res = []
            if dim_counts[3] > 0:
                res.append({"label": "Volume Cells", "value": str(dim_counts[3])})
            if dim_counts[2] > 0:
                res.append({"label": "Surface Cells", "value": str(dim_counts[2])})
            if dim_counts[1] > 0:
                res.append({"label": "Edge Cells", "value": str(dim_counts[1])})
            if dim_counts[0] > 0:
                res.append({"label": "Vertex Cells", "value": str(dim_counts[0])})
            return res
        except Exception:
            return []

    def get_ui_state(self):
        """Return lightweight UI metadata for the current ParaView selection."""
        source = self.source
        if source is None:
            return {
                "pipeline_items": [],
                "active_pipeline_item": None,
                "active_source_label": "",
                "active_source_type": "",
                "active_source_kind": "Reader Type",
                "active_parent_label": "",
                "source_path": "",
                "point_arrays": [],
                "cell_arrays": [],
                "data_stats": [],
                "source_properties": [],
                "display_properties": [],
                "show_calculator_help": False,
                "calculator_attribute_type": "",
                "calculator_input_variables": [],
                "calculator_coordinate_variables": ["coordsX", "coordsY", "coordsZ"],
                "active_visibility": True,
                "selected_array": ARRAY_SOLID,
                "representation": "Surface with Edges",
                "show_cells": True,
                "show_faces": True,
                "color_controls_enabled": False,
                "color_range_min": "",
                "color_range_max": "",
                "color_bar_visible": False,
                "orientation_axes_visible": self._orientation_axes_visible(),
                "categorical_coloring": False,
            }

        data_information = source.GetDataInformation()
        point_items = self._collect_array_items(
            data_information.GetPointDataInformation(), "POINTS"
        )
        cell_items = self._collect_array_items(
            data_information.GetCellDataInformation(), "CELLS"
        )

        active_node = self._get_active_node()
        filename = active_node["filename"]
        relative_filename = self._relative_path(filename)
        active_label = active_node.get("label") or os.path.basename(
            relative_filename or filename or "source"
        )
        xml_name = ""
        if hasattr(source, "SMProxy") and source.SMProxy is not None:
            xml_name = source.SMProxy.GetXMLName() or ""

        stats = [
            {"label": "Points", "value": str(data_information.GetNumberOfPoints())},
            {"label": "Cells", "value": str(data_information.GetNumberOfCells())},
        ]

        if data_information.GetNumberOfCells() > 0:
            stats.extend(self._get_detailed_cell_stats(source))

        stats.extend(
            [
                {"label": "Point Arrays", "value": str(len(point_items))},
                {"label": "Cell Arrays", "value": str(len(cell_items))},
            ]
        )

        color_state = self.get_color_control_state()
        dimension_visibility = active_node.get("cell_dimension_visibility") or {
            "cells": True,
            "faces": True,
        }
        show_cells = bool(
            dimension_visibility.get("cells", dimension_visibility.get("volume", True))
        )
        show_faces = bool(
            dimension_visibility.get("faces", dimension_visibility.get("surface", True))
        )
        return {
            "pipeline_items": [
                {
                    "text": node.get("label")
                    or os.path.basename(node.get("filename") or "source"),
                    "value": node["id"],
                    "node_icon": self._pipeline_icon(node),
                    "visibility_icon": (
                        "mdi-eye-outline"
                        if node["display"] is not None
                        and bool(node.get("visibility", node["display"].Visibility))
                        else "mdi-eye-off-outline"
                    ),
                    "depth": self._pipeline_depth(node),
                }
                for node in self.pipeline_nodes
            ],
            "active_pipeline_item": self.active_node_id,
            "active_source_label": active_label,
            "active_source_type": xml_name or source.__class__.__name__,
            "active_source_kind": self._active_kind_label(),
            "active_parent_label": self._active_parent_label(),
            "source_path": relative_filename or "",
            "point_arrays": point_items,
            "cell_arrays": cell_items,
            "data_stats": stats,
            "source_properties": self.property_inspector.tag_property_scope(
                self.property_inspector.collect_proxy_properties(source), "source"
            ),
            "display_properties": self.property_inspector.tag_property_scope(
                self.property_inspector.collect_proxy_properties(
                    self.display, scope="display"
                ),
                "display",
            ),
            "show_calculator_help": self._is_active_calculator(),
            "calculator_attribute_type": self._calculator_attribute_type(),
            "calculator_input_variables": self._calculator_input_variables(),
            "calculator_coordinate_variables": ["coordsX", "coordsY", "coordsZ"],
            "active_visibility": (
                self.get_visibility(self.active_node_id)
                if self.active_node_id
                else True
            ),
            "selected_array": self._get_selected_array(),
            "representation": self._get_representation(),
            "show_cells": show_cells,
            "show_faces": show_faces,
            **color_state,
            **self.get_time_state(),
        }

    def apply_property_changes(self, source_properties, display_properties):
        """Apply edited property values to the active ParaView source/display proxies."""
        self.property_inspector.apply_proxy_property_changes(
            self.source, source_properties
        )
        self.property_inspector.apply_proxy_property_changes(
            self.display, display_properties
        )

        if self.source is not None:
            self.source.UpdatePipeline()
        self.render()

    def _get_active_node(self) -> PipelineNode | None:
        """Return the active pipeline node."""
        return self._find_node(self.active_node_id)

    def _active_kind_label(self):
        """Return a UI label describing the active node kind."""
        node = self._get_active_node()
        if node is None:
            return "Reader Type"
        return "Filter Type" if node.get("kind") == "filter" else "Reader Type"

    def _active_parent_label(self):
        """Return the parent pipeline label for the active node when available."""
        node = self._get_active_node()
        if node is None or not node.get("parent_id"):
            return ""
        parent = self._find_node(node["parent_id"])
        if parent is None:
            return ""
        return parent.get("label") or os.path.basename(
            parent.get("filename") or "source"
        )

    def _is_active_calculator(self):
        """Return True when the active node is a Calculator filter."""
        node = self._get_active_node()
        if node is None:
            return False
        if node.get("filter_key") == "calculator":
            return True
        source = node.get("source")
        if source is None or not hasattr(source, "SMProxy") or source.SMProxy is None:
            return False
        return (source.SMProxy.GetXMLName() or "") == "Calculator"

    def _calculator_attribute_type(self):
        """Return the active Calculator attribute type label."""
        if not self._is_active_calculator() or self.source is None:
            return ""
        prop = self.source.GetProperty("AttributeType")
        if prop is not None and hasattr(prop, "GetData"):
            return prop.GetData() or ""
        return ""

    def _calculator_input_variables(self):
        """Return input-array variable names available to the active Calculator."""
        if not self._is_active_calculator():
            return []

        node = self._get_active_node()
        if node is None:
            return []

        input_node = (
            self._find_node(node.get("parent_id")) if node.get("parent_id") else None
        )
        input_source = input_node["source"] if input_node is not None else self.source
        if input_source is None:
            return []

        data_information = input_source.GetDataInformation()
        if data_information is None:
            return []

        attribute_type = self._calculator_attribute_type()
        array_information = (
            data_information.GetCellDataInformation()
            if attribute_type == "Cell Data"
            else data_information.GetPointDataInformation()
        )
        items = self._collect_array_items(
            array_information,
            "CELLS" if attribute_type == "Cell Data" else "POINTS",
        )
        return [item["text"].rsplit(" ", 1)[0] for item in items]

    def _sync_view_center(self, source):
        """Align the view center of rotation with the active source bounds center."""
        if self.view is None or source is None:
            return

        data_information = source.GetDataInformation()
        if data_information is None:
            return

        bounds = data_information.GetBounds()
        if not bounds or len(bounds) != 6:
            return

        center = [
            0.5 * (bounds[0] + bounds[1]),
            0.5 * (bounds[2] + bounds[3]),
            0.5 * (bounds[4] + bounds[5]),
        ]

        center_property = self.view.GetProperty("CenterOfRotation")
        if center_property is not None and hasattr(center_property, "SetData"):
            center_property.SetData(center)

        focal_property = self.view.GetProperty("CameraFocalPoint")
        if focal_property is not None and hasattr(focal_property, "SetData"):
            focal_property.SetData(center)

    def _find_node(self, node_id) -> PipelineNode | None:
        """Find a pipeline node by id."""
        for node in self.pipeline_nodes:
            if node["id"] == node_id:
                return node
        return None

    def _collect_descendants(self, node_id) -> list[PipelineNode]:
        """Return all descendants of the provided node id."""
        descendants = []
        direct_children = [
            node for node in self.pipeline_nodes if node.get("parent_id") == node_id
        ]
        for child in direct_children:
            descendants.append(child)
            descendants.extend(self._collect_descendants(child["id"]))
        return descendants

    def _get_selected_array(self):
        """Return the current UI array selector value for the active display."""
        display = self.display
        if display is None:
            return ARRAY_SOLID

        color_array = getattr(display, "ColorArrayName", None)
        if not color_array or len(color_array) < 2 or not color_array[1]:
            return ARRAY_SOLID
        if color_array[0] == "POINTS":
            return f"{POINT_PREFIX}{color_array[1]}"
        if color_array[0] == "CELLS":
            return f"{CELL_PREFIX}{color_array[1]}"
        return ARRAY_SOLID

    def _resolve_available_array_value(self, array_value):
        """Return a valid array selector for the active source, or a safe fallback."""
        source = self.source
        if source is None or not array_value or array_value == ARRAY_SOLID:
            return ARRAY_SOLID

        available_items = self.get_available_arrays()
        available_values = {item["value"] for item in available_items}
        if array_value in available_values:
            return array_value

        if array_value.startswith(POINT_PREFIX):
            name = array_value[len(POINT_PREFIX) :]
        elif array_value.startswith(CELL_PREFIX):
            name = array_value[len(CELL_PREFIX) :]
        else:
            return ARRAY_SOLID

        point_candidate = f"{POINT_PREFIX}{name}"
        cell_candidate = f"{CELL_PREFIX}{name}"
        if point_candidate in available_values:
            return point_candidate
        if cell_candidate in available_values:
            return cell_candidate

        return available_items[1]["value"] if len(available_items) > 1 else ARRAY_SOLID

    def _get_representation(self):
        """Return the current representation label for the active display."""
        display = self.display
        if display is None:
            return "Surface with Edges"
        representation = display.GetProperty("Representation")
        if representation is not None and hasattr(representation, "GetData"):
            representation = representation.GetData()
        reverse = {
            "Surface": "Surface",
            "Surface With Edges": "Surface with Edges",
            "Wireframe": "Wireframe",
            "Points": "Points",
        }
        return reverse.get(representation, "Surface with Edges")

    @staticmethod
    def _node_id(source):
        """Build a stable UI id for a ParaView source proxy."""
        return f"source:{source.GetGlobalIDAsString()}"

    @staticmethod
    def _collect_array_items(data_information, association):
        """Convert ParaView array metadata into Trame select items."""
        if data_information is None:
            return []

        items = []
        for index in range(data_information.GetNumberOfArrays()):
            array_info = data_information.GetArrayInformation(index)
            if array_info is None:
                continue
            name = array_info.GetName()
            if not name:
                continue

            if association == "POINTS":
                items.append(
                    {"text": f"{name} (Point)", "value": f"{POINT_PREFIX}{name}"}
                )
            else:
                items.append(
                    {"text": f"{name} (Cell)", "value": f"{CELL_PREFIX}{name}"}
                )

        return items

    @staticmethod
    def _normalize_representation(representation):
        """Map UI labels to ParaView representation labels."""
        mapping = {
            "Surface": "Surface",
            "Surface with Edges": "Surface With Edges",
            "Wireframe": "Wireframe",
            "Points": "Points",
        }
        return mapping.get(representation, representation)

    @staticmethod
    def _coerce_time_values(raw_times):
        """Return animation timesteps as a plain list of floats."""
        if raw_times is None:
            return []

        try:
            values = list(raw_times)
        except TypeError:
            return []

        coerced = []
        for value in values:
            try:
                coerced.append(float(value))
            except (TypeError, ValueError):
                continue
        return coerced

    def get_time_state(self):
        """Return time information for the current animation scene."""
        get_animation_scene = getattr(self.simple, "GetAnimationScene", None)
        if not callable(get_animation_scene):
            return {
                "time_values": [],
                "current_time": 0.0,
                "time_index": 0,
                "total_timesteps": 0,
                "is_time_dependent": False,
            }

        scene = get_animation_scene()
        if scene is None:
            return {
                "time_values": [],
                "current_time": 0.0,
                "time_index": 0,
                "total_timesteps": 0,
                "is_time_dependent": False,
            }

        time_values = self._coerce_time_values(
            getattr(scene.TimeKeeper, "TimestepValues", None)
        )
        current_time = float(getattr(scene, "AnimationTime", 0.0) or 0.0)

        time_index = 0
        if time_values:
            # Find closest index
            time_index = bisect.bisect_left(time_values, current_time)
            if time_index >= len(time_values):
                time_index = len(time_values) - 1
            elif time_index > 0 and (time_values[time_index] - current_time) > (
                current_time - time_values[time_index - 1]
            ):
                time_index -= 1

        return {
            "time_values": time_values,
            "current_time": current_time,
            "time_index": time_index,
            "total_timesteps": len(time_values),
            "is_time_dependent": len(time_values) > 1,
        }

    def set_time(self, time_value):
        """Set the current time in the animation scene."""
        scene = self.simple.GetAnimationScene()
        scene.AnimationTime = float(time_value)
        self._clear_surface_selection_helper()
        self._boundary_cache.clear()

    def set_time_step(self, step_delta):
        """Move the current time by a number of steps."""
        state = self.get_time_state()
        if not state["is_time_dependent"]:
            return

        new_index = max(
            0, min(state["total_timesteps"] - 1, state["time_index"] + step_delta)
        )
        self.set_time(state["time_values"][new_index])

    def rescale_color_range_over_time(self):
        """Rescale the active color map to the range of data over all timesteps."""
        display = self.display
        if display is None:
            return

        # ParaView API differs across versions/builds:
        # - some expose simple.RescaleTransferFunctionToDataRangeOverTime()
        # - some expose display.RescaleTransferFunctionToDataRangeOverTime()
        # - older versions only support display.RescaleTransferFunctionToDataRange(...)
        simple_rescale_over_time = getattr(
            self.simple, "RescaleTransferFunctionToDataRangeOverTime", None
        )
        if callable(simple_rescale_over_time):
            simple_rescale_over_time()
            self._restore_scalar_bar_visibility()
            self.render()
            return

        display_rescale_over_time = getattr(
            display, "RescaleTransferFunctionToDataRangeOverTime", None
        )
        if callable(display_rescale_over_time):
            display_rescale_over_time()
            self._restore_scalar_bar_visibility()
            self.render()
            return

        display_rescale = getattr(display, "RescaleTransferFunctionToDataRange", None)
        if callable(display_rescale):
            for args in ((False, True), (True, False), ()):
                try:
                    display_rescale(*args)
                    self._restore_scalar_bar_visibility()
                    self.render()
                    return
                except TypeError:
                    continue

        raise RuntimeError(
            "Current ParaView build does not expose a compatible "
            "rescale-over-time API."
        )

    @staticmethod
    def _make_node(
        source,
        display,
        filename,
        kind,
        label,
        parent_id=None,
        filter_key=None,
    ) -> PipelineNode:
        """Build a pipeline node descriptor."""
        return {
            "id": ParaViewBackend._node_id(source),
            "source": source,
            "display": display,
            "filename": filename,
            "kind": kind,
            "label": label,
            "parent_id": parent_id,
            "filter_key": filter_key,
            "visibility": (
                bool(getattr(display, "Visibility", True))
                if display is not None
                else True
            ),
            "cell_dimension_visibility": {"cells": True, "faces": True},
            "cell_dimension_extracts": {},
        }

    def _pipeline_label(self, node: PipelineNode):
        """Return a readable pipeline label with lightweight hierarchy cues."""
        depth = 0
        parent_id = node.get("parent_id")
        while parent_id:
            parent = self._find_node(parent_id)
            if parent is None:
                break
            depth += 1
            parent_id = parent.get("parent_id")
        prefix = "  " * depth
        return f"{prefix}{node.get('label') or os.path.basename(node.get('filename') or 'source')}"

    def _pipeline_depth(self, node: PipelineNode):
        """Return hierarchy depth for a pipeline node."""
        depth = 0
        parent_id = node.get("parent_id")
        while parent_id:
            parent = self._find_node(parent_id)
            if parent is None:
                break
            depth += 1
            parent_id = parent.get("parent_id")
        return depth

    def _pipeline_icon(self, node: PipelineNode):
        """Return a kind-aware icon for a pipeline entry."""
        return self.filter_catalog.pipeline_icon(node)

    def _relative_path(self, filename):
        """Return a path relative to the configured data directory when possible."""
        if not filename:
            return ""
        if self.data_directory is None:
            return os.path.basename(filename)
        try:
            common = os.path.commonpath(
                [self.data_directory, os.path.abspath(filename)]
            )
        except ValueError:
            return os.path.basename(filename)
        if common != self.data_directory:
            return os.path.basename(filename)
        return os.path.relpath(filename, self.data_directory)

    def _resolve_snapshot_filename(self, filename):
        """Resolve a saved-state dataset path back to an absolute readable path."""
        if not filename:
            raise ValueError("Saved state is missing a source filename")
        if os.path.isabs(filename):
            return filename
        if self.data_directory is None:
            return filename
        return os.path.join(self.data_directory, filename)

    def _default_output_extension(self):
        """Return a reasonable file extension for the active dataset type."""
        source = self.source
        if source is None:
            return ".vtk"
        data_information = source.GetDataInformation()
        type_name = (
            data_information.GetDataSetTypeAsString()
            if data_information is not None
            and hasattr(data_information, "GetDataSetTypeAsString")
            else ""
        )
        mapping = {
            "PolyData": ".vtp",
            "UnstructuredGrid": ".vtu",
            "StructuredGrid": ".vts",
            "RectilinearGrid": ".vtr",
            "ImageData": ".vti",
            "MultiBlockDataSet": ".vtm",
            "PartitionedDataSetCollection": ".vtm",
            "PartitionedDataSet": ".vtm",
        }
        for key, suffix in mapping.items():
            if key in type_name:
                return suffix
        return ".vtk"
