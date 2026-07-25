"""Public-HTTP URL and SSRF policy owned by browser Core."""
from __future__ import annotations

import ipaddress
import posixpath
import re
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from .port import ResolvedTarget, TransportError

ALLOWED_SCHEMES = frozenset({"http", "https"})
_CLOUD_METADATA = ipaddress.ip_address("169.254.169.254")
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_SIX_TO_FOUR_RELAY = ipaddress.ip_network("192.88.99.0/24")
_LOCAL_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"})
_URL_HEAD = re.compile(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*):\/\/(?P<authority>[^/?#]*)(?P<tail>.*)$")


class PolicyViolation(Exception):
    """A URL or DNS answer failed the public-only policy."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.message = error_code


@dataclass(frozen=True, slots=True)
class ParsedURL:
    original: str
    scheme: str
    hostname: str
    port: int
    path: str = "/"
    query: str = ""
    explicit_port: bool = False


Resolver = Callable[[str], Sequence[str]]


def _parse(url: object) -> ParsedURL:
    if not isinstance(url, str) or not url or len(url) > 8192 or any(ord(c) < 32 or c.isspace() for c in url):
        raise PolicyViolation("MALFORMED_URL")
    match = _URL_HEAD.match(url)
    if match is None:
        raise PolicyViolation("MALFORMED_URL")
    scheme = match.group("scheme").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise PolicyViolation("SCHEME_NOT_ALLOWED")
    authority = match.group("authority")
    if "@" in authority:
        raise PolicyViolation("URL_USERINFO_FORBIDDEN")
    if not authority:
        raise PolicyViolation("NO_HOSTNAME")
    if authority.startswith("["):
        end = authority.find("]")
        if end < 0:
            raise PolicyViolation("MALFORMED_URL")
        hostname = authority[1:end]
        suffix = authority[end + 1 :]
        if suffix and not suffix.startswith(":"):
            raise PolicyViolation("MALFORMED_URL")
        port_text = suffix[1:] if suffix else ""
    else:
        if authority.count(":") > 1:
            raise PolicyViolation("MALFORMED_URL")
        if ":" in authority:
            hostname, port_text = authority.rsplit(":", 1)
        else:
            hostname, port_text = authority, ""
    hostname = hostname.rstrip(".").lower()
    if not hostname:
        raise PolicyViolation("NO_HOSTNAME")
    explicit_port = bool(port_text)
    if ":" in authority and not port_text:
        raise PolicyViolation("MALFORMED_URL")
    if port_text and (not port_text.isdigit() or len(port_text) > 5):
        raise PolicyViolation("MALFORMED_URL")
    port = int(port_text) if port_text else (443 if scheme == "https" else 80)
    if not 1 <= port <= 65535:
        raise PolicyViolation("MALFORMED_URL")
    tail = match.group("tail")
    before_fragment = tail.split("#", 1)[0]
    if "?" in before_fragment:
        path, query = before_fragment.split("?", 1)
    else:
        path, query = before_fragment, ""
    path = path or "/"
    if not path.startswith("/"):
        raise PolicyViolation("MALFORMED_URL")
    host_for_url = f"[{hostname}]" if ":" in hostname else hostname
    port_suffix = f":{port}" if explicit_port else ""
    original = f"{scheme}://{host_for_url}{port_suffix}{path}"
    if query:
        original += "?" + query
    return ParsedURL(original, scheme, hostname, port, path, query, explicit_port)


def check_scheme(url: str) -> None:
    """Validate URL syntax and scheme without resolving its hostname."""
    _parse(url)


def is_unsafe_ip(value: object) -> Optional[str]:
    """Return the stable policy code for an unsafe address, or ``None``."""
    if not isinstance(value, str):
        return "UNPARSEABLE_IP"
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return "UNPARSEABLE_IP"
    if ip == _CLOUD_METADATA:
        return "CLOUD_METADATA_BLOCKED"
    if ip.is_loopback:
        return "LOOPBACK_BLOCKED"
    if ip.is_unspecified:
        return "UNSPECIFIED_ADDRESS_BLOCKED"
    if ip.is_link_local:
        return "LINK_LOCAL_BLOCKED"
    if ip.is_multicast:
        return "MULTICAST_BLOCKED"
    if isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT:
        return "CGNAT_ADDRESS_BLOCKED"
    if isinstance(ip, ipaddress.IPv4Address) and ip in _SIX_TO_FOUR_RELAY:
        return "SIX_TO_FOUR_RELAY_BLOCKED"
    if ip.is_private:
        return "PRIVATE_ADDRESS_BLOCKED"
    if ip.is_reserved:
        return "RESERVED_ADDRESS_BLOCKED"
    return None


def resolve_and_check(url: str, resolver: Resolver | None = None) -> ResolvedTarget:
    """Parse, resolve, and validate one target before every Port request."""
    parsed = _parse(url)
    if parsed.hostname in _LOCAL_NAMES:
        raise PolicyViolation("LOOPBACK_BLOCKED")
    try:
        literal = ipaddress.ip_address(parsed.hostname.strip("[]"))
    except ValueError:
        literal = None
    if literal is None and re.fullmatch(r"[0-9.]+", parsed.hostname):
        raise PolicyViolation("MALFORMED_URL")
    if literal is not None:
        detail = is_unsafe_ip(str(literal))
        if detail:
            raise PolicyViolation(detail)
        return ResolvedTarget(parsed.hostname, parsed.port, parsed.scheme, (str(literal),))
    try:
        answers = tuple(str(item) for item in resolver(parsed.hostname))  # type: ignore[misc]
    except TransportError:
        raise
    except PolicyViolation:
        raise
    except Exception:
        raise PolicyViolation("DNS_RESOLUTION_FAILED") from None
    if not answers:
        raise PolicyViolation("DNS_RESOLUTION_FAILED")
    for answer in answers:
        detail = is_unsafe_ip(answer)
        if detail:
            raise PolicyViolation(detail)
    return ResolvedTarget(parsed.hostname, parsed.port, parsed.scheme, answers)


def _compose(parsed: ParsedURL, path: str, query: str = "") -> str:
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    port_suffix = f":{parsed.port}" if parsed.explicit_port else ""
    result = f"{parsed.scheme}://{host}{port_suffix}{path or '/'}"
    return result + (("?" + query) if query else "")


def resolved_url(url: str, location: str) -> str:
    """Resolve one redirect/link location without trusting it."""
    if not isinstance(location, str) or not location or len(location) > 8192:
        raise PolicyViolation("MALFORMED_REDIRECT")
    base = _parse(url)
    candidate = location.split("#", 1)[0]
    if not candidate:
        candidate = base.original
    else:
        scheme_match = re.match(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*):", candidate)
        if scheme_match:
            scheme = scheme_match.group("scheme").lower()
            if scheme not in ALLOWED_SCHEMES:
                raise PolicyViolation("SCHEME_NOT_ALLOWED")
            candidate = scheme + candidate[len(scheme_match.group("scheme")) :]
            # An absolute HTTP(S) location is parsed and policy-checked below.
            pass
        elif candidate.startswith("//"):
            candidate = base.scheme + ":" + candidate
        elif candidate.startswith("/"):
            path, _, query = candidate.partition("?")
            candidate = _compose(base, path, query)
        elif candidate.startswith("?"):
            candidate = _compose(base, base.path, candidate[1:])
        else:
            relative_path, separator, query = candidate.partition("?")
            directory = base.path.rsplit("/", 1)[0] + "/"
            joined = posixpath.normpath(directory + relative_path)
            if not joined.startswith("/"):
                joined = "/" + joined
            candidate = _compose(base, joined, query if separator else "")
    return _parse(candidate).original


def same_target(candidate: str, requested_url: str, final_url: str) -> bool:
    """Return whether a caller-named target is bound to this snapshot."""
    return candidate in {requested_url, final_url}
