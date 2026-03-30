## Installation

```bash
uv venv
source ./.venv/bin/activate
uv pip install -r setup/requirements.txt -r setup/requirements-dev.txt
```

Dependencies are declared unpinned in `setup/requirements.txt` (runtime) and `setup/requirements-dev.txt` (dev tools). No lockfiles are used for now: the official Docker image also installs from `setup/requirements.txt` directly.

### Usage

```bash
source .venv/bin/activate
python3 app.py
```

or using the custom `file` argument plus any Trame argument (i.e. `port`)  
`python app.py --file data/grid-1.vtk --port 1234`

## Usage with Docker

Original example at the official [Trame repo](https://github.com/Kitware/trame/tree/master/examples/deploy/docker/SingleFile).

#### Build the image

```bash
docker build -t coral-visualizer-standalone .
```

#### Run the image on port 8008

```bash
docker run -it --rm -p 8008:80 coral-visualizer-standalone
```

Or if you need some prefix

```bash
docker run -it --rm -p 8008:80 -e TRAME_URL_PREFIX=/my-app/sub/path coral-visualizer-standalone
```

## Development 

### Pre-commit hooks

After installing dev dependencies, install the git hooks once:

```bash
pre-commit install
```

After that, `black` and `ruff` run automatically on every `git commit`. To run them manually against all files:

```bash
pre-commit run --all-files
```

Pin hook versions to latest with `pre-commit autoupdate`.

### Format and lint manually

```bash
black .             # auto-format
ruff check .        # lint
ruff check --fix .  # lint + auto-fix
```

### Tests

```bash
pytest          # run all smoke tests
pytest -v       # verbose output
```

## Inspecting VTU files

`inspect_vtu.py` decodes and prints all cell types and data arrays from a `.vtu` file (binary/compressed and not human-readable).

```bash
source .venv/bin/activate
python3 tools/inspect_vtu.py data/output.vtu            # print to console
python3 tools/inspect_vtu.py data/output.vtu -o out.txt # write to file
```
