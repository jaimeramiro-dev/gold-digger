#!/usr/bin/env python3
"""Gold Digger Scout — fetches candidates from structured sources.

Returns a JSON array to stdout. No judgment, no scoring — just gathering.
Each source has a 5-second timeout. Sources that fail are skipped silently
(warning to stderr). All fetches run in parallel via ThreadPoolExecutor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# Optional deps — graceful degradation
try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

try:
    import feedparser
except ImportError:
    feedparser = None  # type: ignore

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

USER_AGENT = "gold-digger/1.0 (https://github.com/jaimeramiro-dev/gold-digger)"
FETCH_TIMEOUT = 5  # seconds per source
MAX_WORKERS = 8
DEFAULT_MAX_RESULTS = 30
DEFAULT_MAX_AGE_DAYS = 7

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _make_request(url: str, headers: dict | None = None, timeout: int = FETCH_TIMEOUT) -> bytes:
    """Fetch a URL and return raw bytes. Raises on error."""
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    # Create SSL context that works broadly
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read()


def _fetch_json(url: str, headers: dict | None = None) -> Any:
    """Fetch JSON from a URL."""
    data = _make_request(url, headers)
    return json.loads(data)


def _warn(msg: str) -> None:
    print(f"[scout] WARNING: {msg}", file=sys.stderr)


def _fetch_readme_excerpt(full_name: str, token: str | None, max_chars: int = 500) -> str:
    """Fetch the first ~500 chars of a GitHub repo's README. Best-effort."""
    url = f"https://api.github.com/repos/{full_name}/readme"
    headers = {"Accept": "application/vnd.github.raw+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        raw = _make_request(url, headers, timeout=3)
        text = raw.decode("utf-8", errors="replace")[:max_chars]
        # Strip markdown formatting noise — keep just readable text
        import re
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)  # headings
        text = re.sub(r"[`*_~\[\]()]", "", text)  # inline formatting
        text = re.sub(r"\n{3,}", "\n\n", text)  # collapse blank lines
        return text.strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Candidate normalization
# ---------------------------------------------------------------------------

def _candidate(
    source: str,
    uid: str,
    title: str,
    url: str,
    description: str = "",
    created_at: str = "",
    stars: int | None = None,
    repo_age_days: int | None = None,
    language: str | None = None,
    topics: list[str] | None = None,
    points: int | None = None,
    pushed_at: str | None = None,
    archived: bool | None = None,
    forks_count: int | None = None,
) -> dict:
    """Build a normalized candidate dict."""
    return {
        "id": f"{source}:{uid}",
        "title": title,
        "url": url,
        "source": source,
        "description": description[:500] if description else "",
        "created_at": created_at,
        "metadata": {
            "stars": stars,
            "points": points,
            "repo_age_days": repo_age_days,
            "language": language,
            "topics": topics or [],
            "pushed_at": pushed_at,
            "archived": archived,
            "forks_count": forks_count,
        },
    }


# ---------------------------------------------------------------------------
# Source fetchers — each returns a list of candidate dicts
# ---------------------------------------------------------------------------

def fetch_mcp_registry(since_iso: str) -> list[dict]:
    """Official MCP Registry — no auth required."""
    url = f"https://registry.modelcontextprotocol.io/v0.1/servers?updated_since={since_iso}&limit=50"
    try:
        data = _fetch_json(url)
    except Exception as e:
        _warn(f"MCP Registry: {e}")
        return []

    results = []
    for entry in data.get("servers", []):
        srv = entry.get("server", {})
        name = srv.get("name", "")
        desc = srv.get("description", "")
        title = srv.get("title", name)
        repo = srv.get("repository", {})
        repo_url = repo.get("url", "") if isinstance(repo, dict) else ""
        results.append(_candidate(
            source="mcp-registry",
            uid=name,
            title=title,
            url=repo_url or f"https://registry.modelcontextprotocol.io/servers/{name}",
            description=desc,
        ))
    return results


