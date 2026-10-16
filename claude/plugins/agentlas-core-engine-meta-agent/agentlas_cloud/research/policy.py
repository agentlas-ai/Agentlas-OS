"""Safety policy for research adapters."""

from __future__ import annotations

import http.client
import ipaddress
import socket
from urllib.parse import urlsplit
from urllib.request import HTTPHandler, HTTPSHandler, OpenerDirector, ProxyHandler, build_opener, getproxies, proxy_bypass


ALLOWED_SCHEMES = {"http", "https"}
DEFAULT_MAX_REDIRECTS = 8
DEFAULT_MAX_BYTES = 1_000_000
WEIGHT_RANKS = {
    "light": 10,
    "external_light": 20,
    "adaptive_medium": 30,
    "credentialed_medium": 40,
    "browser_heavy": 50,
}


def _ip_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def classify_url(url: str, *, allow_private: bool = False) -> tuple[bool, str]:
    """Return (safe, reason) for a URL before an adapter may fetch it."""

    safe, reason, _addresses = resolve_validated(url, allow_private=allow_private)
    return safe, reason


def resolve_validated(url: str, *, allow_private: bool = False) -> tuple[bool, str, list[str]]:
    """Return (safe, reason, addresses): the addresses are the only ones a fetch may connect to.

    A failed lookup is blocked, not allowed: the attacker controls the
    authoritative DNS of their own domain and can fail the check on purpose.
    """

    try:
        parsed = urlsplit(url)
    except Exception as exc:
        return False, f"parse_error:{type(exc).__name__}", []
    if parsed.scheme not in ALLOWED_SCHEMES:
        return False, f"scheme:{parsed.scheme or 'none'}", []
    host = parsed.hostname
    if not host:
        return False, "no_host", []
    if allow_private:
        return True, "allow_private", []

    try:
        ipaddress.ip_address(host)
        return (False, f"ip_blocked:{host}", []) if _ip_blocked(host) else (True, "public_ip", [host])
    except ValueError:
        pass

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except Exception:
        return False, "resolve_failed", []
    addresses: list[str] = []
    for info in infos:
        ip = str(info[4][0])
        if _ip_blocked(ip):
            return False, f"resolves_internal:{host}->{ip}", []
        if ip not in addresses:
            addresses.append(ip)
    if not addresses:
        return False, "resolve_failed", []
    return True, "public", addresses


def _pinned_connection(base: type[http.client.HTTPConnection]) -> type[http.client.HTTPConnection]:
    class Pinned(base):  # type: ignore[misc, valid-type]
        """Connect to validated addresses only. `self.host` stays the original
        name, so the Host header, TLS SNI and certificate check are unchanged."""

        def __init__(self, host: str, *args: object, pinned_addresses: tuple[str, ...] = (), **kwargs: object) -> None:
            super().__init__(host, *args, **kwargs)
            self._pinned_addresses = tuple(pinned_addresses)
            self._create_connection = self._connect_pinned

        def _connect_pinned(self, address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
            last_error: OSError = OSError("no validated address")
            for ip in self._pinned_addresses:
                try:
                    return socket.create_connection((ip, address[1]), timeout, source_address)
                except OSError as exc:
                    last_error = exc
            raise last_error

    return Pinned


_PinnedHTTPConnection = _pinned_connection(http.client.HTTPConnection)
_PinnedHTTPSConnection = _pinned_connection(http.client.HTTPSConnection)


class _PinnedHTTPHandler(HTTPHandler):
    def __init__(self, addresses: list[str]) -> None:
        super().__init__()
        self._addresses = tuple(addresses)

    def http_open(self, req):
        return self.do_open(_PinnedHTTPConnection, req, pinned_addresses=self._addresses)


class _PinnedHTTPSHandler(HTTPSHandler):
    def __init__(self, addresses: list[str]) -> None:
        super().__init__()
        self._addresses = tuple(addresses)

    def https_open(self, req):
        return self.do_open(_PinnedHTTPSConnection, req, context=self._context, pinned_addresses=self._addresses)


def _pinned_opener(addresses: list[str], *handlers: object) -> OpenerDirector:
    # ProxyHandler({}): no ambient proxy on this path, the connection goes to `addresses`.
    return build_opener(ProxyHandler({}), _PinnedHTTPHandler(addresses), _PinnedHTTPSHandler(addresses), *handlers)


def pinned_opener(url: str, *handlers: object) -> tuple[OpenerDirector | None, str]:
    """Validate `url` and return an opener that can only connect where the check looked.

    Checking and then letting urllib resolve again let a TTL-0 rebinding answer
    (public for the check, 127.0.0.1 for the fetch) reach loopback services.
    Call this for every redirect hop. Returns (None, reason) when blocked.
    When a proxy applies to the URL, the proxy resolves the name itself and the
    existing proxy path is kept (the check above still ran, fail-closed).
    """

    safe, reason, addresses = resolve_validated(url)
    if not safe:
        return None, reason
    parsed = urlsplit(url)
    if not addresses or (getproxies().get(parsed.scheme) and not proxy_bypass(parsed.hostname or "")):
        return build_opener(*handlers), reason
    return _pinned_opener(addresses, *handlers), reason


def module_allowed(module_id: str, allowed: list[str], forbidden: list[str]) -> tuple[bool, str]:
    if module_id in forbidden:
        return False, "forbidden_module"
    if allowed and module_id not in allowed:
        return False, "not_in_allowed_modules"
    return True, "allowed"


def weight_allowed(module_weight: str, max_weight: str) -> tuple[bool, str]:
    if not max_weight or max_weight == "policy_selected":
        return True, "allowed"
    max_rank = WEIGHT_RANKS.get(max_weight)
    module_rank = WEIGHT_RANKS.get(module_weight or "light")
    if max_rank is None or module_rank is None:
        return True, "unknown_weight_allowed"
    if module_rank > max_rank:
        return False, f"weight_exceeds_max:max={max_weight}:module={module_weight}"
    return True, "allowed"
