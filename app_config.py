"""Application configuration and CLI parsing."""

import argparse
import os
import sys
from dataclasses import dataclass

from diagnostics import set_devtools_enabled


@dataclass(frozen=True)
class AppConfig:
    file: str | None
    data_directory: str
    devtools_enabled: bool
    show_experimental_filters: bool


def configure_app():
    """Parse CLI arguments and derive runtime configuration."""
    parser = _build_parser()
    args, _unknown = parser.parse_known_args()

    devtools_enabled = bool(args.devtools or args.dev)
    set_devtools_enabled(devtools_enabled)
    if devtools_enabled and "--hot-reload" not in sys.argv:
        sys.argv.append("--hot-reload")
        os.environ["TRAME_HOT_RELOAD"] = "1"

    return AppConfig(
        file=args.file,
        data_directory=os.path.abspath(args.data_directory),
        devtools_enabled=devtools_enabled,
        show_experimental_filters=not args.hide_experimental_filters,
    )


def enable_paraview_web_venv_if_requested():
    """Enable ParaView's web venv hook before importing Trame/ParaView modules."""
    if os.environ.get("PV_VENV") or "--venv" in sys.argv:
        import paraview.web.venv  # noqa: F401


def _build_parser():
    parser = argparse.ArgumentParser(
        description="ParaView Mesh Visualizer and Editor with Trame"
    )
    parser.add_argument(
        "--file",
        default=None,
        help="Path to VTK file to open on start (i.e.: data/grid-1.vtk)",
    )
    parser.add_argument(
        "--data-directory",
        default="./data",
        help="Directory containing input/output VTK files (default: ./data)",
    )
    parser.add_argument(
        "--devtools",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Enable developer diagnostics and Trame hot reload "
            "(default: enabled for now; use --no-devtools to disable)."
        ),
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Deprecated alias for --devtools.",
    )
    parser.add_argument(
        "--hide-experimental-filters",
        action="store_true",
        help="Hide experimentally discovered ParaView filters from the Filter menu.",
    )
    return parser
