"""SSRF guard for Vara outbound fetches (Defect A, consolidated redeploy).

Every server-side fetch of a URL that is not a compile-time constant must go
through this module — above all the RSS harvest path, which accepts
caller-supplied feeds via ``VaraConfig.extra_rss_feeds`` /
``extra_substacks``.

Guard properties (pattern from CVE-2026-14540 / datagouv PR #126):

1. Destination IPs are resolved and rejected when loopback / private /
   link-local (incl. 169.254.169.254) / reserved / multicast / unspecified,
   unless the *host* is explicitly allowlisted for private access
   (``VARA_FEED_ALLOW_PRIVATE_HOSTS``).
2. The destination IP is validated **at connect time**: the connection is
   opened to the already-validated IP (DNS pinning), so a DNS answer that
   changes between check and connect (rebinding) cannot redirect the fetch.
   TLS still verifies against the original hostname (SNI + cert hostname).
3. Every redirect hop is re-resolved and re-validated; redirects are capped.
4. Caller-supplied feeds can be restricted to an explicit feed-host
   allowlist (``VARA_FEED_HOST_ALLOWLIST``) — legitimate feeds are
   enumerable, so when the operator configures one it is enforced.
5. Upstream error bodies are never returned to callers or written to logs:
   failures surface as a status/reason only.

Stdlib-only. This is the vendor copy of ``src/ssrf_guard.py`` — the vendor
package is imported as flat top-level modules, so the guard travels with it.
Keep the two copies in step.
"""

from __future__ import annotations

import http.client
import ipaddress
import os
import socket
import ssl
from dataclasses import dataclass
from typing import Callable, Iterable, Optional
from urllib.parse import urljoin, urlparse

MAX_REDIRECTS = 5
MAX_BODY_BYTES = 10_000_000
_DEFAULT_UA = "VaraHarvester/1.0"


class SSRFError(ValueError):
    """A URL was rejected by the SSRF guard (fail closed)."""


class FetchError(RuntimeError):
    """A guarded fetch failed. Carries status/reason only — never a body."""


def _env_hosts(name: str) -> tuple[str, ...]:
    raw = os.environ.get(name) or ""
    return tuple(h.strip().lower() for h in raw.split(",") if h.strip())


def feed_host_allowlist() -> tuple[str, ...]:
    """Operator-configured allowlist for caller-supplied feed hosts."""
    return _env_hosts("VARA_FEED_HOST_ALLOWLIST")


def private_host_allowlist() -> tuple[str, ...]:
    """Hosts explicitly allowed to resolve to private/loopback addresses."""
    return _env_hosts("VARA_FEED_ALLOW_PRIVATE_HOSTS")


def _ip_is_forbidden(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return True  # unparseable resolver output is forbidden, fail closed
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


@dataclass
class ValidatedTarget:
    url: str
    scheme: str
    host: str
    port: int
    ips: list[str]


Resolver = Callable[[str, int], list[str]]


def _default_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    ips: list[str] = []
    for info in infos:
        ip = info[4][0]
        if ip not in ips:
            ips.append(ip)
    return ips


def resolve_and_validate(
    url: str,
    *,
    caller_supplied: bool = False,
    allowlist_hosts: Optional[Iterable[str]] = None,
    allow_private_hosts: Optional[Iterable[str]] = None,
    resolver: Optional[Resolver] = None,
) -> ValidatedTarget:
    """Resolve *url*'s host and reject forbidden destinations.

    Raises SSRFError on any rejection. Returns the validated IP list so the
    caller can pin the connection to a checked address.
    """
    if not isinstance(url, str) or not url.strip():
        raise SSRFError("empty URL")
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"scheme not allowed: {parsed.scheme or '(none)'}")
    if parsed.username or parsed.password:
        raise SSRFError("URLs with embedded credentials are not allowed")
    host = (parsed.hostname or "").lower()
    if not host:
        raise SSRFError("URL has no host")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    if allowlist_hosts is None:
        allowlist_hosts = feed_host_allowlist() if caller_supplied else ()
    allowlist = tuple(h.lower() for h in allowlist_hosts or ())
    if allowlist and host not in allowlist:
        raise SSRFError(f"host not in feed allowlist: {host}")

    if allow_private_hosts is None:
        allow_private_hosts = private_host_allowlist()
    private_ok = host in tuple(h.lower() for h in allow_private_hosts or ())

    resolve = resolver or _default_resolver
    try:
        ips = resolve(host, port)
    except SSRFError:
        raise
    except Exception as exc:  # DNS failure — reason only, no payload
        raise SSRFError(f"DNS resolution failed for {host}: {type(exc).__name__}") from None
    if not ips:
        raise SSRFError(f"DNS resolution returned no addresses for {host}")
    if not private_ok:
        for ip in ips:
            if _ip_is_forbidden(ip):
                raise SSRFError(
                    f"destination {host} resolves to a non-public address ({ip})"
                )
    return ValidatedTarget(url=url, scheme=parsed.scheme, host=host, port=port, ips=list(ips))