def fetch_glama(since_iso: str) -> list[dict]:
    """Glama MCP registry — no auth required."""
    url = "https://glama.ai/api/mcp/v1/servers?limit=30"
    try:
        data = _fetch_json(url)
    except Exception as e:
        _warn(f"Glama: {e}")
        return []

    results = []
    for srv in data.get("servers", []):
        name = srv.get("name", "")
        desc = srv.get("description", "")
        slug = srv.get("slug", "")
        repo = srv.get("repository", {})
        repo_url = repo.get("url", "") if isinstance(repo, dict) else ""
        srv_url = srv.get("url", repo_url or f"https://glama.ai/mcp/servers/{slug}")
        results.append(_candidate(
            source="glama",
            uid=slug or name,
            title=name,
            url=srv_url,
            description=desc,
        ))
    return results


def fetch_github_search(query: str, token: str | None, since_date: str) -> list[dict]:
    """GitHub search API — optional token. Enriches top results with README excerpts."""
    q = urllib.parse.quote(f"{query} created:>{since_date}")
    url = f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page=15"
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        data = _fetch_json(url, headers)
    except Exception as e:
        _warn(f"GitHub search '{query}': {e}")
        return []

    results = []
    for repo in data.get("items", []):
        created = repo.get("created_at", "")
        age_days = None
        if created:
            try:
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - created_dt).days
            except ValueError:
                pass
        desc = repo.get("description", "") or ""
        full_name = repo.get("full_name", "")
        results.append(_candidate(
            source="github",
            uid=full_name,
            title=full_name,
            url=repo.get("html_url", ""),
            description=desc,
            created_at=created,
            stars=repo.get("stargazers_count"),
            repo_age_days=age_days,
            language=repo.get("language"),
            topics=repo.get("topics", []),
            pushed_at=repo.get("pushed_at"),
            archived=repo.get("archived"),
            forks_count=repo.get("forks_count"),
        ))

    # Enrich top results (by stars) with README excerpts — in parallel
    # Only for repos where description is short (<80 chars)
    enrichable = [
        (i, r) for i, r in enumerate(results)
        if len(r.get("description", "")) < 80
    ][:5]  # cap at 5 to avoid burning rate limit

    if enrichable:
        from concurrent.futures import ThreadPoolExecutor as _Pool
        with _Pool(max_workers=5) as pool:
            futures = {
                pool.submit(_fetch_readme_excerpt, r["title"], token): i
                for i, r in enrichable
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    excerpt = future.result()
                    if excerpt:
                        existing = results[idx].get("description", "")
                        results[idx]["description"] = (
                            f"{existing}\n---\n{excerpt}" if existing else excerpt
                        )
                except Exception:
                    pass

    return results


def fetch_hn(keywords: list[str], since_unix: int) -> list[dict]:
    """Hacker News via Algolia API — no auth."""
    query = " OR ".join(keywords[:5])  # cap query complexity
    q = urllib.parse.quote(query)
    url = (
        f"https://hn.algolia.com/api/v1/search_by_date"
        f"?query={q}&tags=story&numericFilters=created_at_i>{since_unix}"
        f"&hitsPerPage=20"
    )
    try:
        data = _fetch_json(url)
    except Exception as e:
        _warn(f"HN: {e}")
        return []

    results = []
    for hit in data.get("hits", []):
        results.append(_candidate(
            source="hn",
            uid=hit.get("objectID", ""),
            title=hit.get("title", ""),
            url=hit.get("url", f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"),
            description=hit.get("story_text", "") or "",
            created_at=hit.get("created_at", ""),
            points=hit.get("points"),
        ))
    return results


def fetch_reddit(subs: list[str]) -> list[dict]:
    """Reddit public JSON — no auth, 10 req/min."""
    results = []
    # Limit to 5 subs per run to stay under rate limit
    for sub in subs[:5]:
        url = f"https://www.reddit.com/r/{sub}/new.json?limit=10"
        try:
            data = _fetch_json(url)
        except Exception as e:
            _warn(f"Reddit r/{sub}: {e}")
            continue
        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            results.append(_candidate(
                source="reddit",
                uid=post.get("id", ""),
                title=post.get("title", ""),
                url=f"https://reddit.com{post.get('permalink', '')}",
                description=post.get("selftext", "")[:300],
                created_at=datetime.fromtimestamp(
                    post.get("created_utc", 0), tz=timezone.utc
                ).isoformat() if post.get("created_utc") else "",
                points=post.get("score"),
            ))
    return results


def fetch_ossinsight() -> list[dict]:
    """OSS Insight trending repos — no auth."""
    url = "https://api.ossinsight.io/v1/trends/repos/?period=past_week&language=All"
    try:
        data = _fetch_json(url)
    except Exception as e:
        _warn(f"OSS Insight: {e}")
        return []

    results = []
    for row in data.get("data", {}).get("rows", [])[:20]:
        results.append(_candidate(
            source="ossinsight",
            uid=str(row.get("repo_id", "")),
            title=row.get("repo_name", ""),
            url=f"https://github.com/{row.get('repo_name', '')}",
            description=row.get("description", "") or "",
            stars=int(row.get("stars", 0) or 0),
            language=row.get("primary_language"),
        ))
    return results


def fetch_github_releases(repo: str, token: str | None, since_iso: str) -> list[dict]:
    """GitHub releases for a specific repo."""
    url = f"https://api.github.com/repos/{repo}/releases?per_page=5"
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        data = _fetch_json(url, headers)
    except Exception as e:
        _warn(f"GitHub releases {repo}: {e}")
        return []

    results = []
    for rel in data:
        pub = rel.get("published_at", "")
        if pub and pub >= since_iso:
            results.append(_candidate(
                source="github-release",
                uid=f"{repo}:{rel.get('tag_name', '')}",
                title=f"{repo} {rel.get('tag_name', '')}",
                url=rel.get("html_url", ""),
                description=rel.get("body", "")[:500] if rel.get("body") else "",
                created_at=pub,
            ))
    return results


def fetch_rss(feed_url: str, source_name: str, since_iso: str) -> list[dict]:
    """Fetch an RSS/Atom feed. Requires feedparser."""
    if feedparser is None:
        _warn(f"RSS {source_name}: feedparser not installed, skipping")
        return []
    try:
        raw = _make_request(feed_url)
        feed = feedparser.parse(raw)
    except Exception as e:
        _warn(f"RSS {source_name}: {e}")
        return []

    results = []
    for entry in feed.entries[:15]:
        pub = ""
        if hasattr(entry, "published"):
            pub = entry.published
        elif hasattr(entry, "updated"):
            pub = entry.updated

        link = entry.get("link", "")
        title = entry.get("title", "")
        desc = entry.get("summary", "") or entry.get("description", "")

        uid = hashlib.md5(f"{source_name}:{link}".encode()).hexdigest()[:12]
        results.append(_candidate(
            source=f"rss:{source_name}",
            uid=uid,
            title=title,
            url=link,
            description=desc[:500],
            created_at=pub,
        ))
    return results


def fetch_page_titles(page_url: str, source_name: str) -> list[dict]:
    """Basic HTML page scrape — extract links and titles. Last resort."""
    import re
    try:
        raw = _make_request(page_url).decode("utf-8", errors="replace")
    except Exception as e:
        _warn(f"Page {source_name}: {e}")
        return []

    # Simple regex to find article-like links with titles
    # Matches <a href="...">title</a> patterns
    results = []
    pattern = re.compile(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]{10,200})</a>',
        re.IGNORECASE,
    )
    seen_urls = set()
    for match in pattern.finditer(raw):
        href, title = match.group(1), match.group(2).strip()
        # Resolve relative URLs
        if href.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(page_url)
            href = f"{parsed.scheme}://{parsed.netloc}{href}"
        # Skip nav/footer links, short titles, duplicates
        if len(title) < 15 or href in seen_urls:
            continue
        if any(skip in href.lower() for skip in ["#", "javascript:", "mailto:", "/tag/", "/category/"]):
            continue
        seen_urls.add(href)
        uid = hashlib.md5(f"{source_name}:{href}".encode()).hexdigest()[:12]
        results.append(_candidate(
            source=f"page:{source_name}",
            uid=uid,
            title=title,
            url=href,
        ))
        if len(results) >= 10:
            break
    return results


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

