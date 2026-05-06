"""VTK metadata cleanup helpers."""

from pathlib import Path
import re
import tempfile

from vtkmodules.vtkCommonCore import vtkDataArray

_DATA_ARRAY_INFORMATION_KEYS = (
    vtkDataArray.L2_NORM_RANGE(),
    vtkDataArray.L2_NORM_FINITE_RANGE(),
)

_XML_INFORMATION_KEY_PATTERN = re.compile(
    rb"\s*<InformationKey\s+name=\"L2_NORM(?:_FINITE)?_RANGE\""
    rb"\s+location=\"vtkDataArray\"[^>]*>.*?</InformationKey>",
    re.DOTALL,
)


def strip_data_array_information_keys(dataset):
    """Remove optional VTK array information keys that can break XML rereads."""
    if dataset is None:
        return

    if hasattr(dataset, "GetNumberOfBlocks"):
        for index in range(dataset.GetNumberOfBlocks()):
            strip_data_array_information_keys(dataset.GetBlock(index))
        return

    for attributes_getter in (
        getattr(dataset, "GetPointData", None),
        getattr(dataset, "GetCellData", None),
        getattr(dataset, "GetFieldData", None),
    ):
        attributes = attributes_getter() if callable(attributes_getter) else None
        _strip_attributes_information_keys(attributes)

    points_getter = getattr(dataset, "GetPoints", None)
    points = points_getter() if callable(points_getter) else None
    points_data = (
        points.GetData() if points is not None and hasattr(points, "GetData") else None
    )
    _strip_array_information_keys(points_data)


def sanitized_vtk_xml_path(path):
    """Return a temporary XML VTK file path with fragile InformationKey blocks removed."""
    source_path = Path(path)
    if source_path.suffix.lower() not in {
        ".vtu",
        ".pvtu",
        ".vtp",
        ".vti",
        ".vtr",
        ".vts",
    }:
        return str(source_path)

    try:
        content = source_path.read_bytes()
    except OSError:
        return str(source_path)

    cleaned = _XML_INFORMATION_KEY_PATTERN.sub(b"", content)
    if cleaned == content:
        return str(source_path)

    temp = tempfile.NamedTemporaryFile(
        prefix=f"{source_path.stem}_",
        suffix=source_path.suffix,
        delete=False,
    )
    try:
        temp.write(cleaned)
        return temp.name
    finally:
        temp.close()


def _strip_attributes_information_keys(attributes):
    if attributes is None or not hasattr(attributes, "GetNumberOfArrays"):
        return
    for index in range(attributes.GetNumberOfArrays()):
        _strip_array_information_keys(attributes.GetArray(index))


def _strip_array_information_keys(array):
    if array is None or not hasattr(array, "GetInformation"):
        return
    information = array.GetInformation()
    if information is None:
        return
    for key in _DATA_ARRAY_INFORMATION_KEYS:
        try:
            information.Remove(key)
        except Exception:
            pass
