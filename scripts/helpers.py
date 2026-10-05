#!/usr/bin/env python3
"""Gold Digger — deterministic helpers for environment detection, dedupe, and usage signals.

Claude handles judgment; this script handles mechanical filesystem/git operations.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# detect-env: thin wrapper over inventory.py (kept for profile v3 compatibility)
# ---------------------------------------------------------------------------

def detect_env(cwd: str | None = None) -> dict:
    """Compact stack/MCP/skill summary. Full detail: scripts/inventory.py."""
    from inventory import scan_claude, scan_project

    root = Path(cwd or os.getcwd()).resolve()
    project = scan_project(root)
    claude = scan_claude(root)
    deps = (project.get("npm") or {}).get("dependencies", []) + (project.get("python") or {}).get("dependencies", [])
    return {
        "stack": sorted(set(project["infra_files"].values()) | set(deps)),
        "services_hint": project["env_service_prefixes"],
        "installed_mcps": [m["name"] for m in claude["mcp_servers"]],
        "installed_plugins": [p["id"] for p in claude["plugins"]],
        "installed_skills": [s["name"] for s in claude["skills"]],
        "languages": project["languages"],
    }


# ---------------------------------------------------------------------------
# batch: dedupe + usage-signal for multiple candidates in one shot
# ---------------------------------------------------------------------------

_NOISE_TOKENS = {"mcp", "server", "skill", "skills", "claude", "plugin", "agent", "ai", "the", "for",
                "official", "best", "practices", "tools", "kit", "helper", "js", "sdk", "cli"}


def _tokens(name: str) -> set[str]:
    """'io.github.foo/mcp-server-git' → {'git'}; 'vercel:nextjs' → {'vercel', 'nextjs'}."""
    name = name.lower().split("/")[-1]
    parts = re.split(r"[^a-z0-9]+", name)
    return {p for p in parts if p and p not in _NOISE_TOKENS}


def batch_check(candidates_json: str, profile_path: str) -> list[dict]:
    """For each candidate: is it (or something with the same core name) already installed?

    Matching is on whole name tokens, not substrings — 'mcp-server-git' no longer
    "matches" an installed 'github'. Exact = all core tokens equal; similar = shares
    a core token, surfaced for Claude to judge (overlap, not proof of duplication).
    """
    from inventory import scan_claude

    candidates = json.loads(candidates_json)
    claude = scan_claude(Path(os.getcwd()).resolve())
    installed = ([m["name"] for m in claude["mcp_servers"]] + [p["id"].split("@")[0] for p in claude["plugins"]]
                 + [s["name"] for s in claude["skills"]])
    inst_tokens = {name: _tokens(name) for name in installed}

    results = []
    for candidate in candidates:
        raw = candidate.get("name") or candidate.get("title") or ""
        ct = _tokens(raw)
        exact = [n for n, t in inst_tokens.items() if ct and t == ct]
        similar = [n for n, t in inst_tokens.items() if n not in exact and ct & t]
        results.append({
            "candidate": raw,
            "already_installed": bool(exact),
            "installed_as": exact,
            "similar": similar[:5],
        })
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Gold Digger helpers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # detect-env
    env_parser = subparsers.add_parser("detect-env", help="Detect current environment")
    env_parser.add_argument("--cwd", default=None, help="Working directory to scan")

    # batch
    batch_parser = subparsers.add_parser(
        "batch", help="Batch dedupe + usage-signal for multiple candidates"
    )
    batch_parser.add_argument(
        "--candidates", required=True,
        help="JSON array of candidate objects (each with 'name' or 'title')"
    )
    batch_parser.add_argument(
        "--profile", required=True, help="Path to profile.yaml"
    )

    args = parser.parse_args()

    if args.command == "detect-env":
        result = detect_env(args.cwd)
        print(json.dumps(result, indent=2))
    elif args.command == "batch":
        results = batch_check(args.candidates, args.profile)
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
