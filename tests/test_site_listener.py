import httpx
import pytest

from bridge import ChatBridge
from site_listener import initial_backfill


pytestmark = pytest.mark.asyncio


class FakeApp:
    def __init__(self, bridge):
        self.bot_data = {"bridge": bridge}


def _bridge_returning(messages):
    def handler(req):
        return httpx.Response(200, json={"data": messages})
    bridge = ChatBridge.from_env()
    bridge.client = httpx.AsyncClient(
        base_url=bridge.base_url,
        transport=httpx.MockTransport(handler),
    )
    return bridge


class TestInitialBackfill:
    async def test_marks_old_as_seen_keeps_last_10(self):
        msgs = [{"id": i} for i in range(1, 101)]
        bridge = _bridge_returning(msgs)
        try:
            await initial_backfill(FakeApp(bridge))
            assert bridge.last_seen_id == 90
            assert 1 in bridge.queued_ids
            assert 90 in bridge.queued_ids
            assert 91 not in bridge.queued_ids
        finally:
            await bridge.close()

    async def test_no_messages_is_noop(self):
        bridge = _bridge_returning([])
        try:
            await initial_backfill(FakeApp(bridge))
            assert bridge.last_seen_id == 0
            assert len(bridge.queued_ids) == 0
        finally:
            await bridge.close()

    async def test_less_than_10_messages_no_skip(self):
        msgs = [{"id": i} for i in range(1, 6)]
        bridge = _bridge_returning(msgs)
        try:
            await initial_backfill(FakeApp(bridge))
            assert len(bridge.queued_ids) == 0
            assert bridge.last_seen_id == 0
        finally:
            await bridge.close()

    async def test_subsequent_enqueue_skips_old(self):
        msgs = [{"id": i} for i in range(1, 101)]
        bridge = _bridge_returning(msgs)
        try:
            await initial_backfill(FakeApp(bridge))
            assert bridge.enqueue_message({"id": 50}) is False
            assert bridge.enqueue_message({"id": 150}) is True
        finally:
            await bridge.close()
