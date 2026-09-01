"""Regression coverage for stage-aware WeChat outbound media failures."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from lingtai.mcp_servers.wechat import api, media
from lingtai.mcp_servers.wechat.manager import WechatManager
from lingtai.mcp_servers.wechat.types import GetUploadUrlResp, WeixinMessage


BASE_URL = "https://ilink.example.test"
PRESIGNED_URL = (
    "https://cdn.example.test/upload?token=secret-token&signature=secret-signature"
)



def _send_response(content: bytes) -> httpx.Response:
    return httpx.Response(
        200,
        content=content,
        request=httpx.Request("POST", f"{BASE_URL}/ilink/bot/sendmessage"),
    )


def test_send_message_uses_tencent_246_identity_and_safe_acceptance(monkeypatch) -> None:
    captured = {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            captured.update({"url": url, **kwargs})
            return _send_response(json.dumps({
                "ret": 0, "errcode": 0, "errmsg": "ok", "private": "drop"
            }).encode("utf-8"))

    monkeypatch.setattr(api.httpx, "AsyncClient", FakeClient)
    ack = asyncio.run(api.send_message(
        BASE_URL, "test-token",
        WeixinMessage(to_user_id="wxid-recipient", client_id="client-id"),
    ))

    assert captured["json"]["base_info"] == {
        "channel_version": "2.4.6", "bot_agent": "LingTai"
    }
    assert captured["headers"]["iLink-App-ClientVersion"] == "132102"
    assert ack == {"ret": 0, "errcode": 0}


@pytest.mark.parametrize("body, expected", [
    ({"ret": 0}, {"ret": 0}),
    ({"ret": 0, "errcode": 0}, {"ret": 0, "errcode": 0}),
    ({"ret": 0, "errcode": 0, "errmsg": "ok"}, {"ret": 0, "errcode": 0}),
])
def test_send_ack_explicit_zero_ret_accepted(body: dict, expected: dict) -> None:
    response = _send_response(json.dumps(body).encode("utf-8"))
    assert api._parse_send_acknowledgement(response) == expected


@pytest.mark.parametrize("body", [
    {}, {"ret": None}, {"errcode": 0}, {"ret": None, "errcode": 0},
])
def test_send_ack_missing_or_null_ret_accepted(body: dict) -> None:
    """Missing/null ret is provider acceptance per the official client."""
    response = _send_response(json.dumps(body).encode("utf-8"))
    assert api._parse_send_acknowledgement(response) == {"ret": 0}


@pytest.mark.parametrize("body", [
    {"ret": "0"}, {"ret": True}, {"ret": 0.0}, {"ret": []},
    {"ret": 17}, {"ret": -3},
    {"ret": 17, "errcode": 0},
    {"ret": 0.0, "errcode": 0},
    {"ret": False, "errcode": 0},
])
def test_send_ack_invalid_ret_rejected(body: dict) -> None:
    response = _send_response(json.dumps(body).encode("utf-8"))
    with pytest.raises(RuntimeError, match="invalid acknowledgement"):
        api._parse_send_acknowledgement(response)


@pytest.mark.parametrize("body", [
    {"errcode": 9},
    {"ret": None, "errcode": 9},
    {"ret": None, "errcode": "9"},
    {"ret": None, "errcode": True},
    {"ret": None, "errcode": None},
    {"ret": None, "errcode": 0.0},
    {"ret": 0, "errcode": 9},
])
def test_send_ack_nonzero_or_invalid_errcode_rejected(body: dict) -> None:
    """A nonzero/invalid errcode fails even when ret is missing or null."""
    response = _send_response(json.dumps(body).encode("utf-8"))
    with pytest.raises(RuntimeError, match="invalid acknowledgement"):
        api._parse_send_acknowledgement(response)


@pytest.mark.parametrize("content", [b"", b"not-json", b"[]"])
def test_send_ack_rejects_empty_malformed_or_nonobject(content: bytes) -> None:
    with pytest.raises(RuntimeError):
        api._parse_send_acknowledgement(_send_response(content))


def test_send_ack_logs_structural_telemetry_not_raw_body(caplog) -> None:
    """Warnings contain bounded shape telemetry, never the raw response body."""
    import logging
    body = {"ret": None, "errmsg": "something", "private": "secret-value-xyz"}
    with caplog.at_level(logging.WARNING):
        api._parse_send_acknowledgement(
            _send_response(json.dumps(body).encode("utf-8"))
        )
    assert "missing/null ret" in caplog.text
    assert "response_shape=" in caplog.text
    assert "secret-value-xyz" not in caplog.text
    assert "something" not in caplog.text
    assert '"field_count":3' in caplog.text
    assert '"has_ret":true' in caplog.text
    assert '"has_errcode":false' in caplog.text
    assert '"ret":null' in caplog.text


def test_send_ack_shape_omits_keys_values_and_nested_topology(caplog) -> None:
    """Arbitrary key strings and nested payloads cannot leak or amplify logs."""
    import logging
    secret_key = "https://provider.invalid/callback?token=secret-in-key"
    body = {
        "ret": None,
        secret_key: [{"nested-secret-key": "nested-secret-value"}] * 1000,
        "password_is_correct": True,
    }
    with caplog.at_level(logging.WARNING):
        api._parse_send_acknowledgement(
            _send_response(json.dumps(body).encode("utf-8"))
        )
    assert "response_shape=" in caplog.text
    assert secret_key not in caplog.text
    assert "nested-secret-key" not in caplog.text
    assert "nested-secret-value" not in caplog.text
    assert '"password_is_correct":true' not in caplog.text
    assert '"field_count":3' in caplog.text
    assert len(caplog.text) < 1000


def test_safe_ack_shape_does_not_traverse_deep_unknown_fields() -> None:
    nested: object = "leaf-secret"
    for _ in range(2000):
        nested = {"secret-key": nested}
    assert api._safe_ack_shape({"ret": None, "opaque": nested}) == {
        "field_count": 2,
        "has_ret": True,
        "has_errcode": False,
        "ret": None,
    }


def test_send_ack_skips_shape_when_warning_disabled(monkeypatch) -> None:
    monkeypatch.setattr(api.log, "isEnabledFor", lambda level: False)
    monkeypatch.setattr(
        api,
        "_safe_ack_shape",
        lambda body: pytest.fail("shape must not be built when warning is disabled"),
    )
    response = _send_response(b'{"ret":null,"opaque":{"secret":"value"}}')
    assert api._parse_send_acknowledgement(response) == {"ret": 0}


@pytest.mark.parametrize(("body", "secret"), [
    ({"ret": "ret-secret-value"}, "ret-secret-value"),
    ({"ret": None, "errcode": "errcode-secret-value"}, "errcode-secret-value"),
])
def test_send_ack_invalid_diagnostic_values_redacted(caplog, body, secret) -> None:
    """Even malformed ret/errcode values are reduced to structural telemetry."""
    import logging
    with caplog.at_level(logging.WARNING), pytest.raises(
        RuntimeError, match="invalid acknowledgement"
    ):
        api._parse_send_acknowledgement(
            _send_response(json.dumps(body).encode("utf-8"))
        )
    assert secret not in caplog.text
    assert "<str:" in caplog.text


def test_safe_ack_diagnostic_keeps_only_signed_64bit_ints() -> None:
    assert api._safe_ack_diagnostic(-(1 << 63)) == -(1 << 63)
    assert api._safe_ack_diagnostic((1 << 63) - 1) == (1 << 63) - 1
    assert api._safe_ack_diagnostic(-(1 << 63) - 1) == "<int:64bits>"
    assert api._safe_ack_diagnostic(1 << 63) == "<int:64bits>"


@pytest.mark.parametrize(("field", "sign"), [
    ("ret", 1),
    ("ret", -1),
    ("errcode", 1),
    ("errcode", -1),
])
def test_send_ack_huge_integer_diagnostics_are_bounded(
    caplog, field: str, sign: int
) -> None:
    """Huge provider integers never escape raw through warnings or errors."""
    import logging
    digits = "9" * 4000
    raw = digits if sign > 0 else f"-{digits}"
    value = int(raw)
    body = {"ret": value} if field == "ret" else {"ret": None, "errcode": value}

    with caplog.at_level(logging.WARNING), pytest.raises(RuntimeError) as exc_info:
        api._parse_send_acknowledgement(
            _send_response(json.dumps(body).encode("utf-8"))
        )

    error_text = str(exc_info.value)
    assert raw not in caplog.text
    assert raw not in error_text
    assert "<int:" in caplog.text
    assert "<int:" in error_text
    assert len(caplog.text) < 1000
    assert len(error_text) < 300


def test_public_send_result_is_acceptance_not_delivery(monkeypatch, tmp_path: Path) -> None:
    manager = WechatManager(
        token="test-token", user_id="test-bot", working_dir=tmp_path,
        on_inbound=lambda event: None,
    )

    async def accept(*args, **kwargs):
        return {"ret": 0}

    monkeypatch.setattr(api, "send_message", accept)
    monkeypatch.setattr(manager, "_run_async", asyncio.run)
    result = manager._handle_send({"user_id": "wxid-recipient", "text": "hello"})

    assert result["status"] == "ok"
    assert result["delivery_status"] == "provider_accepted"
    assert result["delivery_confirmed"] is False
    assert result["automatic_retry_allowed"] is False
    stored = (tmp_path / "wechat" / "sent" / result["message_id"] / "message.json")
    stored_data = json.loads(stored.read_text(encoding="utf-8"))
    assert stored_data["delivery_status"] == "provider_accepted"
    assert stored_data["delivery_confirmed"] is False


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
        return {"ret": 0}

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
    assert result["partial_provider_acceptance"] is True
    assert result["delivery_status"] == "partial_provider_acceptance"
    assert result["delivery_confirmed"] is False
    assert result["automatic_retry_allowed"] is False
    assert result["sent"] == ["text (12 chars)"]
    assert result["stage"] == "cdn_tls_handshake_failed"
    assert result["media_upload"]["endpoint"] == "https://cdn.example.test"
    assert result["message_id"]
    stored = tmp_path / "wechat" / "sent" / result["message_id"] / "message.json"
    assert stored.is_file()
    assert '"status": "partial"' in stored.read_text(encoding="utf-8")
    assert "bearer-secret" not in stored.read_text(encoding="utf-8")
    assert "wxid-recipient" in stored.read_text(encoding="utf-8")
