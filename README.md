# Coral Visualizer

Trame/Vuetify visualizer for VTK/deal.II-style meshes. The project has two
rendering backends:

- `paraview`: primary backend for pipeline work, filters, edit sessions,
  selection, saving, and advanced display/color controls.
- `vtk`: legacy backend kept for lightweight local rendering and compatibility.

## Installation (ParaView backend)

The app now supports `--backend vtk|paraview|auto`.

The default `auto` mode uses ParaView when ParaView and the Trame ParaView
widget are available in the current Python environment; otherwise it falls back
to the legacy VTK backend.

The recommended way to run the ParaView backend is a dedicated conda
environment from `conda-forge`.

### Prerequisites: install conda

`setup_pv_env.sh` requires `conda` on your PATH. If you do not have it yet,
install **Miniforge** — a minimal, open-source installer that defaults to
`conda-forge` and includes `mamba` for faster environment solving:

```bash
wget "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh"
bash Miniforge3-Linux-x86_64.sh
# follow the prompts; answer yes to "initialize conda"
# restart your shell or: source ~/.bashrc
```

> **Micromamba alternative:** if you prefer a single-binary install with no base
> environment, run `"${SHELL}" <(curl -L micro.mamba.pm/install.sh)` and set
> `CONDA_BIN=micromamba` when calling `setup_pv_env.sh`. Note that the rest of
> this README uses `conda run ...`; replace it with `micromamba run ...`
> throughout if you go this route.

### Create the environment

```bash
./tools/setup_pv_env.sh
```

### Usage

```bash
conda run -n coral-paraview python app.py --backend paraview
```

You can override the defaults if needed:

```bash
ENV_NAME=my-pv-env PYTHON_VERSION=3.10 ./tools/setup_pv_env.sh
```

Mesh editing is supported on both VTK and ParaView backends.

## Legacy local VTK Installation / Unit-Test Environment

```bash
uv venv
source ./.venv/bin/activate
uv pip install -r setup/requirements.txt -r setup/requirements-dev.txt
```

Dependencies are pinned in `setup/requirements.txt` (runtime) and
`setup/requirements-dev.txt` (dev/test tools). Docker installs the same pinned
Python packages after provisioning ParaView from `setup/environment-docker.yml`.

This environment is suitable for the VTK backend and most unit tests. It is not
the recommended way to run the ParaView backend.

### Usage (legacy VTK backend)

```bash
source .venv/bin/activate
python3 app.py
```

or using the custom `file` argument plus any Trame argument (i.e. `port`)  
`python app.py --file data/grid-1.vtk --port 1234`

Use `--data-directory` to scan a custom folder instead of the default `./data` (also used as the save destination for exported `.vtu` files):  
`python app.py --data-directory /path/to/meshes`

Developer diagnostics are enabled by default for now through `--devtools`.
This also enables Trame hot reload and ParaView view/selection debug logs.
Use `--no-devtools` for a quieter production-like local run.

## Dependency Matrix

Verified on this development machine and in the Docker image on 2026-04-25.

| Component | Local `coral-paraview` env | Docker `coral` env |
| --- | ---: | ---: |
| Python | 3.10.20 | 3.10.20 |
| ParaView | 6.1 | 6.1 |
| VTK | 9.6.1 | 9.6.1 |
| trame | 3.12.0 | 3.12.0 |
| trame-vtk | 2.11.6 | 2.11.6 |
| trame-vuetify | 3.2.1 | 3.2.1 |
| pytest | 9.0.3 | 9.0.3 |
| Playwright | 1.58.0 | 1.58.0 |
| pytest-playwright | 0.7.2 (used by e2e tests in conda env) | 0.7.2 |
| Pillow | pinned in dev requirements; not required by local runtime | 12.2.0 |

Local version probe:

```bash
conda run -n coral-paraview python - <<'PY'
import importlib.metadata as md
import sys
print("python", sys.version.split()[0])
for name in ["trame", "trame-vtk", "trame-vuetify", "vtk", "playwright", "pytest"]:
    print(name, md.version(name))
import paraview.simple as ps
print("paraview", ps.GetParaViewVersion())
PY
```

Docker version probe:

```bash
docker run --rm coral-visualizer-standalone \
  micromamba run -n coral python -c "import sys, importlib.metadata as md; \
print('python', sys.version.split()[0]); \
[print(n, md.version(n)) for n in ['trame','trame-vtk','trame-vuetify','vtk','playwright','pytest','pytest-playwright','Pillow']]; \
import paraview.simple as ps; print('paraview', ps.GetParaViewVersion())"
```

## Usage with Docker

