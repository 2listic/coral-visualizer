## Installation

```bash
python3 -m venv .venv
source ./.venv/bin/activate
python -m pip install --upgrade pip
pip install trame                   # Install trame core
pip install trame-vuetify trame-vtk # Install widgets that we'll be using
pip install vtk                     # Install the VTK library
```

## Usage

```bash
source .venv/bin/activate  
python3 app.py --file data/grid-1.vtk --port 1234  
```