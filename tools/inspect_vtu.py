#!/usr/bin/env python3
"""Inspect VTK dataset files (.vtu/.vtk) and print a robust summary."""

import argparse
import os
import sys
import xml.etree.ElementTree as ET

import vtk


def _cell_type_name(type_id: int) -> str:
    name = vtk.vtkCellTypes.GetClassNameFromTypeId(type_id)
    return name if name else f"UNKNOWN({type_id})"


def _looks_like_xml_vtk(filename: str) -> bool:
    """Best-effort check for XML VTK content regardless of extension."""
    try:
        with open(filename, "rb") as handle:
            head = handle.read(2048)
        compact = head.lstrip()
        return compact.startswith(b"<VTKFile") or compact.startswith(b"<?xml") and b"<VTKFile" in compact
    except Exception:
        return False


def _build_reader(filename: str):
    """Return (reader, reader_kind) suitable for the provided VTK file."""
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".vtu" or _looks_like_xml_vtk(filename):
        return vtk.vtkXMLUnstructuredGridReader(), "xml"

    # Legacy .vtk (and fallback for unknown extensions)
    reader = vtk.vtkDataSetReader()
    reader.ReadAllScalarsOn()
    reader.ReadAllVectorsOn()
    reader.ReadAllTensorsOn()
    reader.ReadAllColorScalarsOn()
    reader.ReadAllNormalsOn()
    reader.ReadAllFieldsOn()
    return reader, "legacy"


def _reader_error_message(reader) -> str | None:
    """Return a human-readable vtk reader error, if available."""
    try:
        error_code = int(reader.GetErrorCode())
    except Exception:
        return None
    if error_code == 0:
        return None
    try:
        error_name = vtk.vtkErrorCode.GetStringFromErrorCode(error_code)
    except Exception:
        error_name = None
    return (
        f"VTK reader error code {error_code}"
        + (f" ({error_name})" if error_name else "")
    )


def _xml_fallback_summary(filename: str, out) -> None:
    """
    Best-effort XML summary when vtk reader cannot build a valid dataset.

    This intentionally does not decode appended/compressed binary data. It only
    reports metadata present in the XML structure.
    """
    print("\nFallback XML summary:", file=out)
    try:
        tree = ET.parse(filename)
        root = tree.getroot()
    except Exception as exc:
        print(f"  Could not parse XML fallback: {exc}", file=out)
        return

    if root.tag != "VTKFile":
        print(f"  Unexpected root tag: {root.tag}", file=out)
        return

    ugrid = root.find("UnstructuredGrid")
    if ugrid is None:
        print("  No <UnstructuredGrid> element found.", file=out)
        return

    pieces = ugrid.findall("Piece")
    if not pieces:
        print("  No <Piece> elements found.", file=out)
        return

    for idx, piece in enumerate(pieces):
        n_points = piece.attrib.get("NumberOfPoints", "unknown")
        n_cells = piece.attrib.get("NumberOfCells", "unknown")
        print(f"  Piece {idx}: NumberOfPoints={n_points}, NumberOfCells={n_cells}", file=out)

        point_data = piece.find("PointData")
        cell_data = piece.find("CellData")
        for label, section in (("PointData", point_data), ("CellData", cell_data)):
            if section is None:
                print(f"    {label}: <missing>", file=out)
                continue
            arrays = section.findall("DataArray")
            print(f"    {label}: {len(arrays)} array(s)", file=out)
            for arr in arrays:
                name = arr.attrib.get("Name", "<unnamed>")
                dtype = arr.attrib.get("type", "<unknown-type>")
                ncomp = arr.attrib.get("NumberOfComponents", "1")
                fmt = arr.attrib.get("format", "<unknown-format>")
                print(
                    f"      - {name}: type={dtype}, components={ncomp}, format={fmt}",
                    file=out,
                )


