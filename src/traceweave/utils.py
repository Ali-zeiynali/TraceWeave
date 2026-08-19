from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "ref", "ref_src"}
_WORD_RE = re.compile(r"[\w\-]{2,}", re.UNICODE)


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower().strip(".")
    if not scheme or not host:
        return url.strip()
    port = parts.port
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host if port is None or default_port else f"{host}:{port}"
    if parts.username or parts.password:
        netloc = parts.netloc.lower()
    clean_q = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        low = key.lower()
        if low.startswith("utm_") or low in _TRACKING_KEYS:
            continue
        clean_q.append((key, value))
    query = urlencode(sorted(clean_q))
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, query, ""))


def is_public_ip(value: str) -> bool:
    return bool(ipaddress.ip_address(value).is_global)


def words(text: str) -> set[str]:
    return {m.group(0).casefold() for m in _WORD_RE.finditer(text)}


def lexical_overlap(a: str, b: str) -> float:
    left, right = words(a), words(b)
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, len(left))


def simhash64(text: str) -> str:
    tokens = list(words(text))
    if not tokens:
        return ""
    vector = [0] * 64
    for token in tokens[:50_000]:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        for bit in range(64):
            vector[bit] += 1 if value & (1 << bit) else -1
    out = 0
    for bit, score in enumerate(vector):
        if score >= 0:
            out |= 1 << bit
    return f"{out:016x}"


def extract_first_json_object(text: str) -> dict:
    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start < 0:
        raise ValueError("No JSON object found in model response")
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        ch = text[index]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                value = json.loads(text[start:index + 1])
                if not isinstance(value, dict):
                    raise ValueError("JSON response is not an object")
                return value
    raise ValueError("Unterminated JSON object in model response")
