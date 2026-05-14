import httpx
import pytest
from telegram.error import BadRequest, TimedOut

import site_listener
from bridge import ChatBridge
from site_listener import deliver_message, initial_backfill


pytestmark = pytest.mark.asyncio


class FakeApp:
    def __init__(self, bridge, bot=None):
        self.bot_data = {"bridge": bridge}
        self.bot = bot


class FakeSentMessage:
    def __init__(self, message_id=999):
        self.message_id = message_id


class FakeBot:
    def __init__(self, script):
        self._script = list(script)
        self.calls = 0
        self.photo_args = []

    async def send_message(self, **kwargs):
        self.calls += 1
        outcome = self._script.pop(0) if self._script else FakeSentMessage()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def send_photo(self, **kwargs):
        self.calls += 1
        self.photo_args.append(kwargs.get("photo"))
        outcome = self._script.pop(0) if self._script else FakeSentMessage()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def send_media_group(self, **kwargs):
        self.calls += 1
        outcome = self._script.pop(0) if self._script else FakeSentMessage()
        if isinstance(outcome, BaseException):
            raise outcome
        return [outcome]


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


class TestDeliverMessage:
    @pytest.fixture(autouse=True)
    def _fast_retries(self, monkeypatch):
        monkeypatch.setattr(site_listener, "_NET_RETRY_BACKOFFS", (0, 0, 0))

    def _msg(self, mid=320789):
        return {"id": mid, "message": "ce ta com qnts torrents em semeadura?",
                "user": {"id": 1, "username": "csraquino"}}

    async def test_retries_timeout_then_succeeds(self):
        bridge = _bridge_returning([])
        bot = FakeBot([TimedOut(), TimedOut(), FakeSentMessage(message_id=42)])
        m = self._msg()
        try:
            bridge.enqueue_message(m)
            await deliver_message(FakeApp(bridge, bot), m)
            assert bot.calls == 3
            assert 42 in bridge.msg_map
            assert bridge.msg_map[42]["site_id"] == 320789
            assert 320789 in bridge.queued_ids
        finally:
            await bridge.close()

    async def test_persistent_timeout_releases_id_for_reconcile(self):
        bridge = _bridge_returning([])
        bot = FakeBot([TimedOut()] * 6)
        m = self._msg(320796)
        try:
            bridge.enqueue_message(m)
            assert 320796 in bridge.queued_ids
            await deliver_message(FakeApp(bridge, bot), m)
            assert bot.calls == 4
            assert not bridge.msg_map
            assert 320796 not in bridge.queued_ids
        finally:
            await bridge.close()

    async def test_external_url_passed_directly_no_download(self):
        bridge = _bridge_returning([])

        async def explode(url):
            raise AssertionError(f"download_image não deve ser chamado para URL externa: {url}")
        bridge.download_image = explode

        bot = FakeBot([FakeSentMessage(message_id=77)])
        m = self._msg(320801)
        m["message"] = 'olha <img src="https://i.imgur.com/PdJtDFc.png"> ai'
        try:
            bridge.enqueue_message(m)
            await deliver_message(FakeApp(bridge, bot), m)
            assert bot.photo_args == ["https://i.imgur.com/PdJtDFc.png"]
            assert 77 in bridge.msg_map
        finally:
            await bridge.close()

    async def test_internal_url_downloaded_as_bytes(self):
        bridge = _bridge_returning([])
        downloaded = []

        async def fake_download(url):
            downloaded.append(url)
            return b"BYTES"
        bridge.download_image = fake_download

        bot = FakeBot([FakeSentMessage(message_id=88)])
        m = self._msg(320802)
        m["message"] = f'<img src="{bridge.base_url}/uploads/x.png">'
        try:
            bridge.enqueue_message(m)
            await deliver_message(FakeApp(bridge, bot), m)
            assert downloaded == [f"{bridge.base_url}/uploads/x.png"]
            assert bot.photo_args == [b"BYTES"]
            assert 88 in bridge.msg_map
        finally:
            await bridge.close()

    async def test_internal_url_download_fail_falls_back_to_url(self):
        bridge = _bridge_returning([])

        async def fake_download(url):
            return None
        bridge.download_image = fake_download

        bot = FakeBot([FakeSentMessage(message_id=99)])
        m = self._msg(320803)
        internal_url = f"{bridge.base_url}/uploads/y.png"
        m["message"] = f'<img src="{internal_url}">'
        try:
            bridge.enqueue_message(m)
            await deliver_message(FakeApp(bridge, bot), m)
            assert bot.photo_args == [internal_url]
            assert 99 in bridge.msg_map
        finally:
            await bridge.close()

    async def test_bad_request_with_failing_fallback_keeps_id(self):
        bridge = _bridge_returning([])
        bot = FakeBot([BadRequest("can't parse entities"), BadRequest("still bad")])
        m = self._msg(320700)
        try:
            bridge.enqueue_message(m)
            await deliver_message(FakeApp(bridge, bot), m)
            assert bot.calls == 2
            assert not bridge.msg_map
            assert 320700 in bridge.queued_ids
        finally:
            await bridge.close()