CACHE_DIR = os.path.expanduser("~/.claude/gold-digger/cache")
CACHE_TTL = 6 * 3600  # 6 hours


def _cache_key(name: str) -> Path:
    return Path(CACHE_DIR) / f"{name}.json"


def _read_cache(name: str) -> list[dict] | None:
    path = _cache_key(name)
    if not path.exists():
        return None
    try:
        mtime = path.stat().st_mtime
        if time.time() - mtime > CACHE_TTL:
            return None
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def _write_cache(name: str, data: list[dict]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    try:
        with open(_cache_key(name), "w") as f:
            json.dump(data, f)
    except IOError:
        pass


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def load_yaml_file(path: str) -> dict:
    """Load a YAML file. Falls back to empty dict."""
    if yaml is None:
        _warn("PyYAML not installed — cannot read YAML files")
        return {}
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except (IOError, yaml.YAMLError) as e:
        _warn(f"Cannot read {path}: {e}")
        return {}


def get_github_token(cli_token: str | None) -> str | None:
    """Get GitHub token from CLI arg or environment."""
    return cli_token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def build_hn_keywords(profile: dict) -> list[str]:
    """Build HN search keywords from the user's profile.

    Priority order (fills up to 8 slots):
      1. Fixed ecosystem terms: MCP, claude, AI tool (3 slots, always present)
      2. Stack + searchable dimensions INTERLEAVED (up to 5 slots):
         alternates stack, dimension, stack, dimension... so both get
         representation even when one list is large. If one list runs out
         the other fills the remaining slots.
      3. Declared interests (whatever slots remain)
    """
    keywords = ["MCP", "claude", "AI tool"]
    remaining = 8 - len(keywords)  # 5 slots

    detected = profile.get("detected", {})
    stack_items = list(detected.get("stack", []))
    declared = profile.get("declared", {})
    dim_items = [
        dim.get("name", "")
        for dim in declared.get("dimensions", [])
        if isinstance(dim, dict) and dim.get("searchable")
    ]

    # Interleave stack and dimensions
    si, di = 0, 0
    interleaved: list[str] = []
    while si < len(stack_items) or di < len(dim_items):
        if si < len(stack_items):
            interleaved.append(stack_items[si])
            si += 1
        if di < len(dim_items):
            interleaved.append(dim_items[di])
            di += 1

    keywords.extend(interleaved[:remaining])

    # Interests fill whatever is left
    if len(keywords) < 8:
        for interest in declared.get("interests", []):
            keywords.append(interest)
            if len(keywords) >= 8:
                break

    return keywords[:8]


def get_relevant_subs(profile: dict, sources: dict) -> list[str]:
    """Pick Reddit subs relevant to the user's profile."""
    subs = []
    reddit_cfg = sources.get("ecosystem", {}).get("reddit", {})
    default_subs = reddit_cfg.get("default_subs", {})

    # Always include dev subs
    subs.extend(default_subs.get("dev", []))

    # Add domain-specific subs
    declared = profile.get("declared", {})
    domains = [d.lower() for d in declared.get("domains", [])]
    for domain in domains:
        for key, sub_list in default_subs.items():
            if key in domain or domain in key:
                subs.extend(sub_list)

    # Add subs matching searchable dimensions
    for dim in declared.get("dimensions", []):
        if isinstance(dim, dict) and dim.get("searchable"):
            dim_name = dim.get("name", "").lower()
            for key, sub_list in default_subs.items():
                if dim_name in key or key in dim_name:
                    subs.extend(sub_list)

    return list(dict.fromkeys(subs))[:8]  # dedupe, cap at 8


def get_layer2_channels(profile: dict, sources: dict) -> list[dict]:
    """Determine which Layer 2 channels to fetch based on the user's profile."""
    channels = []
    per_tool = sources.get("per_tool_channels", {})

    # Always include AI labs
    for lab in ["openai", "google_deepmind", "anthropic", "meta_ai", "deepseek"]:
        if lab in per_tool:
            for ch in per_tool[lab]:
                channels.append({"name": lab, **ch})

    # Add tool-specific channels based on detected stack
    detected = profile.get("detected", {})
    stack = [s.lower() for s in detected.get("stack", [])]
    for tool_key, ch_list in per_tool.items():
        if tool_key in stack:
            for ch in ch_list:
                channels.append({"name": tool_key, **ch})

    return channels


# ---------------------------------------------------------------------------
# Warez / piracy pre-filter
# ---------------------------------------------------------------------------

# Patterns that are almost always piracy — match case-insensitively against
# the combined title + description text. Compound patterns reduce false
# positives: "crack" alone could be legitimate ("crack detection"), but
# "crack download" or "cracked version" is not.
_WAREZ_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\bkeygen\b",
        r"\bpatch\s+activator\b",
        r"\bpre[- ]?activated\b",
        r"\bnulled\b",
        r"\bwarez\b",
        r"\blicense\s+key\s+generator\b",
        r"\bserial\s+key\b.*\b(?:download|free|full)\b",
        r"\bcrack(?:ed)?\s+(?:download|version|installer|setup|latest)\b",
        r"\bfull\s+version\s+crack(?:ed)?\b",
        r"\b(?:free|full)\s+download\b.*\bcrack\b",
        r"\bcrack\b.*\b(?:free|full)\s+download\b",
    ]
]


