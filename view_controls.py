"""Small wrapper around Trame view controller callbacks."""


class ViewControllerProxy:
    """Centralize view updates and optional ParaView diagnostics."""

    def __init__(self, ctrl, state, *, backend, devtools_enabled=False):
        self._ctrl = ctrl
        self._state = state
        self._backend = backend
        self._devtools_enabled = bool(devtools_enabled)

    def debug(self, message, **values):
        """Emit compact view diagnostics when devtools are enabled."""
        if not (self._backend == "paraview" and self._devtools_enabled):
            return False
        payload = " ".join(f"{key}={values[key]!r}" for key in sorted(values))
        if payload:
            print(f"[view-debug] {message} {payload}", flush=True)
        else:
            print(f"[view-debug] {message}", flush=True)
        return True

    def update(self, *args, **kwargs):
        """Push a regular view update to the browser."""
        if not hasattr(self._ctrl, "view_update"):
            return None
        self.debug(
            "view.update",
            mode=self._state.mainViewMode,
            args=args,
            kwargs=kwargs,
            edit_session_active=self._state.edit_session_active,
        )
        return self._ctrl.view_update(*args, **kwargs)

    def update_geometry(self, *args, **kwargs):
        """Push a geometry update to the browser."""
        if not hasattr(self._ctrl, "view_update_geometry"):
            return None
        self.debug(
            "view.update_geometry",
            mode=self._state.mainViewMode,
            args=args,
            kwargs=kwargs,
            edit_session_active=self._state.edit_session_active,
        )
        return self._ctrl.view_update_geometry(*args, **kwargs)

    def set_remote_rendering(self, *args, **kwargs):
        """Switch VtkRemoteLocalView rendering mode when available."""
        if not hasattr(self._ctrl, "view_set_remote_rendering"):
            return None
        self.debug(
            "view.set_remote_rendering",
            mode_before=self._state.mainViewMode,
            args=args,
            kwargs=kwargs,
            edit_session_active=self._state.edit_session_active,
        )
        result = self._ctrl.view_set_remote_rendering(*args, **kwargs)
        self.debug(
            "view.set_remote_rendering.done", mode_after=self._state.mainViewMode
        )
        return result
