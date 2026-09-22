"""Runtime patches for upstream trame-vtk defects.

Each patch is guarded: if upstream changes the code being patched, the patch
no-ops with a warning rather than failing, so a dependency upgrade degrades to
the original behavior instead of crashing the app.

Delete a patch once the corresponding upstream fix ships and the pinned version
is raised.
"""

from diagnostics import debug_log


def apply_stale_retry_fix():
    """Keep the ParaView image-delivery stale retry chain alive.

    Upstream ``ParaViewWebPublishImageDelivery.push_render`` always arms the
    retry timer for ``delta_stale_time_before_render`` (D), but
    ``render_stale_image`` only retries when it has waited
    ``D * (stale_count + 1)`` and only re-arms the timer when it waited *less*
    than D. From the second round on the callback fires at delta of about D
    while needing 2D: neither branch runs, ``stale_handler_count`` has already
    been decremented, and the retry chain dies without pushing and without
    rescheduling. The effective retry limit is 1, not ``stale_count_limit``.

    When the view has not settled by then, no further image is pushed and the
    browser keeps an out-of-date frame until unrelated activity triggers a
    render. Symptom: toggling two display controls in quick succession leaves
    the viewport showing the intermediate state.

    This re-arms for the time still owed against the escalating threshold
    instead of dropping the chain. ``stale_count`` still only advances through
    ``push_render``, so ``stale_count_limit`` continues to bound the loop.

    Measured in Docker at ``--cpus=2`` (the CI configuration) on
    ``test_paraview_show_faces_only_keeps_explicit_cube_boundary_faces``:
    14/20 passing without the patch, 20/20 with it (Fisher exact p ~ 0.02).

    Reported upstream against Kitware/trame-vtk; see ``.ai/issue-draft.md``.

    Returns True when the patch is in place, False when it was skipped.
    """
    try:
        from trame_vtk.modules.paraview.protocols import (
            publish_image_delivery as delivery,
        )
    except ImportError as exc:
        print(f"[trame-vtk-patch] stale-retry fix skipped, import failed: {exc}")
        return False

    cls = delivery.ParaViewWebPublishImageDelivery

    if getattr(cls, "_coral_stale_retry_patched", False):
        return True

    if not callable(getattr(cls, "render_stale_image", None)):
        print(
            "[trame-vtk-patch] stale-retry fix skipped: render_stale_image is "
            "gone. Upstream API changed — check whether this patch is still "
            "needed before removing it."
        )
        return False

    def render_stale_image(self, v_id, stale_count=0):
        # `time` and `schedule_callback` are resolved from the upstream module,
        # exactly as upstream's own implementation does.
        if v_id in self.stale_handler_count and self.stale_handler_count[v_id] > 0:
            self.stale_handler_count[v_id] -= 1

            if self.last_stale_time[v_id] != 0:
                delta = delivery.time.time() - self.last_stale_time[v_id]
                required = self.delta_stale_time_before_render * (stale_count + 1)
                if delta >= required and stale_count < self.stale_count_limit:
                    self.push_render(v_id, False, stale_count + 1)
                elif stale_count < self.stale_count_limit:
                    self.stale_handler_count[v_id] += 1
                    delivery.schedule_callback(
                        max(0.001, required - delta + 0.001),
                        lambda: self.render_stale_image(v_id, stale_count),
                    )

    cls.render_stale_image = render_stale_image
    cls._coral_stale_retry_patched = True
    debug_log("[trame-vtk-patch] stale-retry fix applied", flush=True)
    return True


def apply_all():
    """Apply every upstream patch. Call once, before the server starts."""
    return {"stale_retry_fix": apply_stale_retry_fix()}
