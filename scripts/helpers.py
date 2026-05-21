#!/usr/bin/env python3
"""Gold Digger — deterministic helpers for environment detection, dedupe, and usage signals.

Claude handles judgment; this script handles mechanical filesystem/git operations.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# detect-env: reads the current project + global Claude config to infer stack
# ---------------------------------------------------------------------------

PACKAGE_FILES = {
    "package.json": "node",
    "Cargo.toml": "rust",
    "pyproject.toml": "python",
    "setup.py": "python",
    "go.mod": "go",
    "Gemfile": "ruby",
    "pom.xml": "java",
    "build.gradle": "java",
    "composer.json": "php",
    "pubspec.yaml": "dart",
    "Package.swift": "swift",
    "*.csproj": "dotnet",
}

# Keys in package.json dependencies that map to known stack items
KNOWN_NPM_PACKAGES = {
    "next": "nextjs",
    "react": "react",
    "vue": "vue",
    "svelte": "svelte",
    "nuxt": "nuxt",
    "@supabase/supabase-js": "supabase",
    "@anthropic-ai/sdk": "claude-api",
    "openai": "openai-api",
    "tailwindcss": "tailwindcss",
    "prisma": "prisma",
    "drizzle-orm": "drizzle",
    "@vercel/analytics": "vercel",
    "express": "express",
    "fastify": "fastify",
    "typescript": "typescript",
}


def detect_env(cwd: str | None = None) -> dict:
    """Detect the user's environment: stack, installed MCPs, installed skills."""
    cwd = cwd or os.getcwd()
    result = {
        "stack": [],
        "installed_mcps": [],
        "installed_skills": [],
        "languages": [],
    }

    # 1. Detect stack from package files
    for filename, lang in PACKAGE_FILES.items():
        if "*" in filename:
            if glob.glob(os.path.join(cwd, filename)):
                if lang not in result["languages"]:
                    result["languages"].append(lang)
        elif os.path.exists(os.path.join(cwd, filename)):
            if lang not in result["languages"]:
                result["languages"].append(lang)

    # 2. Parse package.json for known frameworks/libraries
    pkg_path = os.path.join(cwd, "package.json")
    if os.path.exists(pkg_path):
        try:
            with open(pkg_path) as f:
                pkg = json.load(f)
            all_deps = {}
            all_deps.update(pkg.get("dependencies", {}))
            all_deps.update(pkg.get("devDependencies", {}))
            for npm_name, stack_name in KNOWN_NPM_PACKAGES.items():
                if npm_name in all_deps and stack_name not in result["stack"]:
                    result["stack"].append(stack_name)
        except (json.JSONDecodeError, IOError):
            pass

    # 3. Parse pyproject.toml for Python deps (basic — look for known patterns)
    pyproject_path = os.path.join(cwd, "pyproject.toml")
    if os.path.exists(pyproject_path):
        try:
            with open(pyproject_path) as f:
                content = f.read()
            # Simple pattern matching — not a full TOML parser
            known_python = {
                "fastapi": "fastapi",
                "django": "django",
                "flask": "flask",
                "anthropic": "claude-api",
                "openai": "openai-api",
                "supabase": "supabase",
            }
            for pkg_name, stack_name in known_python.items():
                if pkg_name in content and stack_name not in result["stack"]:
                    result["stack"].append(stack_name)
        except IOError:
            pass

    # 4. Read installed MCPs from ~/.claude/settings.json
    settings_path = os.path.expanduser("~/.claude/settings.json")
    if os.path.exists(settings_path):
        try:
            with open(settings_path) as f:
                settings = json.load(f)
            mcp_servers = settings.get("mcpServers", {})
            result["installed_mcps"] = list(mcp_servers.keys())
        except (json.JSONDecodeError, IOError):
            pass

    # Also check project-level MCP config
    project_settings = os.path.join(cwd, ".claude", "settings.json")
    if os.path.exists(project_settings):
        try:
            with open(project_settings) as f:
                settings = json.load(f)
            mcp_servers = settings.get("mcpServers", {})
            for name in mcp_servers:
                if name not in result["installed_mcps"]:
                    result["installed_mcps"].append(name)
        except (json.JSONDecodeError, IOError):
            pass

    # 5. Read installed skills from ~/.claude/skills/
    skills_dir = os.path.expanduser("~/.claude/skills")
    if os.path.isdir(skills_dir):
        for skill_md in glob.glob(os.path.join(skills_dir, "*", "SKILL.md")):
            skill_name = os.path.basename(os.path.dirname(skill_md))
            result["installed_skills"].append(skill_name)

    # Also check .agents/skills/ (vercel-labs/skills standard)
    agents_skills_dir = os.path.expanduser("~/.agents/skills")
    if os.path.isdir(agents_skills_dir):
        for skill_md in glob.glob(os.path.join(agents_skills_dir, "*", "SKILL.md")):
            skill_name = os.path.basename(os.path.dirname(skill_md))
            if skill_name not in result["installed_skills"]:
                result["installed_skills"].append(skill_name)

    return result


