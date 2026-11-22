"""Fetch a ticket export from an API. Returns CSV bytes with the same columns as the export, ready for state.prepare.

The response may be CSV, a JSON list of tickets, or a JSON object holding that list under tickets, data, results, items or
records (nested fields are flattened with dots). The token is sent in the header you name and is never saved by the app.
Set RIDEOPS_API_ALLOWED_HOSTS (comma separated) to limit which hosts the server may call.
"""
import difflib
import io
import ipaddress
import json
import os
import re
import socket
import urllib.request
from urllib.parse import urlparse

import pandas as pd

MAX_BYTES = 50_000_000
LIST_KEYS = ("tickets", "data", "results", "items", "records")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect could send the server to a host the checks below never saw."""

    def redirect_request(self, *a, **kw):
        return None


def _check_host(host: str) -> None:
    """Refuse addresses on a private network (loopback, link-local such as cloud metadata, internal ranges) unless the
    operator allows them with RIDEOPS_API_ALLOW_PRIVATE=1. Limit: the name is resolved again when the request is made."""
    if os.environ.get("RIDEOPS_API_ALLOW_PRIVATE", "").strip().lower() in ("1", "true", "yes"):
        return
    for info in socket.getaddrinfo(host, None):
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ValueError("That address is on a private network. The server may only call public addresses "
                             "(the operator can allow others with RIDEOPS_API_ALLOW_PRIVATE=1).")


def check_url(url: str) -> str:
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("The address must start with http:// or https://")
    allowed = [h.strip().lower() for h in os.environ.get("RIDEOPS_API_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if allowed and u.hostname.lower() not in allowed:
        raise ValueError(f"{u.hostname} is not in the list of allowed hosts")
    _check_host(u.hostname)
    return url.strip()


def to_csv(body: bytes, content_type: str = "") -> bytes:
    text = body.decode("utf-8-sig")
    if "json" in content_type.lower() or text.lstrip()[:1] in ("[", "{"):
        data = json.loads(text)
        if isinstance(data, dict):
            data = next((data[k] for k in LIST_KEYS if isinstance(data.get(k), list)), None)
            if data is None:
                raise ValueError("The JSON has no list of tickets (looked for " + ", ".join(LIST_KEYS) + ")")
        if not isinstance(data, list) or not data:
            raise ValueError("The API returned no tickets")
        return pd.json_normalize(data).to_csv(index=False).encode()
    return body


def _get(url: str, header: str, token: str, timeout: int) -> tuple:
    req = urllib.request.Request(check_url(url), headers={"Accept": "application/json, text/csv"})
    token = (token or "").strip()
    if token:
        header = (header or "Authorization").strip()
        bearer = header.lower() == "authorization" and not token.lower().startswith(("bearer ", "basic "))
        req.add_header(header, f"Bearer {token}" if bearer else token)
    with urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout) as r:  # scheme and host are checked above
        body = r.read(MAX_BYTES + 1)
        kind = r.headers.get("Content-Type", "")
    if len(body) > MAX_BYTES:
        raise ValueError("The response is larger than the limit")
    return body, kind


def fetch(url: str, header: str = "Authorization", token: str = "", timeout: int = 30) -> bytes:
    """The response as CSV bytes, with no renaming. Use fetch_frame when the field names may differ."""
    return to_csv(*_get(url, header, token, timeout))


def fetch_frame(url: str, header: str = "Authorization", token: str = "", timeout: int = 30) -> pd.DataFrame:
    """The response as a table of text, before any field mapping."""
    return pd.read_csv(io.BytesIO(to_csv(*_get(url, header, token, timeout))), dtype=str, keep_default_na=False)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def missing(df: pd.DataFrame, required: list) -> list:
    return [c for c in required if c not in df.columns]


def suggest(columns: list, required: list) -> dict:
    """For each required field not present, the source column whose name is closest (or None). A person confirms it."""
    by_norm = {_norm(c): c for c in columns}
    out = {}
    for req in required:
        if req in columns:
            continue
        hit = by_norm.get(_norm(req)) or next(iter(difflib.get_close_matches(_norm(req), list(by_norm), n=1, cutoff=0.75)), None)
        out[req] = by_norm.get(hit) if hit and hit not in columns else hit
    return out


def apply_mapping(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    """Add each required field as a copy of the source column it is mapped to (existing fields are left alone)."""
    out = df.copy()
    for req, src in (mapping or {}).items():
        if req not in out and src in out:
            out[req] = out[src]
    return out


def to_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()
