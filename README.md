# Coral Visualizer

Trame/Vuetify visualizer for VTK/deal.II-style meshes. The project has two
rendering backends:

- `paraview`: primary backend for pipeline work, filters, edit sessions,
  selection, saving, and advanced display/color controls.
- `vtk`: legacy backend kept for lightweight local rendering and compatibility.

## Installation

### Local VTK/Unit-Test Environment

```bash
uv venv
source ./.venv/bin/activate
uv pip install -r setup/requirements.txt -r setup/requirements-dev.txt
```

Dependencies are declared unpinned in `setup/requirements.txt` (runtime) and
`setup/requirements-dev.txt` (dev tools). No lockfiles are used for now.

This environment is suitable for the VTK backend and most unit tests. It is not
the recommended way to run the ParaView backend.

### Usage

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

### ParaView backend

The app now supports `--backend vtk|paraview|auto`.

The default `auto` mode uses ParaView when ParaView and the Trame ParaView
widget are available in the current Python environment; otherwise it falls back
to the legacy VTK backend.

The recommended way to run the ParaView backend is a dedicated conda
environment from `conda-forge`.

Create it non-interactively with:

```bash
./tools/setup_pv_env.sh
```

Then run:

```bash
conda run -n coral-paraview python app.py --backend paraview
```

You can override the defaults if needed:

```bash
ENV_NAME=my-pv-env PYTHON_VERSION=3.10 ./tools/setup_pv_env.sh
```

Mesh editing is supported on both VTK and ParaView backends.

## Dependency Matrix

Verified on this development machine and in the Docker image on 2026-04-25.

| Component | Local `coral-paraview` env | Docker `coral` env |
| --- | ---: | ---: |
| Python | 3.10.20 | 3.10.20 |
| ParaView | 6.1 | 6.1 |
| VTK | 9.6.1 | 9.6.1 |
| trame | 3.12.0 | 3.12.0 |
| trame-vtk | 2.11.6 | 2.11.7 |
| trame-vuetify | 3.2.1 | 3.2.1 |
| pytest | 9.0.3 | 9.0.3 |
| Playwright | 1.58.0 | 1.58.0 |
| pytest-playwright | installed for e2e via local dev setup | 0.7.2 |
| Pillow | not required by local runtime | 12.2.0 |

Local version probe:

```bash
~/anaconda3/envs/coral-paraview/bin/python - <<'PY'
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
`conda-forge` so ParaView is available on Linux/arm64 as well. The container
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

For the full suite, including ParaView e2e tests, use the conda environment:

```bash
~/anaconda3/envs/coral-paraview/bin/pytest -q
```

The standard suite includes headless e2e tests for ParaView. Install the browser
once in your dev environment if it is missing:

```bash
~/anaconda3/envs/coral-paraview/bin/python -m playwright install chromium
```

By default, E2E tests run in headless mode. To run them with a visible browser, use:

```bash
~/anaconda3/envs/coral-paraview/bin/pytest tests/ --show-browser
```

Test meshes used by the suite live in `test_data/` (for example
`test_data/square.vtk`) so tests do not depend on the regular `data/`
working directory.

Useful focused e2e tests:

```bash
~/anaconda3/envs/coral-paraview/bin/pytest -q tests/test_e2e_edit_selection_playwright.py::test_paraview_point_field_replace_box_selection_does_not_toggle_overlap
~/anaconda3/envs/coral-paraview/bin/pytest -q tests/test_e2e_edit_selection_playwright.py::test_paraview_display_color_scale_visibility_survives_rescale
```

## Troubleshooting

- `ModuleNotFoundError: No module named 'paraview'`: use the conda
  `coral-paraview` environment or rebuild the Docker image. The `.venv`/`uv`
  environment does not provide ParaView.
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
~/anaconda3/envs/coral-paraview/bin/python tools/inspect_vtu.py data/output.vtu            # print to console
~/anaconda3/envs/coral-paraview/bin/python tools/inspect_vtu.py data/output.vtu -o out.txt # write to file
```