def _legacy_fallback_summary(filename: str, out) -> None:
    """Best-effort summary for malformed legacy VTK files."""
    print("\nFallback legacy header summary:", file=out)
    try:
        with open(filename, "rb") as handle:
            head = handle.read(4096)
    except Exception as exc:
        print(f"  Could not read file header: {exc}", file=out)
        return

    decoded = head.decode("latin-1", errors="replace")
    lines = [line.strip() for line in decoded.splitlines() if line.strip()]
    if not lines:
        print("  Header is empty or non-text.", file=out)
        return

    preview = lines[:12]
    for idx, line in enumerate(preview):
        print(f"  [{idx}] {line}", file=out)

    dataset_line = next(
        (line for line in lines if line.upper().startswith("DATASET ")),
        None,
    )
    if dataset_line:
        print(f"  Declared dataset: {dataset_line.split(maxsplit=1)[1]}", file=out)


def _print_array(label: str, arr, out) -> None:
    """Print one VTK array robustly (scalar, vector, string, missing, etc.)."""
    if arr is None:
        print(f"\n{label} array: <null>", file=out)
        return

    try:
        name = arr.GetName() or "<unnamed>"
    except Exception:
        name = "<unnamed>"
    try:
        num_tuples = int(arr.GetNumberOfTuples())
    except Exception:
        num_tuples = 0
    try:
        num_components = int(arr.GetNumberOfComponents())
    except Exception:
        num_components = 1

    print(
        f"\n{label} array '{name}' ({num_tuples} tuples, {num_components} component(s)):",
        file=out,
    )

    for tuple_id in range(num_tuples):
        try:
            if num_components == 1:
                value = arr.GetVariantValue(tuple_id).ToString()
            else:
                value = tuple(arr.GetTuple(tuple_id))
        except Exception as exc:
            value = f"<error reading tuple {tuple_id}: {exc}>"
        print(f"  [{tuple_id}] {value}", file=out)


def inspect(filename: str, out) -> None:
    print(f"File: {filename}", file=out)
    if not os.path.exists(filename):
        print("Error: file does not exist.", file=out)
        return
    if not os.path.isfile(filename):
        print("Error: path is not a regular file.", file=out)
        return

    r, reader_kind = _build_reader(filename)
    r.SetFileName(filename)

    can_read = 1
    if hasattr(r, "CanReadFile"):
        try:
            can_read = int(r.CanReadFile(filename))
        except Exception:
            can_read = 0
        if not can_read:
            print(
                f"Warning: {r.__class__.__name__} reports this file may not be readable.",
                file=out,
            )

    r.Update()
    ds = r.GetOutput()

    reader_error = _reader_error_message(r)
    if reader_error:
        print(f"Warning: {reader_error}", file=out)

    if ds is None:
        print("Error: reader returned no dataset output.", file=out)
        if reader_kind == "xml":
            _xml_fallback_summary(filename, out)
        else:
            _legacy_fallback_summary(filename, out)
        return

    print(f"Points: {ds.GetNumberOfPoints()}, Cells: {ds.GetNumberOfCells()}", file=out)
    if ds.GetNumberOfPoints() == 0 and ds.GetNumberOfCells() == 0:
        print(
            "Warning: dataset is empty (0 points, 0 cells). File may be malformed or partially written.",
            file=out,
        )
        if reader_kind == "xml":
            _xml_fallback_summary(filename, out)
        else:
            _legacy_fallback_summary(filename, out)

    print("\nCell types:", file=out)
    for i in range(ds.GetNumberOfCells()):
        type_id = ds.GetCellType(i)
        type_name = _cell_type_name(type_id)
        print(f"  [{i}] {type_name} ({type_id})", file=out)

    for label, data in [("Point", ds.GetPointData()), ("Cell", ds.GetCellData())]:
        if data is None:
            print(f"\n{label}Data: <missing>", file=out)
            continue
        for i in range(data.GetNumberOfArrays()):
            _print_array(label, data.GetArray(i), out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Inspect a VTK unstructured grid file."
    )
    parser.add_argument("file", help="Path to the .vtu file")
    parser.add_argument(
        "-o", "--output", help="Write output to this file instead of stdout"
    )
    args = parser.parse_args()

    if args.output:
        with open(args.output, "w") as f:
            inspect(args.file, f)
        print(f"Output written to {args.output}")
    else:
        inspect(args.file, sys.stdout)
