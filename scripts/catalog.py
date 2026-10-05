#!/usr/bin/env python3
"""Gold Digger — live catalog search. The portfolio's source of truth.

Every candidate Gold Digger recommends must come from a LIVE source queried in
the current session — never from the model's memory. This script is how.

  catalog.py search -q "video rendering" -q "text to speech" [--kinds skills,mcp,repos,npm,hn]
  catalog.py check --url <url> [--url <url> ...]   # verify a link found elsewhere (WebSearch, queue)

Sources (keyword search, NO date filter — established and brand-new alike):
  skills  skills.sh/api/search (the API behind Vercel's `npx skills find`)
          + add-skill.vercel.sh/audit (ath / socket / snyk / zeroleaks risk)
  mcp     Official MCP Registry search (namespace tells you who published it)
  repos   GitHub repo search, non-archived, pushed in the last year, by stars
  npm     npm registry search, with weekly downloads
  hn      Hacker News (Algolia) — surfaces products, services and AI models that
          live in no package registry, including ones the model has never heard of

Noise handling done here (mechanical; Claude does the judging):
  - skills: clones of the same skill are grouped; the canonical one is the oldest
    non-fork repo. A younger copy out-installing the original is flagged.
  - mcp: entries are tagged domain-verified / github-user / re-publisher.
  - every result carries liveness (pushed_at, archived) and adoption numbers verbatim.
Fail loud: a source that errors is reported in "errors", never as "no results".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from net import (CACHE_DIR, cache_get, cache_put, fetch_bytes, fetch_json, github_headers, github_repo, qs, warn)

SKILLS_API = "https://skills.sh/api/search"
AUDIT_API = "https://add-skill.vercel.sh/audit"
MCP_REGISTRY = "https://registry.modelcontextprotocol.io/v0.1/servers"
CACHE_TTL = 6 * 3600
ALL_KINDS = ("skills", "mcp", "repos", "npm", "hn")
RISK_ORDER = ["safe", "low", "unknown", "medium", "high", "critical"]
REPUBLISHER_NAMESPACES = ("ai.smithery", "ai.waystation", "io.github.mcp-dir", "com.pulsemcp", "ai.glama")
_MCP_LOCK = threading.Lock()  # the registry times out under parallel searches — one at a time
_GH_REPO = re.compile(r"^[\w.-]+/[\w.-]+$")


def _cached(key: str, fn):
    hit = cache_get(key, CACHE_TTL)
    if hit is not None:
        return hit
    data = fn()
    cache_put(key, data)
    return data


def _days_ago(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).days
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Skills (skills.sh)
# ---------------------------------------------------------------------------

def _audit(source: str, skill_ids: list[str]) -> dict:
    try:
        return fetch_json(f"{AUDIT_API}?{qs({'source': source, 'skills': ','.join(skill_ids)})}", timeout=6) or {}
    except Exception as e:
        warn(f"audit {source}: {e}")
        return {}


def _summarize_audit(per_auditor: dict | None) -> dict | None:
    if not per_auditor:
        return None
    risks = {name: a.get("risk", "unknown") for name, a in per_auditor.items()}
    worst = max(risks.values(), key=lambda r: RISK_ORDER.index(r) if r in RISK_ORDER else 2)
    return {"worst": worst, "by_auditor": risks}


def search_skills(query: str, limit: int, audit: bool) -> list[dict]:
    data = _cached(f"skills:{query}", lambda: fetch_json(f"{SKILLS_API}?{qs({'q': query, 'limit': 30})}"))
    rows = data.get("skills", [])

    # Same skill name from several publishers: usually copies of one original, sometimes
    # unrelated skills with a generic name. Group them; pick the canonical below.
    # Keep the API's relevance order — ranking by installs lets popular-but-irrelevant win.
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault((r.get("skillId") or r.get("name", "")).lower(), []).append(r)
    ranked = list(groups.values())[:limit]
    query_tokens = {t for t in re.split(r"[^a-z0-9]+", query.lower()) if len(t) > 3}

    # Repo facts for every distinct GitHub source in the shortlisted groups (parallel).
    sources = {r["source"] for g in ranked for r in g if _GH_REPO.match(r.get("source", ""))}
    with ThreadPoolExecutor(max_workers=8) as pool:
        repo_facts = dict(zip(sources, pool.map(github_repo, sources)))

    results = []
    for g in ranked:
        def canon_key(r: dict) -> tuple:
            facts = repo_facts.get(r["source"]) or {}
            owner = r["source"].split("/")[0].lower()
            name_tokens = query_tokens | {t for t in re.split(r"[^a-z0-9]+", (r.get("name") or "").lower()) if len(t) > 3}
            return (
                not any(t in owner for t in name_tokens),  # publisher IS the product (remotion-dev ↔ remotion)
                bool(facts.get("is_fork")),
                -(facts.get("stars") or 0),                # stars are harder to fake than installs
                facts.get("created_at") or "9999",
            )
        g_sorted = sorted(g, key=canon_key)
        canon = g_sorted[0]
        facts = repo_facts.get(canon["source"]) or {}
        flags = []
        others = []
        for c in g_sorted[1:]:
            cf = repo_facts.get(c["source"]) or {}
            others.append({"source": c["source"], "installs": c.get("installs"), "stars": cf.get("stars"),
                           "is_fork": cf.get("is_fork"), "repo_created_at": cf.get("created_at")})
            younger = (cf.get("created_at") or "9999") > (facts.get("created_at") or "")
            if ((c.get("installs") or 0) > (canon.get("installs") or 0) and younger
                    and (cf.get("stars") or 0) < (facts.get("stars") or 0)):
                flags.append(f"{c['source']} (younger repo, fewer stars) has more installs than this one "
                             "— install counts for this skill name look inflated")
        if facts.get("archived"):
            flags.append("source repo archived")
        age = _days_ago(facts.get("created_at"))
        if age is not None and age < 60 and (canon.get("installs") or 0) > 100_000:
            flags.append(f"repo is {age} days old with {canon.get('installs')} installs — unusual")
        results.append({
            "kind": "skill",
            "name": canon.get("name"),
            "source": canon.get("source"),
            "install": f"npx skills add {canon.get('source')}@{canon.get('skillId') or canon.get('name')}",
            "url": f"https://skills.sh/{canon.get('id')}",
            "installs": canon.get("installs"),
            "repo": {k: facts.get(k) for k in ("url", "stars", "pushed_at", "created_at", "archived", "is_fork", "description")} if facts else None,
            "same_name_elsewhere": others,
            "flags": flags,
            "_skill_id": canon.get("skillId") or canon.get("name"),
        })

    if audit and results:
        by_source: dict[str, list[dict]] = {}
        for r in results:
            by_source.setdefault(r["source"], []).append(r)
        with ThreadPoolExecutor(max_workers=6) as pool:
            audits = dict(zip(by_source, pool.map(
                lambda s: _audit(s, [r["_skill_id"] for r in by_source[s]]), by_source)))
        for r in results:
            r["audit"] = _summarize_audit(audits.get(r["source"], {}).get(r["_skill_id"]))
            if r["audit"] and r["audit"]["worst"] in ("high", "critical"):
                r["flags"].append(f"security audit: {r['audit']['worst']} ({r['audit']['by_auditor']})")
    for r in results:
        r.pop("_skill_id", None)
    return results


# ---------------------------------------------------------------------------
# MCP servers (official registry)
# ---------------------------------------------------------------------------

def _publisher_kind(name: str, query: str) -> str:
    ns = name.split("/")[0]
    if ns.startswith(REPUBLISHER_NAMESPACES):
        return "re-publisher (third party listing someone else's server)"
    if ns.startswith("io.github."):
        return "github-user-verified"
    tokens = {t for t in re.split(r"\W+", query.lower()) if len(t) > 2}
    ns_tokens = set(re.split(r"[^a-z0-9]+", ns.lower()))
    if tokens & ns_tokens:
        return "domain-verified, namespace matches the product (likely official)"
    return "domain-verified"


MCP_INDEX = CACHE_DIR / "mcp_index.json"
MCP_INDEX_TTL = 24 * 3600


def _compact_server(entry: dict) -> dict:
    srv = entry.get("server", {})
    meta = (entry.get("_meta") or {}).get("io.modelcontextprotocol.registry/official", {})
    return {
        "name": srv.get("name", ""),
        "title": srv.get("title") or "",
        "description": (srv.get("description") or "")[:400],
        "version": srv.get("version"),
        "updated_at": meta.get("updatedAt") or meta.get("publishedAt"),
        "hosted_remote": bool(srv.get("remotes")),
        "packages": sorted({p.get("registryType", "") for p in srv.get("packages", []) or []} - {""}),
        "repository": (srv.get("repository") or {}).get("url", ""),
    }


def _paginate_registry(extra: dict) -> list[dict]:
    out, cursor = [], None
    while True:
        params = {"version": "latest", "limit": 100, **extra, **({"cursor": cursor} if cursor else {})}
        data = fetch_json(f"{MCP_REGISTRY}?{qs(params)}", timeout=30)
        out += [_compact_server(e) for e in data.get("servers", [])]
        cursor = (data.get("metadata") or {}).get("nextCursor")
        if not cursor:
            return out


def mcp_index(force_full: bool = False) -> dict[str, dict]:
    """Local mirror of the official MCP registry.

    The registry's own `search` times out under any load and only matches names, so we
    mirror it: one full sync (~20k servers, a couple of minutes, once), then cheap
    incremental syncs via `updated_since`. Search runs locally over name + title + description.
    """
    with _MCP_LOCK:
        index: dict = {}
        try:
            index = json.loads(MCP_INDEX.read_text())
        except (OSError, json.JSONDecodeError):
            pass
        servers = index.get("servers", {})
        synced_at = index.get("synced_at")
        fresh = synced_at and _days_ago(synced_at) is not None and \
            (datetime.now(timezone.utc) - datetime.fromisoformat(synced_at)).total_seconds() < MCP_INDEX_TTL
        if servers and fresh and not force_full:
            return servers
        started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if servers and synced_at and not force_full:
            updates = _paginate_registry({"updated_since": synced_at})
        else:
            warn("building the local MCP registry index (first run only, ~2-3 min)…", "catalog")
            servers, updates = {}, _paginate_registry({})
        for s in updates:
            servers[s["name"]] = s
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        MCP_INDEX.write_text(json.dumps({"synced_at": started, "servers": servers}))
        return servers


def search_mcp(query: str, limit: int) -> list[dict]:
    servers = mcp_index()
    words = [w for w in re.split(r"[^a-z0-9]+", query.lower()) if len(w) > 2]
    # Whole words only: "voice" must not match "invoice", "ocr" not "seocrawl".
    def toks(text: str) -> set[str]:
        return set(re.split(r"[^a-z0-9]+", text.lower()))
    scored = []
    for s in servers.values():
        name, title, desc = toks(s["name"]), toks(s["title"]), toks(s["description"])
        if not all(w in name or w in title or w in desc for w in words):
            continue
        score = sum(3 * (w in name) + 2 * (w in title) + (w in desc) for w in words)
        scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    results = [{
        "kind": "mcp",
        "name": s["name"],
        "title": s["title"] or s["name"],
        "description": s["description"],
        "publisher": _publisher_kind(s["name"], query),
        "version": s["version"],
        "registry_updated_at": s["updated_at"],
        "hosted_remote": s["hosted_remote"],
        "packages": s["packages"],
        "repository": s["repository"],
        "_score": score,
    } for score, s in scored[:limit * 5]]
    # Likely-official first, re-publishers last.
    order = lambda r: (0 if "likely official" in r["publisher"] else 2 if r["publisher"].startswith("re-publisher") else 1,
                       -r.pop("_score"))
    results.sort(key=order)
    results = results[:limit]
    gh = [r for r in results if "github.com/" in r["repository"]]
    with ThreadPoolExecutor(max_workers=6) as pool:
        facts = list(pool.map(lambda r: github_repo(r["repository"].split("github.com/")[1].removesuffix(".git").strip("/")), gh))
    for r, f in zip(gh, facts):
        if f:
            r["repo"] = {k: f.get(k) for k in ("stars", "pushed_at", "archived")}
    return results


# ---------------------------------------------------------------------------
# GitHub repos, npm, Hacker News
# ---------------------------------------------------------------------------

def search_repos(query: str, limit: int) -> list[dict]:
    year_ago = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")
    q = f'"{query}" in:name,description,topics archived:false pushed:>{year_ago}'
    url = f"https://api.github.com/search/repositories?{qs({'q': q, 'sort': 'stars', 'order': 'desc', 'per_page': 30})}"
    data = _cached(f"repos:{query}", lambda: fetch_json(url, github_headers()))
    # GitHub stems even quoted terms ("remotion" matches "remote"); keep repos that
    # literally mention every significant word of the query.
    words = [w for w in re.split(r"[^a-z0-9]+", query.lower()) if len(w) > 2]
    def mentions(r: dict) -> bool:
        text = re.sub(r"[^a-z0-9]+", " ", " ".join(
            [r.get("full_name") or "", r.get("description") or "", " ".join(r.get("topics", []))]).lower())
        return all(w in text for w in words)
    items = [r for r in data.get("items", []) if mentions(r)][:limit]
    return [{
        "kind": "repo",
        "name": r.get("full_name"),
        "url": r.get("html_url"),
        "description": r.get("description") or "",
        "stars": r.get("stargazers_count"),
        "forks_count": r.get("forks_count"),
        "pushed_at": r.get("pushed_at"),
        "created_at": r.get("created_at"),
        "topics": r.get("topics", [])[:8],
        "homepage": r.get("homepage") or None,
    } for r in items]


def search_npm(query: str, limit: int) -> list[dict]:
    url = f"https://registry.npmjs.org/-/v1/search?{qs({'text': query, 'size': limit})}"
    data = _cached(f"npm:{query}", lambda: fetch_json(url))
    out = []
    for o in data.get("objects", []):
        p = o.get("package", {})
        out.append({
            "kind": "npm",
            "name": p.get("name"),
            "description": p.get("description") or "",
            "version": p.get("version"),
            "published_at": p.get("date"),
            "weekly_downloads": (o.get("downloads") or {}).get("weekly"),
            "dependents": o.get("dependents"),
            "url": (p.get("links") or {}).get("npm"),
            "repository": (p.get("links") or {}).get("repository"),
            "homepage": (p.get("links") or {}).get("homepage"),
        })
    return out


def search_hn(query: str, limit: int) -> list[dict]:
    base = "https://hn.algolia.com/api/v1/search"
    def run() -> list[dict]:
        hits = []
        since = int((datetime.now(timezone.utc) - timedelta(days=730)).timestamp())
        for params in ({"query": query, "tags": "story", "numericFilters": f"points>=15,created_at_i>{since}", "hitsPerPage": limit},
                       {"query": query, "tags": "show_hn", "numericFilters": f"points>=5,created_at_i>{since}", "hitsPerPage": limit}):
            hits += fetch_json(f"{base}?{qs(params)}").get("hits", [])
        return hits
    seen, out = set(), []
    for h in _cached(f"hn:{query}", run):
        url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        if url in seen:
            continue
        seen.add(url)
        out.append({
            "kind": "hn",
            "title": h.get("title"),
            "url": url,
            "points": h.get("points"),
            "comments": h.get("num_comments"),
            "created_at": h.get("created_at"),
            "discussion": f"https://news.ycombinator.com/item?id={h.get('objectID')}",
        })
    return out[: limit * 2]


SEARCHERS = {
    "skills": lambda q, n, a: search_skills(q, n, a),
    "mcp": lambda q, n, a: search_mcp(q, n),
    "repos": lambda q, n, a: search_repos(q, n),
    "npm": lambda q, n, a: search_npm(q, n),
    "hn": lambda q, n, a: search_hn(q, n),
}


def run_search(queries: list[str], kinds: list[str], limit: int, audit: bool) -> dict:
    jobs = [(q, k) for q in queries for k in kinds]
    out: dict[str, dict] = {q: {"query": q, "results": {}, "errors": {}} for q in queries}

    def job(qk):
        q, k = qk
        try:
            return q, k, SEARCHERS[k](q, limit, audit), None
        except Exception as e:
            return q, k, None, f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=10) as pool:
        for q, k, res, err in pool.map(job, jobs):
            if err:
                out[q]["errors"][k] = err
                warn(f"{k} '{q}': {err}", "catalog")
            else:
                out[q]["results"][k] = res
    return {
        "searched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kinds": kinds,
        "queries": list(out.values()),
    }


# ---------------------------------------------------------------------------
# check: verify a single link is live (for WebSearch finds and queue items)
# ---------------------------------------------------------------------------

def check_url(url: str) -> dict:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    parts = [p for p in parsed.path.split("/") if p]
    try:
        if host == "github.com" and len(parts) >= 2:
            facts = github_repo(f"{parts[0]}/{parts[1]}")
            return {"url": url, "kind": "repo", "live": facts is not None, **(facts or {})}
        if host in ("npmjs.com", "www.npmjs.com") and len(parts) >= 2 and parts[0] == "package":
            name = "/".join(parts[1:3]) if parts[1].startswith("@") else parts[1]
            meta = fetch_json(f"https://registry.npmjs.org/{urllib.parse.quote(name, safe='@')}/latest")
            dl = fetch_json(f"https://api.npmjs.org/downloads/point/last-week/{name}")
            return {"url": url, "kind": "npm", "live": True, "name": name, "version": meta.get("version"),
                    "description": meta.get("description"), "weekly_downloads": dl.get("downloads")}
        if host == "skills.sh" and len(parts) >= 3:
            res = search_skills(parts[-1], 5, audit=True)
            match = [r for r in res if r["source"] == f"{parts[0]}/{parts[1]}"] or res[:1]
            return {"url": url, "kind": "skill", "live": bool(match), **(match[0] if match else {})}
        body = fetch_bytes(url, timeout=10)[:200_000].decode("utf-8", errors="ignore")
        title = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
        desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', body, re.I)
        return {"url": url, "kind": "page", "live": True,
                "title": " ".join(title.group(1).split())[:200] if title else None,
                "description": desc.group(1)[:300] if desc else None}
    except Exception as e:
        return {"url": url, "live": False, "error": f"{type(e).__name__}: {e}"}


def main() -> None:
    ap = argparse.ArgumentParser(description="Gold Digger live catalog search")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("-q", "--query", action="append", required=True, help="Repeatable")
    s.add_argument("--kinds", default=",".join(ALL_KINDS))
    s.add_argument("--limit", type=int, default=6, help="Results per source per query")
    s.add_argument("--no-audit", action="store_true")
    sub.add_parser("sync-mcp", help="Build/refresh the local MCP registry index")
    c = sub.add_parser("check")
    c.add_argument("--url", action="append", required=True, help="Repeatable")
    args = ap.parse_args()

    if args.cmd == "sync-mcp":
        result = {"servers_indexed": len(mcp_index())}
    elif args.cmd == "search":
        kinds = [k.strip() for k in args.kinds.split(",") if k.strip() in SEARCHERS]
        result = run_search(args.query, kinds, args.limit, not args.no_audit)
    else:
        with ThreadPoolExecutor(max_workers=6) as pool:
            result = {"checked": list(pool.map(check_url, args.url))}
    json.dump(result, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
