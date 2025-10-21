import os

CURRENT_DIRECTORY = os.path.abspath(os.path.dirname(__file__))


def get_vtk_files_from_data_folder():
    """Scan the data folder and return list of VTK files."""
    data_folder = os.path.join(CURRENT_DIRECTORY, "data")
    print(f"data_folder: {data_folder}")

    if not os.path.exists(data_folder):
        print(f"Warning: Data folder not found: {data_folder}")
        return []

    vtk_files = []
    for filename in os.listdir(data_folder):
        if filename.lower().endswith(".vtk"):
            full_path = os.path.join(data_folder, filename)
            vtk_files.append({"text": filename, "value": full_path})

    # Sort alphabetically
    vtk_files.sort(key=lambda x: x["text"])
    return vtk_files


def detect_and_create_reader(filename):
    """Detect VTK legacy file type and return appropriate reader."""
    from vtkmodules.vtkIOLegacy import (
        vtkStructuredPointsReader,
        vtkUnstructuredGridReader,
        vtkPolyDataReader,
    )

    ext = os.path.splitext(filename)[1].lower()

    if ext != ".vtk":
        raise ValueError(f"Only .vtk files are supported. Got: {ext}")

    # Read file in binary mode to handle both ASCII and binary VTK files
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

    # Default fallback
    print(f"Warning: Could not detect dataset type, trying UnstructuredGridReader")
    return vtkUnstructuredGridReader()
