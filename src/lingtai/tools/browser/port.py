"""Technology-neutral outbound boundary for the static browser use case.

The browser Core owns this Port.  Implementations may resolve names and issue
one GET-like request, but they must not follow redirects, attach credentials,
or resolve a hostname again after Core has supplied a vetted target.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    """A DNS result that Core has checked before a socket is opened."""

    hostname: str
    port: int
    scheme: str
    ip_addresses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TransportResponse:
    """One bounded HTTP response; redirect following belongs to Core."""

    status: int
    headers: Mapping[str, str]
    body: bytes
    truncated: bool
    url: str


class BrowserPort(Protocol):
    """Outbound browser boundary used by :class:`BrowserEngine`.

    ``resolve`` returns every address answer for a hostname and accepts the
    caller's remaining end-to-end deadline.  Core rejects the entire answer
    set if any address is unsafe.  ``request`` receives that exact vetted set
    and the Adapter must connect to one of those addresses without a second
    DNS lookup.  Calls are stateless one-shot GETs with a finite timeout in
    seconds and a hard byte limit; cookies, authorization, uploads and
    persistent connections are outside this contract.
    """

    def resolve(self, hostname: str, *, timeout_s: float) -> Sequence[str]:
        """Return every current address answer before ``timeout_s`` expires."""

    def request(
        self,
        url: str,
        *,
        resolved: ResolvedTarget,
        max_bytes: int,
        timeout_s: float,
    ) -> TransportResponse:
        """Issue exactly one static GET against the supplied vetted target."""


class TransportError(Exception):
    """Bounded Adapter failure translated by Core into a typed tool failure."""

    def __init__(self, stage: str, error_code: str, *, retryable: bool = False) -> None:
        super().__init__(error_code)
        self.stage = stage
        self.error_code = error_code
        self.message = error_code
        self.retryable = retryable
