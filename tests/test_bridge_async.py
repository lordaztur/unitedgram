import httpx
import pytest

from bridge import ChatBridge


pytestmark = pytest.mark.asyncio


def _make_bridge_with_mock(handler):
    bridge = ChatBridge.from_env()
    bridge.client = httpx.AsyncClient(
        base_url=bridge.base_url,
        transport=httpx.MockTransport(handler),
    )
    return bridge


class TestFetchMessages:
    async def test_success(self):
        def handler(req):
            assert req.url.path == "/api/chat/messages/1"
            return httpx.Response(200, json={"data": [{"id": 1}, {"id": 2}]})
        bridge = _make_bridge_with_mock(handler)
        try:
            msgs = await bridge.fetch_messages()
            assert [m["id"] for m in msgs] == [1, 2]
        finally:
            await bridge.close()

    async def test_401_returns_empty(self):
        def handler(req):
            return httpx.Response(401, json={"message": "unauthenticated"})
        bridge = _make_bridge_with_mock(handler)
        try:
            msgs = await bridge.fetch_messages()
            assert msgs == []
        finally:
            await bridge.close()

    async def test_network_error_returns_empty(self):
        def handler(req):
            raise httpx.ConnectError("mock down")
        bridge = _make_bridge_with_mock(handler)
        try:
            msgs = await bridge.fetch_messages()
            assert msgs == []
        finally:
            await bridge.close()


class TestProbeSession:
    async def test_200(self):
        bridge = _make_bridge_with_mock(lambda req: httpx.Response(200, json={"data": []}))
        try:
            assert await bridge.probe_session() == 200
        finally:
            await bridge.close()

    async def test_401(self):
        bridge = _make_bridge_with_mock(lambda req: httpx.Response(401, json={"err": "x"}))
        try:
            assert await bridge.probe_session() == 401
        finally:
            await bridge.close()

    async def test_network_error_returns_minus_one(self):
        def handler(req):
            raise httpx.ConnectError("mock down")
        bridge = _make_bridge_with_mock(handler)
        try:
            assert await bridge.probe_session() == -1
        finally:
            await bridge.close()


class TestSendAndDelete:
    async def test_send_success(self):
        calls = []

        def handler(req):
            calls.append(req)
            return httpx.Response(200, json={"ok": True})
        bridge = _make_bridge_with_mock(handler)
        try:
            assert await bridge.send_message("hi") is True
            assert len(calls) == 1
        finally:
            await bridge.close()

    async def test_send_rejects_empty(self):
        bridge = _make_bridge_with_mock(lambda req: httpx.Response(500))
        try:
            assert await bridge.send_message("") is False
            assert await bridge.send_message("   ") is False
        finally:
            await bridge.close()

    async def test_delete_success(self):
        def handler(req):
            assert req.url.path == "/api/chat/message/42/delete"
            return httpx.Response(200, json={"ok": True})
        bridge = _make_bridge_with_mock(handler)
        try:
            assert await bridge.delete_message(42) is True
        finally:
            await bridge.close()

    async def test_delete_failure(self):
        bridge = _make_bridge_with_mock(lambda req: httpx.Response(403))
        try:
            assert await bridge.delete_message(42) is False
        finally:
            await bridge.close()


class TestEnqueueViaQueue:
    async def test_enqueue_puts_on_queue(self):
        bridge = ChatBridge.from_env()
        try:
            assert bridge.enqueue_message({"id": 7}) is True
            assert bridge.msg_queue.qsize() == 1
            item = await bridge.msg_queue.get()
            assert item["id"] == 7
        finally:
            await bridge.close()

    async def test_dedup_does_not_enqueue_twice(self):
        bridge = ChatBridge.from_env()
        try:
            assert bridge.enqueue_message({"id": 7}) is True
            assert bridge.enqueue_message({"id": 7}) is False
            assert bridge.msg_queue.qsize() == 1
        finally:
            await bridge.close()
