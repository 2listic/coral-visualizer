"""Edit-session scaffolding for the ParaView-backed workflow."""

from pathlib import Path

from vtkmodules.vtkCommonDataModel import vtkUnstructuredGrid
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

    def clear(self):
        """Reset the session to an inactive state."""
        self.active = False
        self.source_node_id = None
        self.source_label = ""
        self.source_filename = ""
        self.working_dataset = None
        self.dirty = False

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

    @staticmethod
    def is_supported_dataset(dataset):
        """Return True when the dataset type is currently editable."""
        return isinstance(dataset, vtkUnstructuredGrid)
