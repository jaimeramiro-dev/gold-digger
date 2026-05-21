#!/usr/bin/env python3
"""Gold Digger Safety Scanner — static red-flag detection for skills, MCPs, and tools.

NEVER executes the scanned code. Reads files statically and flags suspicious patterns.
Language-agnostic regex heuristics + Python AST analysis where applicable.

Verdict: safe / suspicious / dangerous — with exact triggering lines.
Disclaimer: first-pass red-flag detection, NOT a security guarantee.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

# Each pattern: (category, severity, regex, description)
PATTERNS: list[tuple[str, str, str, str]] = [
    # Remote code execution
    ("remote_exec", "high", r"curl\s+[^\|]*\|\s*(ba)?sh", "curl pipe to shell"),
    ("remote_exec", "high", r"wget\s+[^\|]*\|\s*(ba)?sh", "wget pipe to shell"),
    ("remote_exec", "high", r"\beval\s*\(\s*(fetch|require|import|__import__)", "eval of dynamic import"),
    ("remote_exec", "medium", r"\bos\.system\s*\(", "os.system call"),
    ("remote_exec", "medium", r"subprocess\.\w+\(.*shell\s*=\s*True", "subprocess with shell=True"),
    ("remote_exec", "medium", r"\bexec\s*\(\s*(?!\"\"\")", "exec() call"),
    ("remote_exec", "medium", r"\bFunction\s*\(", "JavaScript Function constructor"),

    # Obfuscation
    ("obfuscation", "high", r"base64\.\s*b64decode.*(?:exec|eval|os\.|subprocess)", "base64 decode + execute"),
    ("obfuscation", "medium", r"\\x[0-9a-fA-F]{2}(?:\\x[0-9a-fA-F]{2}){20,}", "long hex-encoded string"),
    ("obfuscation", "medium", r"\batob\s*\(.*(?:eval|Function)", "atob + eval/Function"),
    ("obfuscation", "medium", r"String\.fromCharCode\s*\((?:\d+\s*,\s*){10,}", "long fromCharCode sequence"),

    # Credential access
    ("credential_access", "high", r"(?:open|read|cat|type)\s*.*~/\.ssh/", "reading SSH keys"),
    ("credential_access", "high", r"(?:open|read|cat|type)\s*.*id_rsa", "reading SSH private key"),
    ("credential_access", "medium", r"(?:open|read|cat)\s*.*\.env\b", "reading .env file"),
    ("credential_access", "medium", r"os\.environ\s*\[.*(?:SECRET|TOKEN|KEY|PASSWORD|CREDENTIAL)", "reading secret env vars"),
    ("credential_access", "medium", r"keychain|credential.?store|password.?store", "accessing credential store"),
    ("credential_access", "medium", r"(?:open|read).*(?:cookies|login.?data|\.mozilla|\.chrome)", "reading browser data"),

    # Exfiltration
    ("exfiltration", "high", r"(?:requests\.post|urllib.*POST|fetch.*POST|http\.request.*POST)\s*\(\s*['\"]https?://\d+\.\d+\.\d+\.\d+", "HTTP POST to IP address"),
    ("exfiltration", "medium", r"(?:requests\.post|urllib.*POST)\s*\(.*(?:token|secret|key|password|credential)", "POSTing sensitive data"),
    ("exfiltration", "medium", r"WebSocket\s*\(\s*['\"]ws://(?!\blocalhost\b)", "WebSocket to external host"),

    # Destructive operations
    ("destructive", "high", r"rm\s+-rf\s+[/~]", "rm -rf on broad path"),
    ("destructive", "high", r"shutil\.rmtree\s*\(\s*['\"](?:/|~|os\.path\.expanduser)", "rmtree on broad path"),
    ("destructive", "medium", r"DROP\s+(?:TABLE|DATABASE)", "SQL DROP"),
    ("destructive", "medium", r"\bFORMAT\s+[A-Z]:", "disk format command"),

    # Crypto mining
    ("crypto_mining", "high", r"stratum\+tcp://", "mining pool connection"),
    ("crypto_mining", "high", r"\bxmrig\b", "XMRig miner reference"),
    ("crypto_mining", "high", r"\bcoinhive\b", "CoinHive reference"),
    ("crypto_mining", "high", r"\bcryptonight\b", "CryptoNight algorithm reference"),

    # Reverse shell
    ("reverse_shell", "high", r"/dev/tcp/", "reverse shell via /dev/tcp"),
    ("reverse_shell", "high", r"\bnc\s+-[^l]*e\s+/bin/(?:ba)?sh", "netcat reverse shell"),
    ("reverse_shell", "high", r"bash\s+-i\s+>&\s+/dev/tcp/", "bash interactive reverse shell"),
    ("reverse_shell", "high", r"python.*socket.*connect.*(?:os\.dup2|subprocess)", "Python reverse shell"),
]

# File extensions to scan
SCANNABLE_EXTENSIONS = {
    ".py", ".js", ".ts", ".mjs", ".cjs", ".jsx", ".tsx",
    ".sh", ".bash", ".zsh", ".fish",
    ".rb", ".go", ".rs", ".lua",
    ".md", ".yaml", ".yml", ".json", ".toml",
}

# Files to skip
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".cache",
}

# ---------------------------------------------------------------------------
# Scanning logic
# ---------------------------------------------------------------------------

def scan_file(filepath: str) -> list[dict]:
    """Scan a single file for red-flag patterns."""
    flags = []
    try:
        with open(filepath, "r", errors="replace") as f:
            lines = f.readlines()
    except (IOError, OSError):
        return []

    for line_num, line in enumerate(lines, 1):
        for category, severity, pattern, description in PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                flags.append({
                    "severity": severity,
                    "category": category,
                    "file": filepath,
                    "line": line_num,
                    "pattern": description,
                    "context": line.strip()[:200],
                })
    return flags


def scan_python_ast(filepath: str) -> list[dict]:
    """Deeper analysis for Python files using AST."""
    flags = []
    try:
        with open(filepath) as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)
    except (IOError, SyntaxError):
        return []

    for node in ast.walk(tree):
        # Check for suspicious imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ("ctypes", "mmap"):
                    flags.append({
                        "severity": "low",
                        "category": "suspicious_import",
                        "file": filepath,
                        "line": node.lineno,
                        "pattern": f"import {alias.name}",
                        "context": f"Imports {alias.name} — unusual for a skill/MCP",
                    })
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("ctypes"):
                flags.append({
                    "severity": "low",
                    "category": "suspicious_import",
                    "file": filepath,
                    "line": node.lineno,
                    "pattern": f"from {node.module} import ...",
                    "context": f"Imports from {node.module}",
                })

    return flags


def check_skill_permissions(repo_path: str) -> list[dict]:
    """Check SKILL.md allowed-tools for overly broad permissions."""
    flags = []
    skill_md = os.path.join(repo_path, "SKILL.md")
    if not os.path.exists(skill_md):
        return []

    try:
        with open(skill_md) as f:
            content = f.read(3000)
    except IOError:
        return []

    # Extract frontmatter
    if content.startswith("---"):
        end = content.find("---", 3)
        if end > 0:
            frontmatter = content[3:end]
            # Check for Bash + Write without other tools (suspicious combo)
            has_bash = "Bash" in frontmatter
            has_write = "Write" in frontmatter
            # Read the description
            desc_match = re.search(r"description:\s*[>|]?\s*(.+?)(?:\n\w|\n---)", frontmatter, re.DOTALL)
            description = desc_match.group(1).strip() if desc_match else ""

            if has_bash and has_write:
                flags.append({
                    "severity": "low",
                    "category": "broad_permissions",
                    "file": "SKILL.md",
                    "line": 1,
                    "pattern": "Requests Bash + Write allowed-tools",
                    "context": f"Description: {description[:100]}",
                })

    return flags


def check_provenance(repo_url: str) -> dict:
    """Check GitHub repo provenance: stars, age, author history."""
    provenance = {"stars": None, "repo_age_days": None, "author_repos": None}

    # Extract owner/repo from URL
    match = re.search(r"github\.com/([^/]+)/([^/\s?#]+)", repo_url)
    if not match:
        return provenance

    owner, repo = match.group(1), match.group(2).rstrip(".git")
    api_url = f"https://api.github.com/repos/{owner}/{repo}"

    headers = {"User-Agent": "gold-digger-safety/1.0", "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        provenance["stars"] = data.get("stargazers_count")
        created = data.get("created_at", "")
        if created:
            from datetime import datetime, timezone
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            provenance["repo_age_days"] = (datetime.now(timezone.utc) - created_dt).days
    except Exception:
        pass

    # Check author's other repos
    try:
        author_url = f"https://api.github.com/users/{owner}"
        req = urllib.request.Request(author_url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            user_data = json.loads(resp.read())
        provenance["author_repos"] = user_data.get("public_repos")
    except Exception:
        pass

    return provenance


def scan_repo(repo_path: str) -> list[dict]:
    """Scan all files in a repo directory."""
    all_flags = []

    for root, dirs, files in os.walk(repo_path):
        # Skip irrelevant directories
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        for filename in files:
            # Never scan ourselves — our pattern definitions would self-trigger
            if filename == "safety_scan.py":
                continue
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SCANNABLE_EXTENSIONS:
                continue

            filepath = os.path.join(root, filename)
            # Make path relative for cleaner output
            rel_path = os.path.relpath(filepath, repo_path)

            # Regex scan (all languages)
            file_flags = scan_file(filepath)
            for flag in file_flags:
                flag["file"] = rel_path
            all_flags.extend(file_flags)

            # AST scan (Python only)
            if ext == ".py":
                ast_flags = scan_python_ast(filepath)
                for flag in ast_flags:
                    flag["file"] = rel_path
                all_flags.extend(ast_flags)

    # Permission check
    all_flags.extend(check_skill_permissions(repo_path))

    return all_flags


def clone_repo(repo_url: str) -> str | None:
    """Shallow-clone a GitHub repo to a temp directory."""
    tmpdir = tempfile.mkdtemp(prefix="gd-scan-")
    try:
        subprocess.run(
            ["git", "clone", "--depth=1", "--quiet", repo_url, tmpdir],
            check=True, timeout=30, capture_output=True,
        )
        return tmpdir
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"[safety] Cannot clone {repo_url}: {e}", file=sys.stderr)
        return None


def determine_verdict(flags: list[dict], provenance: dict) -> str:
    """Determine the overall verdict based on flags and provenance."""
    severities = [f["severity"] for f in flags]

    if "high" in severities:
        return "dangerous"

    if "medium" in severities:
        # Check if provenance is concerning too
        age = provenance.get("repo_age_days")
        stars = provenance.get("stars")
        author_repos = provenance.get("author_repos")
        if age is not None and age < 30 and stars is not None and stars < 10:
            return "dangerous"  # new + low-trust + suspicious patterns
        return "suspicious"

    # Check provenance alone
    age = provenance.get("repo_age_days")
    stars = provenance.get("stars")
    author_repos = provenance.get("author_repos")
    if (age is not None and age < 30
            and stars is not None and stars < 10
            and author_repos is not None and author_repos <= 1):
        return "suspicious"  # brand new repo from unknown author

    return "safe"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Gold Digger Safety Scanner — static red-flag detection"
    )
    parser.add_argument(
        "--repo", required=True,
        help="GitHub URL or local path to scan"
    )
    parser.add_argument(
        "--depth", choices=["shallow", "deep"], default="shallow",
        help="Scan depth (deep includes AST analysis)"
    )
    args = parser.parse_args()

    repo_path = args.repo
    is_url = repo_path.startswith("http://") or repo_path.startswith("https://")
    cloned_dir = None

    if is_url:
        # Clone the repo
        cloned_dir = clone_repo(repo_path)
        if not cloned_dir:
            result = {
                "verdict": "suspicious",
                "flags": [{
                    "severity": "medium",
                    "category": "clone_failed",
                    "file": "",
                    "line": 0,
                    "pattern": "Could not clone repository",
                    "context": f"Failed to clone {repo_path}",
                }],
                "provenance": check_provenance(repo_path),
                "disclaimer": "First-pass red-flag detection, not a security guarantee.",
            }
            print(json.dumps(result, indent=2))
            return
        scan_path = cloned_dir
    else:
        scan_path = repo_path

    # Scan
    flags = scan_repo(scan_path)

    # Provenance (only for GitHub URLs)
    provenance = {}
    if is_url and "github.com" in repo_path:
        provenance = check_provenance(repo_path)

    # Verdict
    verdict = determine_verdict(flags, provenance)

    result = {
        "verdict": verdict,
        "flags": flags,
        "provenance": provenance,
        "disclaimer": "First-pass red-flag detection, not a security guarantee.",
    }

    print(json.dumps(result, indent=2))

    # Cleanup
    if cloned_dir:
        import shutil
        shutil.rmtree(cloned_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
