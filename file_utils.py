import os

CURRENT_DIRECTORY = os.path.abspath(os.path.dirname(__file__))


def get_vtk_files_from_data_folder():
    """Scan the data folder and return list of VTK files (legacy and XML formats)."""
    data_folder = os.path.join(CURRENT_DIRECTORY, "data")
    print(f"data_folder: {data_folder}")

    if not os.path.exists(data_folder):
        print(f"Warning: Data folder not found: {data_folder}")
        return []

    # Support both legacy .vtk and XML format .vtu
    supported_extensions = (".vtk", ".vtu")

    vtk_files = []
    for filename in os.listdir(data_folder):
        if filename.lower().endswith(supported_extensions):
            full_path = os.path.join(data_folder, filename)
            vtk_files.append({"text": filename, "value": full_path})

    # Sort alphabetically
    vtk_files.sort(key=lambda x: x["text"])
    return vtk_files


def detect_and_create_reader(filename):
    """Detect VTK file type (legacy or XML) and return appropriate reader."""
    from vtkmodules.vtkIOLegacy import (
        vtkStructuredPointsReader,
        vtkUnstructuredGridReader,
        vtkPolyDataReader,
    )
    from vtkmodules.vtkIOXML import (
        vtkXMLUnstructuredGridReader,
    )

    ext = os.path.splitext(filename)[1].lower()

    if ext == ".vtu":
        print(f"Detected VTK XML UnstructuredGrid format (.vtu)")
        return vtkXMLUnstructuredGridReader()
    elif ext == ".vtk":
        print(f"Detected VTK legacy format (.vtk), reading header...")
        with open(filename, "rb") as f:
            # Read first ~500 bytes which should contain the header
            header = f.read(500).decode('latin-1', errors='ignore')

            for line in header.split('\n'):
                line = line.strip().upper()
                if "DATASET" in line:
                    if "STRUCTURED_POINTS" in line or "IMAGE_DATA" in line:
                        return vtkStructuredPointsReader()
                    elif "UNSTRUCTURED_GRID" in line:
                        return vtkUnstructuredGridReader()
                    elif "POLYDATA" in line:
                        return vtkPolyDataReader()
                    break

        # Default fallback for legacy format
        print(f"Warning: Could not detect dataset type, trying UnstructuredGridReader")
        return vtkUnstructuredGridReader()
    else:
        raise ValueError(f"Unsupported file format: {ext}. Supported: .vtk, .vtu")
