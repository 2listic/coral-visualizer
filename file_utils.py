import os

from diagnostics import debug_log

CURRENT_DIRECTORY = os.path.abspath(os.path.dirname(__file__))


def get_vtk_files_from_data_folder(data_folder=None):
    """Scan the data folder and return list of VTK files (legacy and XML formats)."""
    if data_folder is None:
        data_folder = os.path.join(CURRENT_DIRECTORY, "data")
    else:
        data_folder = os.path.abspath(data_folder)
    debug_log(f"data_folder: {data_folder}")

    if not os.path.exists(data_folder):
        debug_log(f"Warning: Data folder not found: {data_folder}")
        return []

    # Support both legacy .vtk and XML format .vtu/.pvtu
    supported_extensions = (".vtk", ".vtu", ".pvtu")

    # Collect files grouped by subfolder (relative to data_folder)
    groups = {}  # subfolder_rel_path -> list of {text, value}
    for dirpath, dirnames, filenames in os.walk(data_folder):
        dirnames.sort()  # traverse subdirs alphabetically
        matching = sorted(
            f for f in filenames if f.lower().endswith(supported_extensions)
        )
        if not matching:
            continue
        rel_dir = os.path.relpath(dirpath, data_folder)
        groups[rel_dir] = [
            {"text": f, "value": os.path.join(dirpath, f)} for f in matching
        ]

    # Build flat item list with group headers for subfolders
    items = []
    # Root files first (rel_dir == ".")
    if "." in groups:
        items.extend(groups.pop("."))

    for rel_dir in sorted(groups):
        if items:
            items.append({"divider": True})
        items.append({"header": rel_dir})
        items.extend(groups[rel_dir])

    for item in items:
        if item.get("value") and item.get("text"):
            item["path"] = item["text"]

    for rel_dir, grouped_items in groups.items():
        for item in grouped_items:
            item["path"] = os.path.join(rel_dir, item["text"])

    return items


def detect_and_create_reader(filename):
    """Detect VTK file type (legacy or XML) and return appropriate reader."""
    from vtkmodules.vtkIOLegacy import (
        vtkStructuredPointsReader,
        vtkUnstructuredGridReader,
        vtkPolyDataReader,
    )
    from vtkmodules.vtkIOXML import (
        vtkXMLUnstructuredGridReader,
        vtkXMLPUnstructuredGridReader,
    )

    ext = os.path.splitext(filename)[1].lower()

    if ext == ".vtu":
        debug_log("Detected VTK XML UnstructuredGrid format (.vtu)")
        return vtkXMLUnstructuredGridReader()
    elif ext == ".pvtu":
        debug_log("Detected VTK XML Parallel UnstructuredGrid format (.pvtu)")
        return vtkXMLPUnstructuredGridReader()
    elif ext == ".vtk":
        debug_log("Detected VTK legacy format (.vtk), reading header...")
        reader = None
        with open(filename, "rb") as f:
            # Read first ~500 bytes which should contain the header
            header = f.read(500).decode("latin-1", errors="ignore")

            for line in header.split("\n"):
                line = line.strip().upper()
                if "DATASET" in line:
                    if "STRUCTURED_POINTS" in line or "IMAGE_DATA" in line:
                        reader = vtkStructuredPointsReader()
                    elif "UNSTRUCTURED_GRID" in line:
                        reader = vtkUnstructuredGridReader()
                    elif "POLYDATA" in line:
                        reader = vtkPolyDataReader()
                    else:
                        reader = None
                    break

        if reader is None:
            # Default fallback for legacy format
            debug_log(
                "Warning: Could not detect dataset type, trying UnstructuredGridReader"
            )
            reader = vtkUnstructuredGridReader()

        # Legacy readers only load the first SCALARS array by default.
        # Enable reading all arrays so ManifoldID etc. are discovered.
        reader.ReadAllScalarsOn()
        reader.ReadAllVectorsOn()
        return reader
    else:
        raise ValueError(
            f"Unsupported file format: {ext}. Supported: .vtk, .vtu, .pvtu"
        )
