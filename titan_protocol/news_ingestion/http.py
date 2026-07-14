"""Stdlib-only HTTP transport shared by both provider adapters (mirrors
`titan_protocol.reliability.resource_monitor`'s injected-sampler pattern --
a small real default is provided; tests inject their own `HttpGet`
callable so no test ever performs a real network call). Never logs
headers or query parameters that could carry an API key (CLAUDE.md
security model / ADR-033 SS6) -- only the URL host/path is logged, and
only by the caller, never here."""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, Optional


@dataclass(frozen=True)
class HttpResponse:
    status: int
    content_type: Optional[str]
    body: bytes


HttpGet = Callable[[str, float, Dict[str, str]], HttpResponse]


def default_http_get(url: str, timeout_seconds: float, headers: Dict[str, str]) -> HttpResponse:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return HttpResponse(
                status=response.status,
                content_type=response.headers.get("Content-Type"),
                body=response.read(),
            )
    except urllib.error.HTTPError as exc:
        return HttpResponse(status=exc.code, content_type=exc.headers.get("Content-Type") if exc.headers else None, body=exc.read())


__all__ = ["HttpResponse", "HttpGet", "default_http_get"]
