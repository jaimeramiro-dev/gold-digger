"""Gold Digger — shared HTTP, cache and GitHub helpers (stdlib only).

Every live source goes through here so timeouts, caching and the GitHub token
behave the same in scout.py (radar) and catalog.py (portfolio search).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

USER_AGENT = "gold-digger/2.0 (https://github.com/jaimeramiro-dev/gold-digger)"
DEFAULT_TIMEOUT = 8  # seconds
CACHE_DIR = Path(os.path.expanduser("~/.claude/gold-digger/cache"))

_SSL_CTX = ssl.create_default_context()


def warn(msg: str, tag: str = "gold-digger") -> None:
    print(f"[{tag}] WARNING: {msg}", file=sys.stderr)


def fetch_bytes(url: str, headers: dict | None = None, timeout: float = DEFAULT_TIMEOUT) -> bytes:
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
        return resp.read()


def fetch_json(url: str, headers: dict | None = None, timeout: float = DEFAULT_TIMEOUT) -> Any:
    return json.loads(fetch_bytes(url, headers, timeout))


def qs(params: dict) -> str:
    return urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})


# ---------------------------------------------------------------------------
# Cache — keyed by an arbitrary string, TTL in seconds
# ---------------------------------------------------------------------------

def _cache_path(key: str) -> Path:
    return CACHE_DIR / (hashlib.md5(key.encode()).hexdigest() + ".json")


def cache_get(key: str, ttl: int) -> Any | None:
    path = _cache_path(key)
    try:
        if time.time() - path.stat().st_mtime < ttl:
            return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        pass
    return None


def cache_put(key: str, data: Any) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(key).write_text(json.dumps(data))
    except OSError:
        pass


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

_TOKEN: str | None | bool = False  # False = not resolved yet


def github_token(cli_token: str | None = None) -> str | None:
    """CLI arg → GITHUB_TOKEN/GH_TOKEN → `gh auth token`. Resolved once per process."""
    global _TOKEN
    if cli_token:
        return cli_token
    if _TOKEN is not False:
        return _TOKEN  # type: ignore[return-value]
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token and shutil.which("gh"):
        try:
            out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=3)
            token = out.stdout.strip() or None
        except (subprocess.TimeoutExpired, OSError):
            token = None
    _TOKEN = token
    return token


def github_headers(token: str | None = None) -> dict:
    hdrs = {"Accept": "application/vnd.github+json"}
    tok = token or github_token()
    if tok:
        hdrs["Authorization"] = f"Bearer {tok}"
    return hdrs


def github_repo(full_name: str, ttl: int = 6 * 3600) -> dict | None:
    """Liveness + adoption facts for one repo. None if unreachable."""
    key = f"gh_repo:{full_name.lower()}"
    cached = cache_get(key, ttl)
    if cached is not None:
        return cached
    try:
        r = fetch_json(f"https://api.github.com/repos/{full_name}", github_headers())
    except Exception as e:
        warn(f"GitHub repo {full_name}: {e}")
        return None
    info = {
        "full_name": r.get("full_name"),
        "url": r.get("html_url"),
        "description": r.get("description") or "",
        "stars": r.get("stargazers_count"),
        "forks_count": r.get("forks_count"),
        "is_fork": r.get("fork"),
        "archived": r.get("archived"),
        "created_at": r.get("created_at"),
        "pushed_at": r.get("pushed_at"),
        "topics": r.get("topics", []),
        "license": (r.get("license") or {}).get("spdx_id"),
    }
    cache_put(key, info)
    return info