def _filter_warez(candidates: list[dict]) -> list[dict]:
    """Remove obvious piracy/warez candidates. Logs discards to stderr."""
    clean = []
    for c in candidates:
        text = (
            c.get("title", "") + " " + c.get("description", "")
        )
        matched = False
        for pattern in _WAREZ_PATTERNS:
            if pattern.search(text):
                _warn(f"Filtered warez: {c.get('title', '?')} (matched: {pattern.pattern})")
                matched = True
                break
        if not matched:
            clean.append(c)
    return clean


def run_scout(
    profile_path: str,
    sources_path: str,
    github_token: str | None = None,
    layer: str = "both",
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> list[dict]:
    """Run the full scout and return candidates."""
    profile = load_yaml_file(profile_path)
    sources = load_yaml_file(sources_path)
    token = get_github_token(github_token)

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=max_age_days)
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    since_date = since.strftime("%Y-%m-%d")
    since_unix = int(since.timestamp())

    all_candidates: list[dict] = []
    futures = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        # ----- Layer 1: Ecosystem-wide -----
        if layer in ("1", "both"):
            # MCP registries
            futures[pool.submit(fetch_mcp_registry, since_iso)] = "mcp_registry"
            futures[pool.submit(fetch_glama, since_iso)] = "glama"

            # GitHub searches
            gh_topics = sources.get("ecosystem", {}).get("github", {}).get("search_topics", [])
            for topic in gh_topics[:4]:  # cap to avoid rate limit
                cached = _read_cache(f"gh_{topic}")
                if cached is not None:
                    all_candidates.extend(cached)
                else:
                    futures[pool.submit(
                        fetch_github_search, f"topic:{topic}", token, since_date
                    )] = f"gh_{topic}"

            # Skills registries (via GitHub topic search)
            skills_topics = (
                sources.get("ecosystem", {})
                .get("skills_registries", [{}])[0]
                .get("topics", [])
            )
            for topic in skills_topics[:2]:
                cache_key = f"gh_skill_{topic}"
                cached = _read_cache(cache_key)
                if cached is not None:
                    all_candidates.extend(cached)
                else:
                    futures[pool.submit(
                        fetch_github_search, f"topic:{topic}", token, since_date
                    )] = cache_key

            # Dimension-based GitHub searches (up to 2 calls)
            # Combine searchable dimensions into batched queries so we don't
            # blow the rate limit. Group into max 2 queries of ~3 terms each.
            declared = profile.get("declared", {})
            dim_terms = [
                dim.get("name", "")
                for dim in declared.get("dimensions", [])
                if isinstance(dim, dict) and dim.get("searchable") and dim.get("name")
            ]
            if dim_terms:
                # Split into max 2 groups
                mid = (len(dim_terms) + 1) // 2
                dim_groups = [dim_terms[:mid], dim_terms[mid:]]
                for gi, group in enumerate(dim_groups):
                    if not group:
                        continue
                    # Free-text search: OR the terms together
                    query = " OR ".join(f'"{t}"' for t in group[:3])
                    cache_key = f"gh_dim_{gi}"
                    cached = _read_cache(cache_key)
                    if cached is not None:
                        all_candidates.extend(cached)
                    else:
                        futures[pool.submit(
                            fetch_github_search, query, token, since_date
                        )] = cache_key

            # Hacker News
            hn_keywords = build_hn_keywords(profile)
            cached = _read_cache("hn")
            if cached is not None:
                all_candidates.extend(cached)
            else:
                futures[pool.submit(fetch_hn, hn_keywords, since_unix)] = "hn"

            # Reddit
            subs = get_relevant_subs(profile, sources)
            if subs:
                cached = _read_cache("reddit")
                if cached is not None:
                    all_candidates.extend(cached)
                else:
                    futures[pool.submit(fetch_reddit, subs)] = "reddit"

            # OSS Insight trending
            cached = _read_cache("ossinsight")
            if cached is not None:
                all_candidates.extend(cached)
            else:
                futures[pool.submit(fetch_ossinsight)] = "ossinsight"

        # ----- Layer 2: Per-tool channels -----
        if layer in ("2", "both"):
            channels = get_layer2_channels(profile, sources)
            for ch in channels:
                ch_name = ch["name"]
                ch_type = ch.get("type", "")
                cache_key = f"l2_{ch_name}_{ch_type}"

                cached = _read_cache(cache_key)
                if cached is not None:
                    all_candidates.extend(cached)
                    continue

                if ch_type == "rss" and ch.get("url"):
                    futures[pool.submit(
                        fetch_rss, ch["url"], ch_name, since_iso
                    )] = cache_key
                elif ch_type == "github_releases" and ch.get("repo"):
                    futures[pool.submit(
                        fetch_github_releases, ch["repo"], token, since_iso
                    )] = cache_key
                elif ch_type == "page" and ch.get("url"):
                    futures[pool.submit(
                        fetch_page_titles, ch["url"], ch_name
                    )] = cache_key

        # Collect results
        for future in as_completed(futures):
            cache_key = futures[future]
            try:
                results = future.result()
                all_candidates.extend(results)
                _write_cache(cache_key, results)
            except Exception as e:
                _warn(f"Source {cache_key} failed: {e}")

    # Dedupe by URL
    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for c in all_candidates:
        url = c.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            deduped.append(c)

    # Filter obvious piracy/warez — these waste candidate slots and must
    # never be recommended. Compound patterns to avoid false positives
    # (e.g. "crack detection" in image processing is legitimate).
    deduped = _filter_warez(deduped)

    # Sort: prioritize by stars/points (descending), then recency
    def sort_key(c: dict) -> tuple:
        meta = c.get("metadata", {})
        score = meta.get("stars") or meta.get("points") or 0
        created = c.get("created_at", "")
        return (-score, created)  # negative score for descending

    deduped.sort(key=sort_key)

    # Cap output
    return deduped[:max_results]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Gold Digger Scout — fetch candidates from sources")
    parser.add_argument("--profile", required=True, help="Path to profile.yaml")
    parser.add_argument("--sources", required=True, help="Path to sources.yaml")
    parser.add_argument("--github-token", default=None, help="GitHub personal access token")
    parser.add_argument("--layer", choices=["1", "2", "both"], default="both", help="Which layers to fetch")
    parser.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS, help="How far back to look")
    parser.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS, help="Max candidates to return")
    args = parser.parse_args()

    candidates = run_scout(
        profile_path=args.profile,
        sources_path=args.sources,
        github_token=args.github_token,
        layer=args.layer,
        max_age_days=args.max_age_days,
        max_results=args.max_results,
    )

    json.dump(candidates, sys.stdout, indent=2)
    print()  # trailing newline


if __name__ == "__main__":
    main()
