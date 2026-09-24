import httpx
import pytest

from bridge import ChatBridge
from config import settings


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["imgbb", "passtheimage"])
async def test_upload_message_uses_selected_host(monkeypatch, host):
    monkeypatch.setenv("IMAGE_HOST", host)
    monkeypatch.setenv("IMGBB_API_KEY", "imgbb-secret")
    monkeypatch.setenv("PASSTHEIMAGE_API_KEY", "passtheimage-secret")
    monkeypatch.setattr(settings, "image_msg_expiration_seconds", 43200)

    def handler(request):
        body = request.content.decode("latin1")
        assert 'filename="photo.png"' in body
        if host == "imgbb":
            assert str(request.url) == "https://api.imgbb.com/1/upload"
            assert 'name="image"' in body
            assert 'name="key"' in body and "imgbb-secret" in body
            assert "43200" in body
            return httpx.Response(200, json={"data": {"url": "https://i.ibb.co/photo.png"}})
        assert str(request.url) == "https://passtheima.ge/api/1/upload"
        assert request.headers["X-API-Key"] == "passtheimage-secret"
        assert 'name="source"' in body
        assert "PT43200S" in body
        return httpx.Response(200, json={"status_code": 200, "image": {"url": "https://passtheima.ge/images/photo.png"}})

    bridge = ChatBridge.from_env()
    await bridge.upload_client.aclose()
    bridge.upload_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        url = await bridge.upload_image(b"image bytes", ephemeral=True, filename="photo.png")
        assert url == ("https://i.ibb.co/photo.png" if host == "imgbb" else "https://passtheima.ge/images/photo.png")
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_passtheimage_avatar_has_no_expiration(monkeypatch):
    monkeypatch.setenv("IMAGE_HOST", "passtheimage")
    monkeypatch.setenv("PASSTHEIMAGE_API_KEY", "secret")

    def handler(request):
        assert b'expiration' not in request.content
        return httpx.Response(200, json={"image": {"url": "https://passtheima.ge/images/avatar.png"}})

    bridge = ChatBridge.from_env()
    await bridge.upload_client.aclose()
    bridge.upload_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert await bridge.upload_image(b"avatar") == "https://passtheima.ge/images/avatar.png"
    finally:
        await bridge.close()
