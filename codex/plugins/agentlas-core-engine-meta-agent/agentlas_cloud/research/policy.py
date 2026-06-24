"""Safety policy for research adapters."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


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

    try:
        parsed = urlsplit(url)
    except Exception as exc:
        return False, f"parse_error:{type(exc).__name__}"
    if parsed.scheme not in ALLOWED_SCHEMES:
        return False, f"scheme:{parsed.scheme or 'none'}"
    host = parsed.hostname
    if not host:
        return False, "no_host"
    if allow_private:
        return True, "allow_private"

    try:
        ipaddress.ip_address(host)
        return (False, f"ip_blocked:{host}") if _ip_blocked(host) else (True, "public_ip")
    except ValueError:
        pass

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except Exception:
        return True, "resolve_failed_allow"
    for info in infos:
        ip = str(info[4][0])
        if _ip_blocked(ip):
            return False, f"resolves_internal:{host}->{ip}"
    return True, "public"


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
