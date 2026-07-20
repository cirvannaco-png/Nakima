"""Shared SSRF guard for anything that makes a real outbound request to a
caller-supplied URL (security/dast.py, security/pentest_simulator.py).
Extracted to one place deliberately — this check is safety-critical, and
having it exist in two copies would risk them drifting apart silently
(one gets updated, the other doesn't) in a way that's easy to miss in
review since both call sites "look" protected.
"""

import ipaddress
import socket


def unsafe_target_reason(hostname: str | None) -> str | None:
    """Returns None if hostname resolves to a public, routable address —
    i.e. it's safe to make a real request to. Returns a human-readable
    reason string if it should be refused.
    """
    if not hostname:
        return "no hostname in the URL"
    try:
        resolved = {info[4][0] for info in socket.getaddrinfo(hostname, None)}
    except socket.gaierror as e:
        return f"hostname didn't resolve ({e})"

    for ip_str in resolved:
        ip = ipaddress.ip_address(ip_str)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return f"resolves to {ip_str}, a private/loopback/link-local/reserved address"
    return None
