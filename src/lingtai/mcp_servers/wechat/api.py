"""HTTP wrappers for the iLink Bot API endpoints."""
from __future__ import annotations

import base64
import json
import logging
import os
import struct
from typing import Any

import httpx

from .types import (
    GetUpdatesResp, GetUploadUrlResp, GetConfigResp,
    WeixinMessage, msg_from_dict, msg_to_dict,
)

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
DEFAULT_LONG_POLL_TIMEOUT = 35.0
DEFAULT_SEND_TIMEOUT = 15.0

# iLink protocol identity, aligned with Tencent/openclaw-weixin 2.4.6.
# ClientVersion is 0x00MMNNPP for 2.4.6 => 132102.
_PKG_VERSION = "2.4.6"
_ILINK_APP_ID = "bot"
_ILINK_APP_CLIENT_VERSION = str((2 << 16) | (4 << 8) | 6)


def _ensure_trailing_slash(url: str) -> str:
    return url if url.endswith("/") else url + "/"


def _random_wechat_uin() -> str:
    """Generate X-WECHAT-UIN header value.

    Random uint32 → decimal string → base64.
    Matches the official Tencent/openclaw-weixin implementation.
    """
    uint32 = struct.unpack(">I", os.urandom(4))[0]
    return base64.b64encode(str(uint32).encode("utf-8")).decode("ascii")


def _common_headers() -> dict[str, str]:
    """Headers required by the iLink Bot API on every request (GET and POST).

    These were identified by comparing lingtai-wechat against the official
    Tencent/openclaw-weixin plugin.  Without them the server may reject or
    silently drop requests.
    """
    return {
        "X-WECHAT-UIN": _random_wechat_uin(),
        "iLink-App-Id": _ILINK_APP_ID,
        "iLink-App-ClientVersion": _ILINK_APP_CLIENT_VERSION,
    }


def _auth_headers(token: str | None) -> dict[str, str]:
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        **_common_headers(),
    }
    if token:
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


def _base_info() -> dict:
    return {"channel_version": _PKG_VERSION, "bot_agent": "LingTai"}


async def get_qrcode(base_url: str = DEFAULT_BASE_URL) -> dict:
    """Fetch a QR code for WeChat login.

    Returns dict with 'qrcode' (str) and 'qrcode_img_content' (str) keys.
    """
    url = _ensure_trailing_slash(base_url) + "ilink/bot/get_bot_qrcode?bot_type=3"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_common_headers(), timeout=15.0)
        resp.raise_for_status()
        return resp.json()


async def poll_qr_status(base_url: str, qrcode: str) -> dict:
    """Poll QR code login status. Returns dict with 'status' key.

    Status values: 'wait', 'scaned', 'confirmed', 'expired', 'scaned_but_redirect'.
    On 'confirmed': also has 'bot_token', 'ilink_bot_id', 'baseurl', 'ilink_user_id'.

    Network/gateway timeouts (e.g. Cloudflare 524) are treated as 'wait'
    so the caller can simply retry, matching the official Tencent plugin behavior.
    """
    url = (
        _ensure_trailing_slash(base_url)
        + f"ilink/bot/get_qrcode_status?qrcode={qrcode}"
    )
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url,
                headers=_common_headers(),
                timeout=DEFAULT_LONG_POLL_TIMEOUT + 5,
            )
            resp.raise_for_status()
            return resp.json()
    except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
        # Treat network/gateway timeouts as "still waiting" so the caller
        # can retry, matching the official Tencent plugin behavior.
        log.debug("poll_qr_status: network error, will retry: %s", e)
        return {"status": "wait"}


