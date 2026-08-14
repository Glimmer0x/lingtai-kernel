"""Focused regression coverage for official CDN URL + bounded retry."""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from lingtai.mcp_servers.wechat import api, media
from lingtai.mcp_servers.wechat.types import GetUploadUrlResp


BASE_URL = "https://ilink.example.test"
CDN_BASE = "https://cdn.example.test/c2c"
UPLOAD_PARAM = "secret-upload-param"
FILEKEY = "abcdef0123456789"


def _attachment(tmp_path: Path) -> Path:
    p = tmp_path / "attachment.txt"
    p.write_text("attachment", encoding="utf-8")
    return p


class _StaticClient:
    """In-memory httpx AsyncClient stand-in returning a fixed sequence."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.posts: list[tuple[str, bytes]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, *, content, headers=None, timeout=None):
        self.posts.append((url, content))
        if not self._responses:
            raise AssertionError("more posts than canned responses")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _Resp:
    def __init__(self, status_code=200, headers=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("POST", "https://cdn.example.test/"),
                response=httpx.Response(self.status_code, request=httpx.Request("POST", "https://cdn.example.test/")),
            )

    def json(self):
        import json
        return json.loads(self.text)


def test_official_cdn_url_preferred_when_upload_param_present(
    monkeypatch, tmp_path: Path
) -> None:
    file_path = _attachment(tmp_path)

    async def fake_get_upload_url(*args, **kwargs):
        return GetUploadUrlResp(
            upload_param=UPLOAD_PARAM,
            upload_full_url="https://dynamic.example.test/upload?token=leak",
        )

    client = _StaticClient([
        _Resp(headers={"x-encrypted-param": "download-param"}),
    ])
    monkeypatch.setattr(api, "get_upload_url", fake_get_upload_url)
    monkeypatch.setattr(media.httpx, "AsyncClient", lambda: client)

    info = asyncio.run(media.upload_media(
        file_path, BASE_URL, "bearer-secret", "wxid-secret",
        cdn_base_url=CDN_BASE,
    ))

    # Official static CDN URL was used, never the dynamic presigned fallback.
    assert len(client.posts) == 1
    url, _ = client.posts[0]
    assert url.startswith(f"{CDN_BASE}/upload?encrypted_query_param=")
    assert "token=leak" not in url
    assert info.cdn_media.encrypt_query_param == "download-param"


def test_fallback_dynamic_url_when_no_upload_param(monkeypatch, tmp_path: Path) -> None:
    file_path = _attachment(tmp_path)

    async def fake_get_upload_url(*args, **kwargs):
        return GetUploadUrlResp(upload_full_url="https://dynamic.example.test/upload?token=leak")

    client = _StaticClient([
        _Resp(headers={"x-encrypted-param": "download-param"}),
    ])
    monkeypatch.setattr(api, "get_upload_url", fake_get_upload_url)
    monkeypatch.setattr(media.httpx, "AsyncClient", lambda: client)

    info = asyncio.run(media.upload_media(file_path, BASE_URL, "bearer-secret", "wxid-secret"))
    assert info.cdn_media.encrypt_query_param == "download-param"


def test_cdn_upload_retries_transport_failure_then_succeeds(
    monkeypatch, tmp_path: Path
) -> None:
    file_path = _attachment(tmp_path)

    async def fake_get_upload_url(*args, **kwargs):
        return GetUploadUrlResp(upload_param=UPLOAD_PARAM)

    client = _StaticClient([
        httpx.ConnectError("boom one"),
        _Resp(headers={"x-encrypted-param": "download-param"}),
    ])
    monkeypatch.setattr(api, "get_upload_url", fake_get_upload_url)
    monkeypatch.setattr(media.httpx, "AsyncClient", lambda: client)

    info = asyncio.run(media.upload_media(
        file_path, BASE_URL, "bearer-secret", "wxid-secret",
        cdn_base_url=CDN_BASE,
    ))
    assert info.cdn_media.encrypt_query_param == "download-param"
    assert len(client.posts) == 2  # one failure, one retry


def test_cdn_upload_retries_missing_metadata_then_succeeds(
    monkeypatch, tmp_path: Path
) -> None:
    file_path = _attachment(tmp_path)

    async def fake_get_upload_url(*args, **kwargs):
        return GetUploadUrlResp(upload_param=UPLOAD_PARAM)

    client = _StaticClient([
        _Resp(headers={}, text=""),          # HTTP 200 but no encrypted metadata
        _Resp(headers={"x-encrypted-param": "download-param"}),
    ])
    monkeypatch.setattr(api, "get_upload_url", fake_get_upload_url)
    monkeypatch.setattr(media.httpx, "AsyncClient", lambda: client)

    info = asyncio.run(media.upload_media(
        file_path, BASE_URL, "bearer-secret", "wxid-secret",
        cdn_base_url=CDN_BASE,
    ))
    assert info.cdn_media.encrypt_query_param == "download-param"
    assert len(client.posts) == 2


def test_cdn_upload_gives_up_after_max_attempts(monkeypatch, tmp_path: Path) -> None:
    file_path = _attachment(tmp_path)

    async def fake_get_upload_url(*args, **kwargs):
        return GetUploadUrlResp(upload_param=UPLOAD_PARAM)

    client = _StaticClient([
        httpx.ConnectError("boom one"),
        httpx.ConnectError("boom two"),
        httpx.ConnectError("boom three"),
    ])
    monkeypatch.setattr(api, "get_upload_url", fake_get_upload_url)
    monkeypatch.setattr(media.httpx, "AsyncClient", lambda: client)

    with pytest.raises(media.MediaUploadError) as exc_info:
        asyncio.run(media.upload_media(
            file_path, BASE_URL, "bearer-secret", "wxid-secret",
            cdn_base_url=CDN_BASE,
        ))
    payload = exc_info.value.as_result()
    assert payload["media_upload"]["stage"] == "cdn_upload_http_failed"
    assert "bearer-secret" not in str(payload)
    assert "wxid-secret" not in str(payload)
    assert len(client.posts) == 3
