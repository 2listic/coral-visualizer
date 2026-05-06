#!/usr/bin/env python3
"""Look up ParaView API symbols: print docstring and jump-to-source location.

Usage:
  python tools/pv_lookup.py simple.Show
  python tools/pv_lookup.py servermanager.Proxy
"""

import importlib
import inspect
import sys


def resolve(symbol: str):
    parts = symbol.split(".")
    if len(parts) < 2:
        sys.exit(f"Provide a dotted symbol, e.g. simple.Show (got: {symbol!r})")

    module_name = "paraview." + ".".join(parts[:-1])
    attr_name = parts[-1]

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        sys.exit(f"Cannot import {module_name}: {exc}")

    obj = getattr(module, attr_name, None)
    if obj is None:
        sys.exit(f"{attr_name!r} not found in {module_name}")

    return obj


def main():
    if len(sys.argv) != 2:
        sys.exit(f"Usage: {sys.argv[0]} <symbol>  (e.g. simple.Show)")

    obj = resolve(sys.argv[1])

    try:
        file = inspect.getfile(obj)
        _, line = inspect.getsourcelines(obj)
        print(f"{file}:{line}")
    except (TypeError, OSError) as exc:
        sys.exit(f"Cannot locate source: {exc}")


if __name__ == "__main__":
    main()