async def get_updates(
    base_url: str,
    token: str,
    get_updates_buf: str = "",
    timeout: float = DEFAULT_LONG_POLL_TIMEOUT,
) -> GetUpdatesResp:
    """Long-poll for incoming messages.

    Returns GetUpdatesResp with msgs list and updated get_updates_buf cursor.
    On client-side timeout, returns empty response to allow retry.
    """
    url = _ensure_trailing_slash(base_url) + "ilink/bot/getupdates"
    body = {
        "get_updates_buf": get_updates_buf,
        "base_info": _base_info(),
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                json=body,
                headers=_auth_headers(token),
                timeout=timeout + 5,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        # Server didn't respond in time — return empty to retry
        return GetUpdatesResp(
            ret=0, msgs=[], get_updates_buf=get_updates_buf,
        )

    msgs = [msg_from_dict(m) for m in data.get("msgs", [])]
    return GetUpdatesResp(
        ret=data.get("ret"),
        errcode=data.get("errcode"),
        errmsg=data.get("errmsg"),
        msgs=msgs,
        get_updates_buf=data.get("get_updates_buf", get_updates_buf),
        longpolling_timeout_ms=data.get("longpolling_timeout_ms"),
    )


async def send_message(
    base_url: str,
    token: str,
    msg: WeixinMessage,
) -> dict[str, int]:
    """Submit one recipient-visible request and return a safe provider ack.

    Success accepts a missing/null ``ret`` or an explicit non-boolean integer
    ``ret == 0`` only when ``errcode`` is absent or an integer zero. This is
    provider acceptance only; it does not confirm recipient delivery.
    """
    url = _ensure_trailing_slash(base_url) + "ilink/bot/sendmessage"
    body = {
        "msg": msg_to_dict(msg),
        "base_info": _base_info(),
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            json=body,
            headers=_auth_headers(token),
            timeout=DEFAULT_SEND_TIMEOUT,
        )
        resp.raise_for_status()
        return _parse_send_acknowledgement(resp)


def _ack_code(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# Only fixed diagnostic field names can enter telemetry. Arbitrary provider
# keys and opaque values are never copied, traversed, or serialized.
_SAFE_ACK_DIAGNOSTIC_KEYS = ("ret", "errcode")
_SAFE_ACK_INT_MIN = -(1 << 63)
_SAFE_ACK_INT_MAX = (1 << 63) - 1


def _safe_ack_diagnostic(value: object) -> object:
    """Return bounded metadata for one fixed acknowledgement diagnostic."""
    if value is None:
        return None
    if _ack_code(value):
        if _SAFE_ACK_INT_MIN <= value <= _SAFE_ACK_INT_MAX:
            return value
        return f"<int:{value.bit_length()}bits>"
    if isinstance(value, str):
        return f"<str:{len(value)}>"
    return f"<{type(value).__name__}>"


def _safe_ack_shape(body: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded, secret-safe description of an acknowledgement body."""
    shape: dict[str, Any] = {
        "field_count": len(body),
        "has_ret": "ret" in body,
        "has_errcode": "errcode" in body,
    }
    for key in _SAFE_ACK_DIAGNOSTIC_KEYS:
        if key in body:
            shape[key] = _safe_ack_diagnostic(body[key])
    return shape


def _log_ack_warning(message: str, body: dict[str, Any]) -> None:
    """Log one bounded acknowledgement warning only when it will be emitted."""
    if not log.isEnabledFor(logging.WARNING):
        return
    log.warning(
        "%s response_shape=%s",
        message,
        json.dumps(_safe_ack_shape(body), ensure_ascii=False, separators=(",", ":")),
    )


def _parse_send_acknowledgement(resp: "httpx.Response") -> dict[str, int]:
    """Parse iLink sendmessage acknowledgement.

    Mirrors the official OpenClaw/Tencent client: a missing or null ``ret``
    field is treated as provider acceptance (the protocol declares it
    optional). Any non-zero integer or non-integer ``ret`` is still a failure.
    A nonzero or non-integer ``errcode`` is also a failure, even when ``ret``
    is missing or null.  Only secret-safe structural telemetry is logged when
    the acknowledgement deviates from the explicit ``{"ret": 0}`` shape.
    """
    if not resp.text.strip():
        raise RuntimeError("iLink send_message returned an empty response")
    try:
        body = resp.json()
    except ValueError as exc:
        raise RuntimeError("iLink send_message returned malformed JSON") from exc
    if not isinstance(body, dict):
        raise RuntimeError("iLink send_message returned non-object JSON")

    ret = body.get("ret")

    # Validate errcode first and independent of ret so that a missing or null
    # ret never bypasses an explicit nonzero/invalid errcode.
    if "errcode" in body:
        errcode = body.get("errcode")
        if not _ack_code(errcode) or errcode != 0:
            detail = (
                _safe_ack_diagnostic(errcode) if _ack_code(errcode) else "<invalid>"
            )
            _log_ack_warning(
                "iLink send_message returned non-zero/invalid errcode;", body
            )
            raise RuntimeError(
                "iLink send_message returned invalid acknowledgement: "
                f"errcode={detail}"
            )

    if ret is None:
        _log_ack_warning(
            "iLink send_message returned missing/null ret; treating as provider "
            "acceptance per official protocol.",
            body,
        )
        return {"ret": 0}

    if not _ack_code(ret):
        _log_ack_warning(
            "iLink send_message returned invalid ret type;", body
        )
        raise RuntimeError(
            "iLink send_message returned invalid acknowledgement: "
            f"ret=<invalid {type(ret).__name__}>"
        )

    if ret != 0:
        detail = _safe_ack_diagnostic(ret)
        _log_ack_warning(
            "iLink send_message returned non-zero ret;", body
        )
        raise RuntimeError(
            f"iLink send_message returned invalid acknowledgement: ret={detail}"
        )

    ack: dict[str, int] = {"ret": 0}
    if "errcode" in body:
        ack["errcode"] = 0
    return ack


async def get_upload_url(
    base_url: str,
    token: str,
    *,
    media_type: int,
    to_user_id: str,
    rawsize: int,
    rawfilemd5: str,
    filesize: int,
    aeskey: str | None = None,
    filekey: str | None = None,
    no_need_thumb: bool = True,
) -> GetUploadUrlResp:
    """Get a pre-signed CDN upload URL.

    iLink requires `filekey` (random 16-byte hex string) and `no_need_thumb`
    in the request body, even though they are not strictly part of the
    publicly documented schema. Without `filekey` the server may return
    HTTP 200 with `upload_full_url` omitted, causing the upload to silently
    fail downstream. Mirrors OpenClaw / Hermes behavior.
    """
    url = _ensure_trailing_slash(base_url) + "ilink/bot/getuploadurl"
    body: dict[str, Any] = {
        "media_type": media_type,
        "to_user_id": to_user_id,
        "rawsize": rawsize,
        "rawfilemd5": rawfilemd5,
        "filesize": filesize,
        "no_need_thumb": no_need_thumb,
        "base_info": _base_info(),
    }
    if filekey:
        body["filekey"] = filekey
    if aeskey:
        body["aeskey"] = aeskey
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            json=body,
            headers=_auth_headers(token),
            timeout=DEFAULT_SEND_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    return GetUploadUrlResp(
        upload_param=data.get("upload_param"),
        upload_full_url=data.get("upload_full_url"),
    )


async def get_config(base_url: str, token: str) -> GetConfigResp:
    """Get bot config (typing ticket etc.)."""
    url = _ensure_trailing_slash(base_url) + "ilink/bot/getconfig"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            json={"base_info": _base_info()},
            headers=_auth_headers(token),
            timeout=DEFAULT_SEND_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    return GetConfigResp(
        ret=data.get("ret"),
        errmsg=data.get("errmsg"),
        typing_ticket=data.get("typing_ticket"),
    )
