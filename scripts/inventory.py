#!/usr/bin/env python3
"""Gold Digger — inventory of the user's CURRENT portfolio, with real usage.

Answers "what do you already have, and do you actually use it?" so the skill
can say what's surplus (DROP / overlap) and what's missing (gap).

Reads, never writes. Never reads secret VALUES — only env var NAMES.

  inventory.py [--cwd DIR] [--days 60]

Output (JSON):
  project: languages, dependencies (+ possibly-unused), infra/config files,
           services inferred from deps/env-var names/config files
  claude:  MCP servers (every config location), plugins, skills
  usage:   per MCP server / skill: calls + last use in the last N days,
           mined from Claude Code transcripts (~/.claude/projects/*.jsonl)
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", ".nuxt", ".svelte-kit", "out",
    ".venv", "venv", "__pycache__", ".turbo", ".vercel", "coverage", ".cache", "target",
}
JS_EXT = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte", ".astro"}
PY_EXT = {".py"}
MAX_SOURCE_FILES = 4000
MAX_FILE_BYTES = 400_000

# MCP servers provided by the host app itself — never candidates for DROP.
HOST_BUILTIN_PREFIXES = (
    "ccd_", "Claude_Browser", "Claude_Code_", "terminal", "visualize", "computer-use",
    "claude-in-chrome", "scheduled-tasks", "mcp-registry",
)

# Config/infra files that reveal tools and services. Value = what it implies.
INFRA_FILES = {
    "vercel.json": "vercel", "netlify.toml": "netlify", "fly.toml": "fly.io",
    "railway.json": "railway", "railway.toml": "railway", "wrangler.toml": "cloudflare-workers",
    "wrangler.jsonc": "cloudflare-workers", "render.yaml": "render", "Dockerfile": "docker",
    "docker-compose.yml": "docker-compose", "compose.yaml": "docker-compose",
    "supabase/config.toml": "supabase", "firebase.json": "firebase", "amplify.yml": "aws-amplify",
    "prisma/schema.prisma": "prisma", "remotion.config.ts": "remotion",
    "playwright.config.ts": "playwright", ".github/workflows": "github-actions",
    "turbo.json": "turborepo", "nx.json": "nx", "components.json": "shadcn-ui",
    "sanity.config.ts": "sanity", "expo-env.d.ts": "expo", "app.json": "expo-or-react-native",
    "default.project.json": "roblox-rojo", "project.godot": "godot", "ProjectSettings": "unity",
}
INFRA_GLOBS = {
    "next.config.*": "nextjs", "vite.config.*": "vite", "tailwind.config.*": "tailwindcss",
    "drizzle.config.*": "drizzle", "vitest.config.*": "vitest", "jest.config.*": "jest",
    "sentry.*.config.*": "sentry", "astro.config.*": "astro", "svelte.config.*": "sveltekit",
    "nuxt.config.*": "nuxt", "*.csproj": "dotnet", "*.uproject": "unreal",
}
PACKAGE_FILES = {
    "package.json": "javascript/typescript", "pyproject.toml": "python", "requirements.txt": "python",
    "setup.py": "python", "go.mod": "go", "Cargo.toml": "rust", "Gemfile": "ruby",
    "pom.xml": "java", "build.gradle": "java/kotlin", "composer.json": "php",
    "pubspec.yaml": "dart/flutter", "Package.swift": "swift",
}
# Claude Code built-in slash commands — not skills, never counted as skill usage.
BUILTIN_COMMANDS = {
    "model", "doctor", "clear", "compact", "config", "help", "init", "login", "logout", "mcp",
    "memory", "permissions", "review", "status", "cost", "resume", "add-dir", "agents", "hooks",
    "ide", "plugin", "plugins", "fast", "effort", "context", "export", "rewind", "usage",
    "statusline", "terminal-setup", "vim", "bug", "release-notes", "upgrade", "theme",
    "output-style", "privacy-settings", "install-github-app", "todos", "exit", "skills",
    "remote-control", "sandbox", "feedback", "btw", "loop", "goal",
}
# Dependencies that are build tooling, not portfolio choices — never flag as unused.
TOOLING_DEPS = re.compile(
    r"^(@types/|typescript$|eslint|prettier|@eslint/|ts-node|tsx$|@typescript-eslint/|postcss|"
    r"autoprefixer|husky|lint-staged|rimraf|cross-env|concurrently|nodemon|@biomejs/)"
)
ENV_FILES = (".env.example", ".env.sample", ".env.template", ".env.local.example", ".env", ".env.local",
             ".env.development", ".env.production", ".dev.vars")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _frontmatter_description(skill_md: Path) -> str:
    try:
        head = skill_md.read_text(errors="ignore")[:3000]
    except OSError:
        return ""
    m = re.search(r"^description:\s*(>-?|\|-?)?\s*\n?(.*?)(?=^\w[\w-]*:|^---)", head, re.S | re.M)
    if not m:
        return ""
    return " ".join(m.group(2).split())[:300]


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------

def _walk_sources(cwd: Path, exts: set[str]) -> list[Path]:
    files: list[Path] = []
    for root, dirs, names in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for n in names:
            if Path(n).suffix in exts:
                files.append(Path(root) / n)
                if len(files) >= MAX_SOURCE_FILES:
                    return files
    return files


def _read_sources(files: list[Path]) -> str:
    chunks = []
    for f in files:
        try:
            if f.stat().st_size <= MAX_FILE_BYTES:
                chunks.append(f.read_text(errors="ignore"))
        except OSError:
            pass
    return "\n".join(chunks)


_JS_IMPORT = re.compile(r"""(?:from\s+|require\(\s*|import\(\s*|import\s+)['"]([^'"]+)['"]""")
_PY_IMPORT = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][\w]*)", re.M)


def _npm_project(cwd: Path) -> dict | None:
    pkg = _read_json(cwd / "package.json")
    if not pkg:
        return None
    deps = dict(pkg.get("dependencies", {}))
    dev = dict(pkg.get("devDependencies", {}))
    source_text = _read_sources(_walk_sources(cwd, JS_EXT))
    imported = set()
    for spec in _JS_IMPORT.findall(source_text):
        if spec.startswith((".", "/")):
            continue
        parts = spec.split("/")
        imported.add("/".join(parts[:2]) if spec.startswith("@") else parts[0])
    # CLIs referenced from scripts or config files count as used too
    aux = json.dumps(pkg.get("scripts", {}))
    for cfg in list(cwd.glob("*.config.*")) + list(cwd.glob(".*rc*")):
        try:
            aux += cfg.read_text(errors="ignore")[:20000]
        except OSError:
            pass
    # CSS-first tools (Tailwind v4: @import "tailwindcss") and companion packages
    aux += _read_sources(_walk_sources(cwd, {".css", ".scss"}))[:200000]
    if "react" in deps or "react" in dev:
        imported.add("react-dom")
    unused = []
    for name in list(deps) + list(dev):
        if TOOLING_DEPS.search(name) or name in imported:
            continue
        bare = name.split("/")[-1]
        if name in aux or re.search(rf"\b{re.escape(bare)}\b", aux):
            continue
        unused.append(name)
    return {
        "dependencies": sorted(deps),
        "dev_dependencies": sorted(dev),
        "possibly_unused": sorted(unused),
    }


# Distribution name → import name, where they differ (the common cases only; Claude
# judges the rest — "possibly_unused" is a hint, never a verdict).
PY_IMPORT_ALIASES = {
    "python-docx": "docx", "pyjwt": "jwt", "pyyaml": "yaml", "pillow": "PIL", "beautifulsoup4": "bs4",
    "scikit-learn": "sklearn", "python-dotenv": "dotenv", "opencv-python": "cv2", "psycopg": "psycopg",
    "psycopg2-binary": "psycopg2", "python-multipart": "multipart", "google-genai": "google",
    "sentry-sdk": "sentry_sdk", "pydantic-settings": "pydantic_settings", "python-dateutil": "dateutil",
}
# Pulled in implicitly by a framework, or run as a CLI rather than imported.
PY_IMPLICIT = {"uvicorn", "gunicorn", "python-multipart", "alembic", "ruff", "pytest", "mypy", "black",
               "pre-commit", "httpx", "cryptography"}


def _req_name(spec: str) -> str:
    return re.split(r"[<>=!~\[; @]", spec.strip(), maxsplit=1)[0]


def _python_project(cwd: Path) -> dict | None:
    names: list[str] = []
    dev: list[str] = []
    req = cwd / "requirements.txt"
    if req.exists():
        for line in req.read_text(errors="ignore").splitlines():
            line = line.split("#")[0].strip()
            if line and not line.startswith("-"):
                names.append(_req_name(line))
    pyproject = cwd / "pyproject.toml"
    if pyproject.exists():
        try:
            import tomllib
            data = tomllib.loads(pyproject.read_text(errors="ignore"))
        except Exception:
            data = {}
        project = data.get("project", {})
        names += [_req_name(x) for x in project.get("dependencies", [])]
        for group in list(project.get("optional-dependencies", {}).values()) + list(data.get("dependency-groups", {}).values()):
            dev += [_req_name(x) for x in group if isinstance(x, str)]
        poetry = data.get("tool", {}).get("poetry", {})
        names += [n for n in poetry.get("dependencies", {}) if n.lower() != "python"]
    if not names and not dev:
        return None
    source = _read_sources(_walk_sources(cwd, PY_EXT))
    imported = {m.lower() for m in _PY_IMPORT.findall(source)}
    aux = ""
    for f in ("Dockerfile", "Procfile", "pyproject.toml", "alembic.ini"):
        try:
            aux += (cwd / f).read_text(errors="ignore")[:20000] if f != "pyproject.toml" else ""
        except OSError:
            pass
    for sh in list(cwd.glob("*.sh")) + list(cwd.glob("scripts/*.sh")):
        try:
            aux += sh.read_text(errors="ignore")[:20000]
        except OSError:
            pass
    unused = []
    for n in names:
        mod = PY_IMPORT_ALIASES.get(n.lower(), n.lower().replace("-", "_")).lower()
        if mod in imported or n.lower() in PY_IMPLICIT or re.search(rf"\b{re.escape(n)}\b", aux):
            continue
        unused.append(n)
    return {
        "dependencies": sorted(set(names)),
        "dev_dependencies": sorted(set(dev)),
        "possibly_unused": sorted(set(unused)),
    }


def _env_var_names(cwd: Path) -> list[str]:
    names: set[str] = set()
    for fname in ENV_FILES:
        p = cwd / fname
        if not p.is_file():
            continue
        try:
            for line in p.read_text(errors="ignore").splitlines():
                m = re.match(r"\s*(?:export\s+)?([A-Z][A-Z0-9_]{2,})\s*=", line)
                if m:
                    names.add(m.group(1))  # NAME only — the value is never read into output
        except OSError:
            pass
    return sorted(names)


def _subproject_dirs(cwd: Path, max_depth: int = 2) -> list[Path]:
    """The root plus any folder (≤ max_depth) holding a package manifest — monorepos
    keep backend/ and web/ side by side and the root has no manifest at all."""
    found = [cwd]
    for root, dirs, names in os.walk(cwd):
        depth = len(Path(root).relative_to(cwd).parts)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")] if depth < max_depth else []
        if depth and any(n in PACKAGE_FILES for n in names):
            found.append(Path(root))
    return found


def _scan_dir(d: Path) -> dict:
    infra: dict[str, str] = {}
    for f, tool in INFRA_FILES.items():
        if (d / f).exists():
            infra[f] = tool
    for pattern, tool in INFRA_GLOBS.items():
        for match in glob.glob(str(d / pattern)):
            infra[os.path.relpath(match, d)] = tool
    return {
        "languages": sorted({lang for f, lang in PACKAGE_FILES.items() if (d / f).exists()}),
        "npm": _npm_project(d),
        "python": _python_project(d),
        "infra_files": infra,
        "env_var_names": _env_var_names(d),
    }


def scan_project(cwd: Path) -> dict:
    parts = []
    for d in _subproject_dirs(cwd):
        info = _scan_dir(d)
        if d != cwd and not (info["languages"] or info["infra_files"]):
            continue
        parts.append({"path": os.path.relpath(d, cwd), **info})
    env_names = sorted({n for p in parts for n in p["env_var_names"]})
    # Service hints from env var prefixes (STRIPE_SECRET_KEY → stripe). Generic on purpose:
    # Claude interprets unfamiliar prefixes itself.
    prefixes = sorted({n.split("_")[0].lower() for n in env_names
                       if n.split("_")[0] not in {"NEXT", "VITE", "PUBLIC", "NODE", "APP", "API", "DATABASE", "BASE", "ENV"}})
    return {
        "path": str(cwd),
        "languages": sorted({lang for p in parts for lang in p["languages"]}),
        "parts": parts,  # root first, then each subproject (backend/, web/, ...)
        "env_service_prefixes": prefixes,
        "is_git_repo": (cwd / ".git").exists(),
    }


# ---------------------------------------------------------------------------
# Claude setup: MCP servers, plugins, skills
# ---------------------------------------------------------------------------

def scan_claude(cwd: Path) -> dict:
    mcps: dict[str, dict] = {}

    def add_mcp(name: str, scope: str, source: str, cfg: dict | None = None) -> None:
        entry = mcps.setdefault(name, {"name": name, "scopes": [], "sources": []})
        if scope not in entry["scopes"]:
            entry["scopes"].append(scope)
        entry["sources"].append(source)
        if cfg:
            entry["transport"] = cfg.get("type") or ("stdio" if cfg.get("command") else "http")
            if cfg.get("command"):
                entry["command"] = " ".join([cfg["command"], *map(str, cfg.get("args", []))])[:160]
            if cfg.get("url"):
                entry["url"] = cfg["url"]

    claude_json = _read_json(HOME / ".claude.json")
    for name, cfg in claude_json.get("mcpServers", {}).items():
        add_mcp(name, "user", "~/.claude.json", cfg)
    for name, cfg in claude_json.get("projects", {}).get(str(cwd), {}).get("mcpServers", {}).items():
        add_mcp(name, "local", "~/.claude.json projects[cwd]", cfg)
    for name, cfg in _read_json(cwd / ".mcp.json").get("mcpServers", {}).items():
        add_mcp(name, "project", ".mcp.json", cfg)
    for name, cfg in _read_json(HOME / ".claude" / "settings.json").get("mcpServers", {}).items():
        add_mcp(name, "user", "~/.claude/settings.json", cfg)
    desktop = HOME / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    for name, cfg in _read_json(desktop).get("mcpServers", {}).items():
        add_mcp(name, "desktop", "claude_desktop_config.json", cfg)

    # Plugins (+ the skills and MCP servers they bring)
    plugins = []
    skills: dict[str, dict] = {}
    installed = _read_json(HOME / ".claude" / "plugins" / "installed_plugins.json").get("plugins", {})
    enabled = _read_json(HOME / ".claude" / "settings.json").get("enabledPlugins", {})
    for plugin_id, installs in installed.items():
        for inst in installs if isinstance(installs, list) else [installs]:
            path = Path(inst.get("installPath", ""))
            short = plugin_id.split("@")[0]
            p_skills = sorted(p.parent.name for p in path.glob("skills/*/SKILL.md"))
            p_mcps = list(_read_json(path / ".mcp.json").get("mcpServers", {}))
            plugins.append({
                "id": plugin_id, "version": inst.get("version"), "scope": inst.get("scope"),
                "enabled": enabled.get(plugin_id, True), "installed_at": inst.get("installedAt"),
                "skills": p_skills, "mcp_servers": p_mcps,
            })
            for s in p_skills:
                skills[f"{short}:{s}"] = {
                    "name": f"{short}:{s}", "scope": "plugin", "plugin": plugin_id,
                    "description": _frontmatter_description(path / "skills" / s / "SKILL.md"),
                }
            for m in p_mcps:
                add_mcp(m, "plugin", plugin_id)

    # skills-lock.json is written by Vercel's `npx skills add` — it tells us where each came from.
    lock = {**_read_json(HOME / ".agents" / "skills-lock.json").get("skills", {}),
            **_read_json(cwd / "skills-lock.json").get("skills", {})}
    for base, scope in ((cwd / ".claude" / "skills", "project"), (cwd / ".agents" / "skills", "project"),
                        (HOME / ".claude" / "skills", "user"), (HOME / ".agents" / "skills", "user")):
        for skill_md in base.glob("*/SKILL.md"):
            name = skill_md.parent.name
            if name not in skills:
                skills[name] = {"name": name, "scope": scope, "path": str(skill_md.parent),
                                "description": _frontmatter_description(skill_md),
                                **({"installed_from": lock[name].get("source")} if name in lock else {})}

    return {"mcp_servers": list(mcps.values()), "plugins": plugins, "skills": list(skills.values())}


# ---------------------------------------------------------------------------
# Usage — mined from transcripts
# ---------------------------------------------------------------------------

def scan_usage(days: int, project_root: Path | None = None) -> dict:
    root = HOME / ".claude" / "projects"
    cutoff = time.time() - days * 86400
    mcp_use: dict[str, dict] = {}
    skill_use: dict[str, dict] = {}
    p_mcp_use: dict[str, dict] = {}
    p_skill_use: dict[str, dict] = {}
    sessions = 0
    p_sessions: set[str] = set()
    # Worktrees of this project live elsewhere sometimes (".../Donna--claude-worktrees-x"
    # transcripts carry cwd ".../Donna/.claude/worktrees/x") — a prefix match covers both.
    proot = str(project_root) if project_root else None

    def in_project(cwd: str) -> bool:
        return bool(proot) and (cwd == proot or cwd.startswith(proot + os.sep))

    def bump(table: dict, key: str, ts: str, project: str, sample: str | None = None) -> None:
        e = table.setdefault(key, {"calls": 0, "last_used": "", "projects": set(), "sample_tools": set()})
        e["calls"] += 1
        if ts > e["last_used"]:
            e["last_used"] = ts
        if project:
            e["projects"].add(project)
        if sample and len(e["sample_tools"]) < 4:
            e["sample_tools"].add(sample)

    for f in root.glob("*/*.jsonl"):
        try:
            if f.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        sessions += 1
        try:
            fh = f.open(errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                # Cheap substring gate before paying for json.loads on a 300MB corpus.
                has_tool = '"tool_use"' in line and ('"mcp__' in line or '"Skill"' in line)
                has_cmd = "<command-name>" in line
                if not (has_tool or has_cmd):
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = d.get("timestamp", "")
                project = d.get("cwd", "")
                here = in_project(project)
                if here:
                    p_sessions.add(f.name)
                content = (d.get("message") or {}).get("content")
                if isinstance(content, list) and d.get("type") == "assistant":
                    for b in content:
                        if not isinstance(b, dict) or b.get("type") != "tool_use":
                            continue
                        name = b.get("name", "")
                        if name.startswith("mcp__"):
                            server, _, tool = name[5:].partition("__")
                            bump(mcp_use, server, ts, project, tool)
                            if here:
                                bump(p_mcp_use, server, ts, project, tool)
                        elif name == "Skill":
                            skill = (b.get("input") or {}).get("skill", "")
                            if skill:
                                bump(skill_use, skill.lstrip("/"), ts, project)
                                if here:
                                    bump(p_skill_use, skill.lstrip("/"), ts, project)
                elif has_cmd and d.get("type") == "user":
                    text = content if isinstance(content, str) else json.dumps(content)
                    for cmd in re.findall(r"<command-name>/?([\w:.-]+)</command-name>", text):
                        if cmd not in BUILTIN_COMMANDS:
                            bump(skill_use, cmd, ts, project)
                            if here:
                                bump(p_skill_use, cmd, ts, project)

    def finalize(table: dict) -> dict:
        return {k: {"calls": v["calls"], "last_used": v["last_used"][:10], "projects": len(v["projects"]),
                    **({"sample_tools": sorted(v["sample_tools"])} if v["sample_tools"] else {})}
                for k, v in sorted(table.items(), key=lambda kv: -kv[1]["calls"])}

    return {"window_days": days, "sessions_scanned": sessions,
            "mcp_servers": finalize(mcp_use), "skills": finalize(skill_use),
            "this_project": {"sessions_with_tool_use": len(p_sessions),
                             "mcp_servers": finalize(p_mcp_use), "skills": finalize(p_skill_use)}}


def _no_calls(claude: dict, table: dict) -> tuple[list[str], list[str]]:
    used_mcp = set(table["mcp_servers"])
    used_skills = {s.split(":")[-1] for s in table["skills"]} | set(table["skills"])
    mcps = [m["name"] for m in claude["mcp_servers"]
            if not m["name"].startswith(HOST_BUILTIN_PREFIXES)
            and not any(u == m["name"] or u.endswith("_" + m["name"]) for u in used_mcp)]
    skills = [s["name"] for s in claude["skills"]
              if s["name"] not in used_skills and s["name"].split(":")[-1] not in used_skills]
    return mcps, skills


def _unused(claude: dict, usage: dict) -> dict:
    mcps, skills = _no_calls(claude, usage)
    p_mcps, p_skills = _no_calls(claude, usage["this_project"])
    project_skills = {s["name"] for s in claude["skills"] if s["scope"] == "project"}
    # Remote connectors (claude.ai) show up in transcripts only as opaque ids; list them so
    # Claude can identify them from their tool names.
    remote = {k: v for k, v in usage["mcp_servers"].items()
              if re.fullmatch(r"[0-9a-f-]{36}", k)}
    return {
        # Not called anywhere in the window — true surplus candidates.
        "mcp_servers_no_calls": mcps,
        "skills_no_calls": skills,
        # Used elsewhere but never in this project — "not for this project", not "useless".
        "mcp_servers_not_used_here": [m for m in p_mcps if m not in mcps],
        # Skills installed IN this project that this project never calls.
        "project_skills_never_used_here": sorted(n for n in project_skills if n in p_skills),
        "remote_connectors_seen": remote,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Gold Digger inventory")
    ap.add_argument("--cwd", default=os.getcwd())
    ap.add_argument("--days", type=int, default=60, help="Usage window in days")
    ap.add_argument("--no-usage", action="store_true", help="Skip transcript mining")
    args = ap.parse_args()
    cwd = Path(args.cwd).resolve()

    claude = scan_claude(cwd)
    usage = (scan_usage(args.days, cwd) if not args.no_usage else
             {"window_days": 0, "mcp_servers": {}, "skills": {}, "this_project": {"mcp_servers": {}, "skills": {}}})
    out = {
        "generated_at": _now().isoformat(timespec="seconds"),
        "project": scan_project(cwd),
        "claude": claude,
        "usage": usage,
        "no_recent_use": _unused(claude, usage) if not args.no_usage else None,
    }
    json.dump(out, sys.stdout, indent=1, default=list)
    print()


if __name__ == "__main__":
    main()
