## Installation

```bash
python3 -m venv .venv
source ./.venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Or manually:
```bash
pip install trame                   # Install trame core
pip install trame-vuetify trame-vtk # Install widgets that we'll be using
pip install vtk                     # Install the VTK library
pip install balck                   # Black formatter
```

## Usage

```bash
source .venv/bin/activate  
python3 app.py  
```
or using the custom `file` argument plus any Trame argument (i.e. `port`)    
`python app.py --file data/grid-1.vtk --port 1234`

### Format your code

`black app.py`

## Inspecting VTU files

`inspect_vtu.py` decodes and prints all cell types and data arrays from a `.vtu` file (binary/compressed and not human-readable).

```bash
source .venv/bin/activate
python3 inspect_vtu.py data/output.vtu            # print to console
python3 inspect_vtu.py data/output.vtu -o out.txt # write to file
```

## Usage with Docker

Original example at the official [Trame repo](https://github.com/Kitware/trame/tree/master/examples/deploy/docker/SingleFile).

### Build the image

```bash
docker build -t trame-simple-visualizer .
```

### Run the image on port 8008

```bash
docker run -it --rm -p 8008:80 trame-simple-visualizer
```

Or if you need some prefix

```bash
docker run -it --rm -p 8008:80 -e TRAME_URL_PREFIX=/my-app/sub/path trame-simple-visualizer
```
