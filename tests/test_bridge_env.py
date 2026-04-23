import pytest

from bridge import BridgeConfig, ChatBridge, REQUIRED_ENV, _compose_ws_host


class TestComposeWsHost:
    def test_no_port_returns_host_unchanged(self):
        assert _compose_ws_host("https://x.com:8443", None) == "https://x.com:8443"
        assert _compose_ws_host("https://x.com", None) == "https://x.com"

    def test_port_override_replaces_existing(self):
        assert _compose_ws_host("https://x.com:8443", "9000") == "https://x.com:9000"

    def test_port_added_when_absent(self):
        assert _compose_ws_host("https://x.com", "8443") == "https://x.com:8443"

    def test_preserves_path(self):
        assert _compose_ws_host("https://x.com:8443/socket", "9000") == "https://x.com:9000/socket"

    def test_http_scheme_supported(self):
        assert _compose_ws_host("http://x.com:6001", "7001") == "http://x.com:7001"

    def test_malformed_host_returned_unchanged(self):
        assert _compose_ws_host("not-a-url", "9000") == "not-a-url"


class TestBridgeConfigFromEnv:
    def test_success_with_all_vars(self):
        cfg = BridgeConfig.from_env()
        assert cfg.base_url == "https://example.test"
        assert cfg.chatroom_id == 1

    def test_ws_host_gets_default_port_8443(self, monkeypatch):
        monkeypatch.setenv("WS_HOST", "https://x.com")
        monkeypatch.delenv("WS_PORT", raising=False)
        cfg = BridgeConfig.from_env()
        assert cfg.ws_host == "https://x.com:8443"

    def test_ws_host_respects_explicit_ws_port(self, monkeypatch):
        monkeypatch.setenv("WS_HOST", "https://x.com")
        monkeypatch.setenv("WS_PORT", "6001")
        cfg = BridgeConfig.from_env()
        assert cfg.ws_host == "https://x.com:6001"

    def test_missing_ws_host_raises(self, monkeypatch):
        monkeypatch.delenv("WS_HOST", raising=False)
        with pytest.raises(RuntimeError, match="WS_HOST"):
            BridgeConfig.from_env()

    def test_missing_required_raises(self, monkeypatch):
        monkeypatch.delenv("COOKIE", raising=False)
        with pytest.raises(RuntimeError, match="COOKIE"):
            BridgeConfig.from_env()

    def test_all_required_listed_in_error(self, monkeypatch):
        for k in REQUIRED_ENV:
            monkeypatch.delenv(k, raising=False)
        with pytest.raises(RuntimeError) as exc:
            BridgeConfig.from_env()
        for k in REQUIRED_ENV:
            assert k in str(exc.value)

    def test_aliases_are_deduped_and_sorted_by_length(self, monkeypatch):
        monkeypatch.setenv("MY_USERNAME", "alice")
        monkeypatch.setenv("MY_ALIASES", "Alice, bob, alice ")
        cfg = BridgeConfig.from_env()
        assert "alice" in cfg.aliases
        assert "bob" in cfg.aliases
        assert list(cfg.aliases) == sorted(cfg.aliases, key=len, reverse=True)

    def test_is_frozen(self):
        cfg = BridgeConfig.from_env()
        with pytest.raises(Exception):
            cfg.base_url = "mutated"


class TestChatBridgeFromEnv:
    def test_delegates_to_config(self):
        bridge = ChatBridge.from_env()
        assert bridge.base_url == "https://example.test"
        assert bridge.ws_channel == "presence-chatroom.1"
        assert bridge.cfg.base_url == bridge.base_url

    def test_missing_required_raises(self, monkeypatch):
        monkeypatch.delenv("COOKIE", raising=False)
        with pytest.raises(RuntimeError, match="COOKIE"):
            ChatBridge.from_env()


class TestFindTgMsgId:
    @pytest.fixture
    def bridge(self):
        return ChatBridge.from_env()

    def test_returns_tg_id_when_site_id_exists(self, bridge):
        bridge.msg_map[999] = {"site_id": 42, "handle": "x", "text": ""}
        bridge.msg_map[1000] = {"site_id": 43, "handle": "y", "text": ""}
        assert bridge.find_tg_msg_id(42) == 999
        assert bridge.find_tg_msg_id(43) == 1000

    def test_returns_none_when_absent(self, bridge):
        bridge.msg_map[999] = {"site_id": 42, "handle": "x", "text": ""}
        assert bridge.find_tg_msg_id(9999) is None

    def test_returns_none_when_empty(self, bridge):
        assert bridge.find_tg_msg_id(42) is None


class TestEnqueueMessage:
    @pytest.fixture
    def bridge(self):
        return ChatBridge.from_env()

    def test_dedup(self, bridge):
        m = {"id": 42}
        assert bridge.enqueue_message(m) is True
        assert bridge.enqueue_message(m) is False

    def test_rejects_invalid_id(self, bridge):
        assert bridge.enqueue_message({"id": 0}) is False
        assert bridge.enqueue_message({"id": "x"}) is False
        assert bridge.enqueue_message({}) is False

    def test_updates_last_seen(self, bridge):
        bridge.enqueue_message({"id": 100})
        bridge.enqueue_message({"id": 50})
        assert bridge.last_seen_id == 100

    def test_evicts_oldest_when_full(self, bridge):
        bridge.queued_limit = 5
        for i in range(10):
            bridge.enqueue_message({"id": i + 1})
        assert len(bridge.queued_ids) == 5
        assert 1 not in bridge.queued_ids
        assert 10 in bridge.queued_ids
