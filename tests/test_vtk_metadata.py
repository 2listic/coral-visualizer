from vtkmodules.vtkCommonCore import vtkDoubleArray
from vtkmodules.vtkCommonDataModel import vtkUnstructuredGrid

from vtk_metadata import sanitized_vtk_xml_path, strip_data_array_information_keys


def test_sanitized_vtk_xml_path_removes_l2_norm_information_keys(tmp_path):
    source = tmp_path / "mesh.vtu"
    source.write_bytes(
        b"""<?xml version="1.0"?>
<VTKFile type="UnstructuredGrid">
  <UnstructuredGrid>
    <Piece>
      <PointData>
        <DataArray Name="U">
          <InformationKey name="L2_NORM_RANGE" location="vtkDataArray" length="2">
            <Value index="0">0</Value>
            <Value index="1">inf</Value>
          </InformationKey>
        </DataArray>
      </PointData>
    </Piece>
  </UnstructuredGrid>
</VTKFile>
"""
    )

    sanitized = sanitized_vtk_xml_path(source)

    assert sanitized != str(source)
    assert b"L2_NORM_RANGE" not in open(sanitized, "rb").read()
    assert b"DataArray" in open(sanitized, "rb").read()


def test_strip_data_array_information_keys_removes_l2_norm_metadata():
    dataset = vtkUnstructuredGrid()
    array = vtkDoubleArray()
    array.SetName("U")
    array.GetInformation().Set(vtkDoubleArray.L2_NORM_RANGE(), (0.0, 1.0), 2)
    array.GetInformation().Set(vtkDoubleArray.L2_NORM_FINITE_RANGE(), (0.0, 1.0), 2)
    dataset.GetPointData().AddArray(array)

    strip_data_array_information_keys(dataset)

    assert array.GetInformation().Has(vtkDoubleArray.L2_NORM_RANGE()) == 0
    assert array.GetInformation().Has(vtkDoubleArray.L2_NORM_FINITE_RANGE()) == 0