def validate_url(url: str, **kwargs) -> ValidatedTarget:
    """Validate only (no fetch). Used at config/tool intake, fail closed."""
    return resolve_and_validate(url, **kwargs)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTP connection opened to a pre-validated IP, Host header preserved."""

    def __init__(self, *args, pinned_ip: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:  # noqa: D102 — http.client hook
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        if self._tunnel_host:
            self._tunnel()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection to a pre-validated IP; TLS verifies the real host."""

    def __init__(self, *args, pinned_ip: str, sni_host: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._pinned_ip = pinned_ip
        self._sni_host = sni_host

    def connect(self) -> None:  # noqa: D102 — http.client hook
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        if self._tunnel_host:
            self._tunnel()
        context = self._context or ssl.create_default_context()
        self.sock = context.wrap_socket(self.sock, server_hostname=self._sni_host)


def _connect(target: ValidatedTarget, timeout: float):
    """Open a connection pinned to the first validated IP."""
    ip = target.ips[0]
    if target.scheme == "https":
        return _PinnedHTTPSConnection(
            target.host, target.port, timeout=timeout, pinned_ip=ip, sni_host=target.host
        )
    return _PinnedHTTPConnection(target.host, target.port, timeout=timeout, pinned_ip=ip)


def fetch_bytes(
    url: str,
    *,
    timeout: float = 10.0,
    max_redirects: int = MAX_REDIRECTS,
    max_bytes: int = MAX_BODY_BYTES,
    caller_supplied: bool = False,
    allowlist_hosts: Optional[Iterable[str]] = None,
    allow_private_hosts: Optional[Iterable[str]] = None,
    headers: Optional[dict[str, str]] = None,
    resolver: Optional[Resolver] = None,
    connect_factory: Optional[Callable[[ValidatedTarget, float], object]] = None,
) -> tuple[int, dict[str, str], bytes, str]:
    """Guarded GET. Returns (status, headers, body, final_url).

    The connection is pinned to an IP validated in this same call, and each
    redirect hop is resolved/validated again before it is followed.
    """
    current = url
    request_headers = {"User-Agent": _DEFAULT_UA, "Accept": "*/*"}
    if headers:
        request_headers.update(headers)

    for hop in range(max_redirects + 1):
        target = resolve_and_validate(
            current,
            caller_supplied=caller_supplied,
            allowlist_hosts=allowlist_hosts,
            allow_private_hosts=allow_private_hosts,
            resolver=resolver,
        )
        parsed = urlparse(current)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        factory = connect_factory or _connect
        conn = factory(target, timeout)
        try:
            conn.request("GET", path, headers=request_headers)  # type: ignore[attr-defined]
            response = conn.getresponse()  # type: ignore[attr-defined]
            status = int(response.status)
            resp_headers = {k.lower(): v for k, v in response.getheaders()}
            if status in (301, 302, 303, 307, 308):
                location = resp_headers.get("location")
                response.read()
                if not location:
                    raise FetchError(f"redirect without Location from {target.host}")
                if hop >= max_redirects:
                    raise FetchError(f"redirect cap ({max_redirects}) exceeded")
                current = urljoin(current, location)
                continue
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise FetchError(f"response from {target.host} exceeds {max_bytes} bytes")
            return status, resp_headers, body, current
        except (SSRFError, FetchError):
            raise
        except Exception as exc:
            # Reason class only — upstream bodies are never surfaced/logged.
            raise FetchError(f"fetch of {target.host} failed: {type(exc).__name__}") from None
        finally:
            try:
                conn.close()  # type: ignore[attr-defined]
            except Exception:
                pass
    raise FetchError(f"redirect cap ({max_redirects}) exceeded")


def fetch_text(url: str, **kwargs) -> str:
    """Guarded GET returning decoded text. Non-2xx raises FetchError."""
    status, _headers, body, _final = fetch_bytes(url, **kwargs)
    if status < 200 or status >= 300:
        raise FetchError(f"fetch returned status {status}")
    return body.decode("utf-8", errors="replace")
