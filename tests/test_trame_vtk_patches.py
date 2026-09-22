"""Unit tests for the upstream trame-vtk runtime patches."""

import heapq
from types import SimpleNamespace

import pytest

from trame_vtk_patches import apply_stale_retry_fix

pytest.importorskip("trame_vtk.modules.paraview.protocols.publish_image_delivery")

from trame_vtk.modules.paraview.protocols import (  # noqa: E402
    publish_image_delivery as delivery,
)

VIEW = "1"
# The protocol treats last_stale_time == 0 as "not stale", so the virtual clock
# starts from a wall-clock-like origin rather than from zero.
EPOCH = 1000.0


class Clock:
    def __init__(self):
        self.now = EPOCH

    def time(self):
        return self.now


class Scheduler:
    """Deterministic stand-in for wslink.schedule_callback."""

    def __init__(self, clock):
        self.clock = clock
        self.queue = []
        self.seq = 0

    def schedule(self, delay, callback):
        assert delay > 0, "a non-positive delay would busy-loop the event loop"
        self.seq += 1
        heapq.heappush(self.queue, (self.clock.now + delay, self.seq, callback))

    def run(self, until, max_steps=1000):
        steps = 0
        while self.queue and self.queue[0][0] <= EPOCH + until:
            when, _, callback = heapq.heappop(self.queue)
            self.clock.now = when
            callback()
            steps += 1
            assert steps < max_steps, "retry chain did not terminate"
        self.clock.now = EPOCH + until


@pytest.fixture
def harness(monkeypatch):
    """A patched protocol instance with render and transport stubbed out."""
    assert apply_stale_retry_fix(), "patch did not apply"

    clock = Clock()
    scheduler = Scheduler(clock)
    monkeypatch.setattr(delivery, "time", clock)
    monkeypatch.setattr(delivery, "schedule_callback", scheduler.schedule)

    protocol = delivery.ParaViewWebPublishImageDelivery(decode=False)
    protocol.tracking_views[VIEW] = {
        "enabled": True,
        "originalSize": [300, 300],
        "ratio": 1,
        "mtime": 0,
        "quality": 100,
    }
    protocol.last_stale_time[VIEW] = 0
    protocol.stale_handler_count[VIEW] = 0

    state = SimpleNamespace(
        protocol=protocol,
        scheduler=scheduler,
        published=[],
        pushes=[],
        settle_after=0.0,
    )

    def still_render(_options):
        settled = clock.now - EPOCH >= state.settle_after
        return {
            "stale": not settled,
            "image": b"settled" if settled else b"in-progress",
            "mtime": 2 if settled else 1,
            "size": [300, 300],
        }

    protocol.still_render = still_render
    protocol.addAttachment = lambda image: image
    protocol.publish = lambda _topic, reply: state.published.append(reply["image"])

    push_render = protocol.push_render

    def record(v_id, ignore_animation=False, stale_count=0):
        state.pushes.append(stale_count)
        return push_render(v_id, ignore_animation, stale_count)

    protocol.push_render = record
    return state


def test_patch_is_idempotent():
    assert apply_stale_retry_fix()
    first = delivery.ParaViewWebPublishImageDelivery.render_stale_image
    assert apply_stale_retry_fix()
    assert delivery.ParaViewWebPublishImageDelivery.render_stale_image is first


def test_settled_frame_is_delivered_after_several_stale_replies(harness):
    """Without the patch the client is left on the in-progress frame."""
    harness.settle_after = harness.protocol.delta_stale_time_before_render * 2.4

    harness.protocol.push_render(VIEW)
    harness.scheduler.run(until=10.0)

    assert harness.published, "no frame was ever pushed"
    assert harness.published[-1] == b"settled"


def test_retry_chain_progresses_past_the_first_retry(harness):
    harness.settle_after = harness.protocol.delta_stale_time_before_render * 2.4

    harness.protocol.push_render(VIEW)
    harness.scheduler.run(until=10.0)

    assert max(harness.pushes) >= 2


def test_retry_chain_terminates_when_the_view_never_settles(harness):
    harness.settle_after = float("inf")

    harness.protocol.push_render(VIEW)
    harness.scheduler.run(until=600.0)

    assert not harness.scheduler.queue, "retry chain is still scheduling callbacks"
    assert max(harness.pushes) <= harness.protocol.stale_count_limit
