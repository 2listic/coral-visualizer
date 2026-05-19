"""Centralized notification helper for Trame state."""


def notify(state, message, notification_type="info"):
    """Push a toast notification to the UI snackbar."""
    state.notification_message = message
    state.notification_type = notification_type
    state.notification_show = True