# ---------------------------------------------------------------------------
# batch: dedupe + usage-signal for multiple candidates in one shot
# ---------------------------------------------------------------------------

def _get_installed_inventory() -> dict:
    """Load the full inventory of installed MCPs and skills ONCE."""
    inventory = {"mcps": [], "skills": [], "skill_descriptions": {}}

    # MCPs from ~/.claude/settings.json
    settings_path = os.path.expanduser("~/.claude/settings.json")
    if os.path.exists(settings_path):
        try:
            with open(settings_path) as f:
                settings = json.load(f)
            inventory["mcps"] = list(settings.get("mcpServers", {}).keys())
        except (json.JSONDecodeError, IOError):
            pass

    # Skills from ~/.claude/skills/ and ~/.agents/skills/
    for base in ["~/.claude/skills", "~/.agents/skills"]:
        skills_dir = os.path.expanduser(base)
        if os.path.isdir(skills_dir):
            for skill_md in glob.glob(os.path.join(skills_dir, "*", "SKILL.md")):
                skill_name = os.path.basename(os.path.dirname(skill_md))
                if skill_name not in inventory["skills"]:
                    inventory["skills"].append(skill_name)
                # Read description for similarity matching
                try:
                    with open(skill_md) as f:
                        content = f.read(1000)  # first 1KB is enough
                    inventory["skill_descriptions"][skill_name] = content
                except IOError:
                    pass

    return inventory


def _get_git_log_summary() -> str:
    """Get recent git log for usage signal. Cached per invocation."""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--since=90 days ago", "--name-only", "-50"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _check_similarity(candidate_name: str, installed_items: list[str]) -> list[str]:
    """Find installed items with similar names (simple substring/prefix matching)."""
    similar = []
    c_lower = candidate_name.lower().replace("-", "").replace("_", "")
    for item in installed_items:
        i_lower = item.lower().replace("-", "").replace("_", "")
        # Check if one is a substring of the other, or they share a long prefix
        if c_lower in i_lower or i_lower in c_lower:
            similar.append(item)
        elif len(c_lower) > 4 and len(i_lower) > 4:
            # Check shared prefix (at least 5 chars)
            prefix_len = 0
            for a, b in zip(c_lower, i_lower):
                if a == b:
                    prefix_len += 1
                else:
                    break
            if prefix_len >= 5:
                similar.append(item)
    return similar


def batch_check(candidates_json: str, profile_path: str) -> list[dict]:
    """Check dedupe + usage signal for all candidates in one shot.

    Reads filesystem and git ONCE, then checks each candidate against the
    shared data. Much faster than N separate subprocess calls.
    """
    try:
        import yaml as _yaml
    except ImportError:
        _yaml = None

    candidates = json.loads(candidates_json)
    inventory = _get_installed_inventory()
    git_log = _get_git_log_summary()

    # Load profile for additional installed items
    profile_mcps = []
    profile_skills = []
    if _yaml and os.path.exists(profile_path):
        try:
            with open(profile_path) as f:
                profile = _yaml.safe_load(f) or {}
            profile_mcps = profile.get("detected", {}).get("installed_mcps", [])
            profile_skills = profile.get("detected", {}).get("installed_skills", [])
        except Exception:
            pass

    all_installed = list(set(
        inventory["mcps"] + inventory["skills"] + profile_mcps + profile_skills
    ))

    results = []
    for candidate in candidates:
        name = candidate.get("name", candidate.get("title", "")).lower().strip()
        # Normalize: strip common prefixes
        for prefix in ["mcp-server-", "mcp-", "claude-", "skill-"]:
            if name.startswith(prefix):
                name_short = name[len(prefix):]
                break
        else:
            name_short = name

        # Dedupe check
        already_installed = any(
            name_short in item.lower() or item.lower() in name_short
            for item in all_installed
        )

        # Similarity check
        similar = _check_similarity(name_short, all_installed)

        # Usage signal from git log
        last_used_days_ago = None
        usage_evidence = ""
        if name_short and git_log:
            # Check if mentioned in recent git changes
            if name_short in git_log.lower():
                usage_evidence = "Referenced in recent git activity"
                last_used_days_ago = 0  # recent

        results.append({
            "candidate": candidate.get("name", candidate.get("title", "")),
            "already_installed": already_installed,
            "similar": similar,
            "last_used_days_ago": last_used_days_ago,
            "usage_evidence": usage_evidence,
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
