"""Developer diagnostics shared across backend helpers."""

_devtools_enabled = False


def set_devtools_enabled(enabled):
    """Set process-wide developer diagnostics."""
    global _devtools_enabled
    _devtools_enabled = bool(enabled)


def devtools_enabled():
    """Return whether developer diagnostics should be emitted."""
    return _devtools_enabled


def debug_log(message="", *, flush=False):
    """Print a developer diagnostic only when devtools are enabled."""
    if _devtools_enabled:
        print(message, flush=flush)
