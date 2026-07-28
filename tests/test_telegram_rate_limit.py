"""Focused contract tests for Telegram Bot API 429 handling."""

from pathlib import Path
import time
from unittest.mock import Mock

import pytest

from lingtai.mcp_servers.telegram.account import (
    TelegramAccount,
    TelegramRateLimitError,
)
from lingtai.mcp_servers.telegram.manager import TelegramManager
from tests._notification_store_helpers import notification_store_for


class _Response:
    status_code = 429

    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.json_calls = 0

    def json(self) -> object:
        self.json_calls += 1
        return self.payload


class _Client:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    def post(self, url: str, **kwargs: object) -> _Response:
        self.calls.append((url, kwargs))
        return self.response


@pytest.mark.parametrize(
    ("payload", "expected_retry_after"),
    [
        ({"parameters": {"retry_after": 37}}, 37),
        ({}, None),
        ({"parameters": {"retry_after": "37"}}, None),
        ({"parameters": {"retry_after": True}}, None),
        ({"parameters": {"retry_after": -1}}, None),
    ],
)
def test_429_fails_fast_without_sleep_or_second_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
    expected_retry_after: int | None,
) -> None:
    response = _Response(payload)
    client = _Client(response)
    account = TelegramAccount(
        alias="bot",
        bot_token="123:test",
        allowed_users=None,
        state_dir=tmp_path,
    )
    account._client = client
    sleep = Mock()
    monkeypatch.setattr(time, "sleep", sleep)

    with pytest.raises(TelegramRateLimitError) as caught:
        account._request("sendMessage", json={"chat_id": 123, "text": "hello"})

    assert caught.value.error_code == 429
    assert caught.value.retry_after == expected_retry_after
    assert client.calls == [
        (
            "https://api.telegram.org/bot123:test/sendMessage",
            {"json": {"chat_id": 123, "text": "hello"}},
        )
    ]
    assert response.json_calls == 1
    sleep.assert_not_called()


class _RateLimitedAccount:
    alias = "bot"

    def __init__(self, retry_after: int | None) -> None:
        self.retry_after = retry_after
        self.calls = 0

    def send_message(self, *_args: object, **_kwargs: object) -> dict:
        self.calls += 1
        raise TelegramRateLimitError(self.retry_after)


class _Service:
    def __init__(self, retry_after: int | None) -> None:
        self.default_account = _RateLimitedAccount(retry_after)

    def get_account(self, alias: str) -> _RateLimitedAccount:
        assert alias == "bot"
        return self.default_account


@pytest.mark.parametrize("retry_after", [41, None])
def test_manager_serializes_rate_limit_without_persisting_a_send(
    tmp_path: Path,
    retry_after: int | None,
) -> None:
    service = _Service(retry_after)
    manager = TelegramManager(
        service,
        working_dir=tmp_path,
        on_inbound=lambda _: None,
        notification_store=notification_store_for(tmp_path),
    )

    result = manager.handle({
        "action": "send",
        "account": "bot",
        "chat_id": 123,
        "text": "hello",
    })

    expected = {
        "status": "error",
        "error": "Telegram API rate limited",
        "error_code": 429,
        "retryable": False,
        "guidance": "Do not retry this Telegram action automatically.",
    }
    if retry_after is not None:
        expected.update({
            "error": f"Telegram API rate limited; retry after {retry_after} seconds",
            "retry_after": retry_after,
            "guidance": (
                "Do not retry this Telegram action for at least "
                f"{retry_after} seconds."
            ),
        })

    assert result == expected
    assert service.default_account.calls == 1
    assert not (tmp_path / "telegram" / "bot" / "sent").exists()
