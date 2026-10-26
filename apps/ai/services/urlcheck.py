"""Where the server may be pointed. A DM types the endpoint, so unless an administrator saved it
the host must resolve to public addresses only - the app must not be turned into a way to reach
its own network (the database, other containers, cloud metadata)."""

import ipaddress
import socket
from urllib.parse import urlparse


def is_public(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%")[0])
        if not address.is_global:
            return False
    return bool(infos)
