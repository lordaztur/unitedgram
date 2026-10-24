import asyncio

import httpx
import pytest

from bridge import clean_html, site_message_text
from formatting import format_discord_body, format_reactions_discord, format_reactions_telegram
from site_listener import deliver_message, schedule_reaction_update
from tests.test_site_listener import FakeApp, FakeBot, FakeSentMessage, _bridge_returning


class StubBridge:
    aliases = ()


REACTIONS = [
    {"emoji": "👍", "count": 2, "users": ["alice", "bob"]},
    {"emoji": "🔥", "count": 1, "users": ["carol"]},
]


class TestQuoteAndReplyParsing:
    def test_inverted_quote_keeps_leading_text(self):
        html = ('minha resposta<blockquote><cite><i class="fas fa-quote-left"></i> alice</cite>'
                '<div>texto original</div></blockquote>')
        out = clean_html(html)
        assert out.startswith("[quote=alice]")
        assert out.endswith("minha resposta")
        assert "minha resposta" in format_discord_body(StubBridge(), out)

    def test_inverted_quote_keeps_text_on_both_sides(self):
        html = 'antes<blockquote>@alice: citado</blockquote>depois'
        out = clean_html(html)
        assert out.startswith("[quote=alice]citado[/quote]")
        assert "antes" in out and "depois" in out

    def test_reply_to_becomes_quote(self):
        m = {"message": "Sim", "reply_to": {"id": 1, "user": {"username": "fluxldu"}, "excerpt": "apareço na lista?"}}
        assert site_message_text(m) == "[quote=fluxldu]apareço na lista?[/quote]\nSim"
        body = format_discord_body(StubBridge(), site_message_text(m))
        assert body.startswith("respondeu a **fluxldu**")

    def test_reply_to_ignored_when_message_has_quote(self):
        m = {"message": "<blockquote>@bob: x</blockquote>y",
             "reply_to": {"user": {"username": "alice"}, "excerpt": "z"}}
        assert site_message_text(m).count("[quote=") == 1
        assert "[quote=bob]" in site_message_text(m)


class TestReactionFormatting:
    def test_telegram(self):
        out = format_reactions_telegram(REACTIONS)
        assert out == "\n\n👍 <i>alice, bob</i>\n🔥 <i>carol</i>"

    def test_discord(self):
        assert format_reactions_discord(REACTIONS) == "`👍 alice, bob`  `🔥 carol`"

    def test_empty(self):
        assert format_reactions_telegram([]) == ""
        assert format_reactions_discord(None) == ""
        assert format_reactions_discord([{"emoji": "👍", "users": []}]) == ""


class EditingBot(FakeBot):
    def __init__(self, script=()):
        super().__init__(script)
        self.edits = []

    async def edit_message_text(self, **kwargs):
        self.edits.append(("text", kwargs))

    async def edit_message_caption(self, **kwargs):
        self.edits.append(("caption", kwargs))


@pytest.mark.asyncio
class TestStickerAndReactionsDelivery:
    async def test_sticker_sent_as_photo_and_reactions_in_caption(self):
        bridge = _bridge_returning([])

        async def fake_sticker(m):
            return b"\x89PNGdata", "png"
        bridge.get_site_sticker = fake_sticker

        bot = EditingBot([FakeSentMessage(message_id=10)])
        m = {"id": 500, "message": "", "user": {"id": 1, "username": "b1guuuu"},
             "sticker": {"url": f"{bridge.base_url}/authenticated-images/stickers/18"},
             "reactions": REACTIONS[:1]}
        try:
            await deliver_message(bridge, FakeApp(bridge, bot), None, m)
            assert bot.photo_args == [b"\x89PNGdata"]
            entry = bridge.msg_map[10]
            assert entry["platform"] == "tg" and entry["kind"] == "caption"
            assert "👍" not in entry["render"]
        finally:
            await bridge.close()

    async def test_reaction_event_edits_telegram_message(self):
        bridge = _bridge_returning([])
        bot = EditingBot([FakeSentMessage(message_id=11)])
        app = FakeApp(bridge, bot)
        bridge.telegram_app = app
        m = {"id": 501, "message": "oi", "user": {"id": 1, "username": "alice"}, "reactions": []}
        try:
            await deliver_message(bridge, app, None, m)
            schedule_reaction_update(bridge, 501, REACTIONS)
            schedule_reaction_update(bridge, 501, REACTIONS[:1])
            await asyncio.gather(*list(bridge.reaction_tasks.values()))
            kind, kwargs = bot.edits[-1]
            assert kind == "text"
            assert kwargs["message_id"] == 11
            assert kwargs["text"].endswith("👍 <i>alice, bob</i>")
            assert "🔥" not in kwargs["text"]
        finally:
            await bridge.close()

    async def test_reaction_for_unknown_message_is_ignored(self):
        bridge = _bridge_returning([])
        try:
            schedule_reaction_update(bridge, 999, REACTIONS)
            assert not bridge.reaction_tasks
        finally:
            await bridge.close()


@pytest.mark.asyncio
class TestSiteReactionApi:
    def _bridge(self, state):
        def handler(req):
            if req.url.path == "/api/chat/config":
                return httpx.Response(200, json={"reactions": ["👍", "❤️"]})
            emoji = req.read().decode("utf-8")
            assert "reaction" in req.url.path and emoji
            state["on"] = not state["on"]
            users = ["wastaken"] if state["on"] else []
            state["calls"] += 1
            return httpx.Response(200, json={"data": {"id": 1, "reactions": [
                {"emoji": "👍", "count": len(users), "users": users}] if users else []}})
        bridge = _bridge_returning([])
        bridge.client = httpx.AsyncClient(base_url=bridge.base_url, transport=httpx.MockTransport(handler))
        bridge.aliases = ("wastaken",)
        return bridge

    async def test_normalize_reaction(self):
        bridge = self._bridge({"on": False, "calls": 0})
        try:
            assert await bridge.normalize_reaction("❤") == "❤️"
            assert await bridge.normalize_reaction("🦄") is None
        finally:
            await bridge.close()

    async def test_set_reaction_is_idempotent(self):
        state = {"on": True, "calls": 0}
        bridge = self._bridge(state)
        try:
            # já reagido no site: o toggle remove, então set_reaction precisa desfazer
            reactions = await bridge.set_reaction(1, "👍", True)
            assert state["on"] is True and state["calls"] == 2
            assert reactions[0]["users"] == ["wastaken"]
            await bridge.set_reaction(1, "👍", False)
            assert state["on"] is False and state["calls"] == 3
        finally:
            await bridge.close()


class TestTelegramReactionLimits:
    def test_drops_reaction_lines_instead_of_cutting_html(self):
        from site_listener import _with_telegram_reactions
        base = "x" * 1000
        out = _with_telegram_reactions(base, REACTIONS, 1024)
        assert out == base + "\n\n👍 <i>alice, bob</i>"
        assert _with_telegram_reactions(base, REACTIONS, 1005) == base
        assert _with_telegram_reactions("oi", REACTIONS, 4096).endswith("🔥 <i>carol</i>")
