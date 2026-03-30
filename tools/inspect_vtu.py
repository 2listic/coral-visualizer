#!/usr/bin/env python3
"""Inspect a VTK unstructured grid file and print all array values."""

import argparse
import sys
import vtk


def _cell_type_name(type_id: int) -> str:
    name = vtk.vtkCellTypes.GetClassNameFromTypeId(type_id)
    return name if name else f"UNKNOWN({type_id})"


def inspect(filename: str, out) -> None:
    r = vtk.vtkXMLUnstructuredGridReader()
    r.SetFileName(filename)
    r.Update()
    ds = r.GetOutput()

    print(f"File: {filename}", file=out)
    print(f"Points: {ds.GetNumberOfPoints()}, Cells: {ds.GetNumberOfCells()}", file=out)

    print("\nCell types:", file=out)
    for i in range(ds.GetNumberOfCells()):
        type_id = ds.GetCellType(i)
        type_name = _cell_type_name(type_id)
        print(f"  [{i}] {type_name} ({type_id})", file=out)

    for label, data in [("Point", ds.GetPointData()), ("Cell", ds.GetCellData())]:
        for i in range(data.GetNumberOfArrays()):
            arr = data.GetArray(i)
            name = arr.GetName()
            vals = [arr.GetValue(j) for j in range(arr.GetNumberOfTuples())]
            print(f"\n{label} array '{name}':", file=out)
            for idx, v in enumerate(vals):
                print(f"  [{idx}] {v}", file=out)


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
