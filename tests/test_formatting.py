from config import settings
from formatting import build_bbcode_payload, format_telegram_message


class StubBridge:
    def __init__(self, aliases=None):
        self.aliases = aliases or []


def _msg(username, text, extra=None):
    d = {"user": {"username": username}, "message": text}
    if extra:
        d.update(extra)
    return d


class TestFormatTelegramMessage:
    def setup_method(self):
        settings.telegram_user = "telegramhandle"

    def test_simple_text(self):
        bridge = StubBridge()
        out = format_telegram_message(bridge, _msg("alice", "oi"))
        assert "<b>alice</b>" in out
        assert "oi" in out

    def test_own_message_shows_voce(self):
        bridge = StubBridge(aliases=["lord"])
        out = format_telegram_message(bridge, _msg("Lord", "testando"))
        assert "Você" in out

    def test_empty_text(self):
        bridge = StubBridge()
        out = format_telegram_message(bridge, _msg("bob", ""))
        assert "enviou" in out

    def test_escapes_html_entities(self):
        bridge = StubBridge()
        out = format_telegram_message(bridge, _msg("<script>", "texto"))
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_bbcode_quote_renders_as_reply(self):
        bridge = StubBridge()
        msg = _msg("eve", "[quote=alice]texto citado[/quote]\nminha resposta")
        out = format_telegram_message(bridge, msg)
        assert "respondeu a" in out
        assert "<blockquote>" in out
        assert "texto citado" in out
        assert "minha resposta" in out

    def test_bbcode_quote_without_reply_renders_as_quoted(self):
        bridge = StubBridge()
        msg = _msg("eve", "[quote=alice]só citação[/quote]")
        out = format_telegram_message(bridge, msg)
        assert "citou" in out
        assert "<blockquote>" in out

    def test_reply_to_self_uses_telegram_handle(self):
        bridge = StubBridge(aliases=["alice"])
        msg = _msg("eve", "[quote=alice]x[/quote]\nresposta")
        out = format_telegram_message(bridge, msg)
        assert "@telegramhandle" in out

    def test_alias_in_text_gets_tagged(self):
        bridge = StubBridge(aliases=["alice"])
        msg = _msg("eve", "ei Alice olha isso")
        out = format_telegram_message(bridge, msg)
        assert "@telegramhandle" in out

    def test_no_tagging_when_telegram_user_empty(self):
        settings.telegram_user = ""
        bridge = StubBridge(aliases=["alice"])
        msg = _msg("eve", "ei Alice olha")
        out = format_telegram_message(bridge, msg)
        assert "@" not in out or "@telegramhandle" not in out

    def test_unknown_user_falls_back(self):
        bridge = StubBridge()
        msg = {"message": "só texto"}
        out = format_telegram_message(bridge, msg)
        assert "Desconhecido" in out


class TestBuildBbcodePayload:
    def test_basic(self):
        original = {"handle": "alice", "text": "mensagem original"}
        out = build_bbcode_payload(original, "minha resposta")
        assert out == "[quote=alice]mensagem original[/quote]\nminha resposta"

    def test_truncates_long_quoted_text(self):
        original = {"handle": "alice", "text": "x" * 500}
        out = build_bbcode_payload(original, "resp")
        assert "..." in out
        assert len(out) < 400

    def test_handle_at_sign_is_stripped(self):
        original = {"handle": "@alice", "text": "texto"}
        out = build_bbcode_payload(original, "r")
        assert "[quote=alice]" in out
        assert "@" not in out.split("[/quote]")[0]

    def test_escapes_bracket_characters_in_handle_and_text(self):
        original = {"handle": "al[ice]", "text": "[spoil]segredo[/spoil]"}
        out = build_bbcode_payload(original, "r")
        assert "[ice]" not in out
        assert "[spoil]segredo[/spoil]" not in out
