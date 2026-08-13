"""Regression coverage for stage-aware WeChat outbound media failures."""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from lingtai.mcp_servers.wechat import api, media
from lingtai.mcp_servers.wechat.manager import WechatManager
from lingtai.mcp_servers.wechat.types import GetUploadUrlResp


BASE_URL = "https://ilink.example.test"
PRESIGNED_URL = (
    "https://cdn.example.test/upload?token=secret-token&signature=secret-signature"
)


def test_safe_endpoint_discards_path_and_presigned_query() -> None:
    assert media._safe_endpoint(PRESIGNED_URL) == "https://cdn.example.test"
    assert media._safe_endpoint("https://cdn.example.test:8443/private/path") == (
        "https://cdn.example.test:8443"
    )


def test_upload_url_tls_failure_has_stage_and_safe_runtime(monkeypatch, tmp_path: Path) -> None:
    file_path = tmp_path / "attachment.txt"
    file_path.write_text("attachment", encoding="utf-8")

    async def fail_get_upload_url(*args, **kwargs):
        raise httpx.ConnectError(
            "[SSL: SSLV3_ALERT_HANDSHAKE_FAILURE] "
            f"while connecting to {BASE_URL}/ilink/bot/getuploadurl?token=secret"
        )

    monkeypatch.setattr(api, "get_upload_url", fail_get_upload_url)

    with pytest.raises(media.MediaUploadError) as exc_info:
        asyncio.run(media.upload_media(file_path, BASE_URL, "bearer-secret", "wxid-secret"))

    error = exc_info.value
    payload = error.as_result()
    assert error.stage == "get_upload_url_failed"
    assert payload["media_upload"]["error_kind"] == "tls_handshake"
    assert payload["media_upload"]["endpoint"] == BASE_URL
    assert payload["media_upload"]["runtime"]["httpx"]
    assert "bearer-secret" not in str(payload)
    assert "wxid-secret" not in str(payload)
    assert "secret" not in str(payload)


def test_dynamic_cdn_tls_failure_reports_dynamic_host(monkeypatch, tmp_path: Path) -> None:
    file_path = tmp_path / "attachment.txt"
    file_path.write_text("attachment", encoding="utf-8")

    async def fake_get_upload_url(*args, **kwargs):
        return GetUploadUrlResp(upload_full_url=PRESIGNED_URL)

    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            raise httpx.ConnectError(
                "[SSL: SSLV3_ALERT_HANDSHAKE_FAILURE] "
                f"while connecting to {PRESIGNED_URL}"
            )

    monkeypatch.setattr(api, "get_upload_url", fake_get_upload_url)
    monkeypatch.setattr(media.httpx, "AsyncClient", lambda: FailingClient())

    with pytest.raises(media.MediaUploadError) as exc_info:
        asyncio.run(media.upload_media(file_path, BASE_URL, "bearer-secret", "wxid-secret"))

    error = exc_info.value
    assert error.stage == "cdn_tls_handshake_failed"
    assert error.diagnostic.endpoint == "https://cdn.example.test"
    assert error.diagnostic.error_kind == "tls_handshake"
    assert "secret-token" not in str(error)


def test_text_plus_media_returns_partial_result_and_persists_status(
    monkeypatch, tmp_path: Path,
) -> None:
    manager = WechatManager(
        token="bearer-secret",
        user_id="test-bot",
        working_dir=tmp_path,
        on_inbound=lambda event: None,
    )
    file_path = tmp_path / "attachment.txt"
    file_path.write_text("attachment", encoding="utf-8")

    async def send_text(*args, **kwargs):
        return None

    async def fail_upload(*args, **kwargs):
        raise media.media_upload_error(
            "cdn_tls_handshake_failed", PRESIGNED_URL,
            httpx.ConnectError("[SSL: TLSV1_ALERT_HANDSHAKE_FAILURE]"),
        )

    monkeypatch.setattr(api, "send_message", send_text)
    monkeypatch.setattr(media, "upload_media", fail_upload)
    monkeypatch.setattr(manager, "_run_async", asyncio.run)

    result = manager._handle_send({
        "user_id": "wxid-recipient",
        "text": "text control",
        "media_path": str(file_path),
    })

    assert result["status"] == "partial"
    assert result["partial_delivery"] is True
    assert result["sent"] == ["text (12 chars)"]
    assert result["stage"] == "cdn_tls_handshake_failed"
    assert result["media_upload"]["endpoint"] == "https://cdn.example.test"
    assert result["message_id"]
    stored = tmp_path / "wechat" / "sent" / result["message_id"] / "message.json"
    assert stored.is_file()
    assert '"status": "partial"' in stored.read_text(encoding="utf-8")
    assert "bearer-secret" not in stored.read_text(encoding="utf-8")
    assert "wxid-recipient" in stored.read_text(encoding="utf-8")