Original example at the official [Trame repo](https://github.com/Kitware/trame/tree/master/examples/deploy/docker/SingleFile).

The Docker image uses `micromamba` and a dedicated conda environment from
`conda-forge` so ParaView is available on Linux/arm64 as well. Python and
ParaView are constrained in `setup/environment-docker.yml`; runtime and dev
Python packages are installed from the pinned requirements files. The container
starts the app with `--backend paraview --server` by default.

The Docker path does not install ParaView from `setup/requirements.txt`.
Instead, it provisions a dedicated conda environment from
`setup/environment-docker.yml`.

#### Build the image

```bash
docker build -t coral-visualizer-standalone .
```

#### Run the image on port 8008

```bash
docker run -it --rm -p 8008:8080 coral-visualizer-standalone
```

Or if you need some prefix

```bash
docker run -it --rm -p 8008:8080 -e TRAME_URL_PREFIX=/my-app/sub/path coral-visualizer-standalone
```

#### Verify the container serves HTTP

```bash
docker run -d --rm --name coral-visualizer-readme-verify -p 18080:8080 coral-visualizer-standalone
python - <<'PY'
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:18080", timeout=5) as response:
    print(response.status)
PY
docker stop coral-visualizer-readme-verify
```

The ParaView backend starts correctly in the container and can render
offscreen, but on hosts without a full EGL/X stack you may still see startup
warnings such as `bad X server connection` or `Could not initialize a device`.
In the current setup those warnings are non-fatal: the app still starts and
ParaView can produce screenshots offscreen.

## Tests

### Unit tests

Activate the uv venv, then run:

```bash
source .venv/bin/activate
pytest          # run all unit tests
pytest -v       # verbose output
```

### E2E tests

E2E tests require the `coral-paraview` conda environment (ParaView + Playwright).
Run all tests (unit + e2e):

```bash
conda run -n coral-paraview pytest -q
```

By default, E2E tests run in headless mode. To run them with a visible browser:

```bash
conda run -n coral-paraview pytest tests/ --show-browser
```

Test meshes live in `test_data/` so tests do not depend on the `data/` directory.

Useful focused e2e tests:

```bash
conda run -n coral-paraview pytest -q tests/test_e2e_edit_selection_playwright.py::test_paraview_point_field_replace_box_selection_does_not_toggle_overlap
conda run -n coral-paraview pytest -q tests/test_e2e_edit_selection_playwright.py::test_paraview_display_color_scale_visibility_survives_rescale
```

## CI/CD

### Pre-commit hooks

After installing dev dependencies, install the git hooks once:

```bash
pre-commit install
```

After that, formatting (`black`), linting (`ruff`), and unit tests (`pytest`) run automatically on every `git commit`.  
**NOTE:**  
E2E tests are excluded from the pre-commit hook — run them manually with the
conda environment when needed.  
Either the uv venv or the conda environment must be active so that `pytest` is on the path.

To run hooks manually against all files:

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

### GitHub Actions

Two workflows run on push and pull requests to `main`:

- **CI** (`.github/workflows/test.yml`): builds the Docker image and runs the full
  test suite inside it via `micromamba run -n coral pytest -v tests/`.
- **Publish** (`.github/workflows/docker-publish.yml`): builds and pushes the Docker
  image to the GitHub Container Registry on pushes to `main` and on version tags (`v*.*.*`).

## Troubleshooting

- `ModuleNotFoundError: No module named 'paraview'`: use the conda
  `coral-paraview` environment or rebuild the Docker image. The `.venv`/`uv`
  environment does not provide ParaView.
- **ParaView backend not available even with `conda run`**: if the `.venv` is
  active in your shell, `conda run` inherits its `PATH` and `python` resolves
  to `.venv/bin/python` instead of the conda env. Run `deactivate` first, then
  retry `conda run -n coral-paraview python app.py ...`.
- `Page.wait_for_selector` failures in e2e: first verify the app can start with
  `--backend paraview`; then rerun with `--show-browser` or
  `E2E_STREAM_APP_LOGS=1`.
- ParaView startup warnings about X/EGL/OSMesa can be non-fatal in Docker. The
  HTTP verification above is the quick check that the app still starts.
- If a local Docker HTTP check fails with permission errors, rerun the check
  outside a restricted sandbox or with permission to access localhost/Docker.

## Inspecting VTU files

`inspect_vtu.py` decodes and prints all cell types and data arrays from a `.vtu` file (binary/compressed and not human-readable).

```bash
conda run -n coral-paraview python tools/inspect_vtu.py data/output.vtu            # print to console
conda run -n coral-paraview python tools/inspect_vtu.py data/output.vtu -o out.txt # write to file
```
