#!/usr/bin/env python3
"""Generates dark_mode.svg and light_mode.svg for my GitHub profile.

Stats come from the GitHub API, the git history of my repos and the
token-protected JSON on status.grafkox.de. Standard library only.
If a source fails, the last values from cache/stats.json are used.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache" / "stats.json"

USER = "grafkox"
HOMELAB_URL = os.environ.get("HOMELAB_URL", "https://status.grafkox.de/homelab.json")
HOMELAB_STALE_AFTER = 4 * 3600  # server writes every 3 h; older data is shown as offline
USER_AGENT = "grafkox-profile-card/1.0 (+https://github.com/grafkox/grafkox)"

# git matches --author against "Name <email>"; names only, no e-mail in a public repo
AUTHOR_PATTERN = r"^(Leon Herschel|GrafkoxLP|grafkox) <"  # old and new username
# Generated or vendored files never count as lines of code.
LOC_IGNORE = re.compile(
    r"(^|/)(node_modules|vendor|dist|build|target)/"
    r"|(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|composer\.lock)$"
    r"|\.min\.(js|css)$"
)
# The first commit of this fork imports the upstream source, which is not my code.
LOC_SKIP_REPOS = {"AdvancedBan-Velocity"}

WIDTH = 62  # characters per text line on the right-hand side

PROFILE = [
    ("title", "leon@grafkox"),
    ("OS", "Windows, macOS, Ubuntu Server"),
    ("Role", "IT Apprentice (FiSi) @ ID Logistics"),
    ("Location", "Hesse, Germany"),
    ("blank", ""),
    ("Languages.Programming", "JavaScript, PHP, Java, Python"),
    ("Languages.Computer", "HTML, CSS, SQL, YAML, Bash"),
    ("Languages.Real", "German, English"),
    ("blank", ""),
    ("Stack", "Docker, ZFS, nginx, Cloudflare Tunnel"),
    ("Local AI", "Ollama, Open WebUI, self-hosted agents"),
    ("Hobbies.Racing", "Le Mans Ultimate, Assetto Corsa"),
    ("Hobbies.Making", "3D printing, homelab tinkering"),
    ("section", "Homelab"),
    ("Host", "Dell PowerEdge R730"),
    ("homelab", ""),
    ("section", "Contact"),
    ("Web", "grafkox.de"),
    ("Email", "contact@grafkox.de"),
    ("section", "GitHub Stats"),
    ("github", ""),
]

THEMES = {
    "dark": dict(bg="#161b22", text="#c9d1d9", key="#ffa657", value="#a5d6ff",
                 dots="#616e7f", add="#3fb950", sub="#f85149"),
    "light": dict(bg="#f6f8fa", text="#24292f", key="#953800", value="#0a3069",
                  dots="#c2cfde", add="#1a7f37", sub="#cf222e"),
}


# --------------------------------------------------------------------------- data

def http_json(url: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Accept", "application/json")
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def graphql(token: str, query: str, variables: dict | None = None) -> dict:
    res = http_json("https://api.github.com/graphql", token,
                    {"query": query, "variables": variables or {}})
    if res.get("errors"):
        raise RuntimeError(res["errors"])
    return res["data"]


def git_stats(token: str, full_name: str, count_loc: bool) -> tuple[int, int, int]:
    """Return (commits, additions, deletions) authored by me in one repository."""
    auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    # GitHub masks the raw secret in logs, but not this base64 form, so mask it too.
    print(f"::add-mask::{auth}")
    with tempfile.TemporaryDirectory() as tmp:
        clone = subprocess.run(
            ["git", "-c", f"http.extraHeader=Authorization: Basic {auth}",
             "clone", "--quiet", "--bare", f"https://github.com/{full_name}.git", tmp],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if clone.returncode != 0:
            # Never raise CalledProcessError here: its message contains the command incl. the header.
            raise RuntimeError(f"git clone of {full_name} failed (exit {clone.returncode})")
        log = subprocess.run(
            ["git", "-C", tmp, "log", "--no-merges", "--extended-regexp", "--regexp-ignore-case",
             f"--author={AUTHOR_PATTERN}", "--numstat", "--format=tformat:@commit"],
            check=True, capture_output=True, text=True, errors="replace").stdout
    commits = adds = dels = 0
    for line in log.splitlines():
        if line == "@commit":
            commits += 1
            continue
        parts = line.split("\t")
        if not count_loc or len(parts) != 3 or parts[0] == "-":
            continue  # empty line, binary file or LOC disabled
        if LOC_IGNORE.search(parts[2]):
            continue
        adds += int(parts[0])
        dels += int(parts[1])
    return commits, adds, dels


def github_stats(token: str) -> dict:
    data = graphql(token, """
      query($login: String!) {
        user(login: $login) {
          followers { totalCount }
          repositories(ownerAffiliations: OWNER, first: 100) {
            nodes { nameWithOwner name isPrivate isFork stargazerCount isEmpty }
          }
        }
      }""", {"login": USER})["user"]
    repos = [r for r in data["repositories"]["nodes"] if not r["isEmpty"]]
    commits = adds = dels = 0
    for repo in repos:
        c, a, d = git_stats(token, repo["nameWithOwner"], repo["name"] not in LOC_SKIP_REPOS)
        commits, adds, dels = commits + c, adds + a, dels + d
    return {
        "repos": sum(1 for r in repos if not r["isPrivate"]),
        "stars": sum(r["stargazerCount"] for r in repos),
        "followers": data["followers"]["totalCount"],
        "commits": commits,
        "loc_add": adds,
        "loc_del": dels,
    }


def homelab_stats(token: str) -> dict:
    raw = http_json(HOMELAB_URL, token)
    keys = ("updated", "uptime_seconds", "containers_running", "mem_used_bytes", "mem_total_bytes")
    return {k: int(raw[k]) for k in keys}


# ------------------------------------------------------------------------- render

def fmt_uptime(seconds: int) -> str:
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    mins = rest // 60
    plural = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"
    if days:
        return f"{plural(days, 'day')}, {plural(hours, 'hour')}"
    return f"{plural(hours, 'hour')}, {plural(mins, 'min')}"


def gib(b: int) -> str:
    return f"{b / 1024 ** 3:.1f} GiB"


def kv(key: str, value: str | list) -> list:
    """One 'Key: ..... value' line as a list of (css-class, text) spans."""
    parts = value if isinstance(value, list) else [("value", value)]
    vlen = sum(len(t) for _, t in parts)
    dots = max(2, WIDTH - len(key) - 3 - vlen)
    return [("key", key), ("text", ": "), ("dots", "." * dots), ("text", " ")] + parts


def build_lines(gh: dict, lab: dict | None, now: int) -> list:
    lines = []
    for kind, value in PROFILE:
        if kind == "title":
            lines.append([("text", value + " "), ("text", "-" * (WIDTH - len(value) - 1))])
        elif kind == "blank":
            lines.append([])
        elif kind == "section":
            head = f"- {value} "
            lines.append([("text", head + "-" * (WIDTH - len(head)))])
        elif kind == "homelab":
            if lab and now - lab["updated"] <= HOMELAB_STALE_AFTER:
                lines.append(kv("Uptime", fmt_uptime(lab["uptime_seconds"])))
                lines.append(kv("Containers", f"{lab['containers_running']} running"))
                lines.append(kv("Memory", f"{gib(lab['mem_used_bytes'])} / {gib(lab['mem_total_bytes'])}"))
            else:
                seen = time.strftime("%Y-%m-%d", time.gmtime(lab["updated"])) if lab else "never"
                lines.append(kv("Status", [("sub", "offline"), ("value", f" (last seen {seen})")]))
        elif kind == "github":
            lines.append(kv("Repos", f"{gh['repos']} {{Stars: {gh['stars']}}}"))
            lines.append(kv("Commits", f"{gh['commits']:,} {{Followers: {gh['followers']}}}"))
            total = gh["loc_add"] - gh["loc_del"]
            lines.append(kv("Lines of Code", [
                ("value", f"{total:,} ( "), ("add", f"{gh['loc_add']:,}++"),
                ("value", ", "), ("sub", f"{gh['loc_del']:,}--"), ("value", " )")]))
        else:
            lines.append(kv(kind, value))
    return lines


def render(theme: str, ascii_art: list[str], lines: list) -> str:
    c = THEMES[theme]
    lh, top, left_ascii, left_text, width = 20, 30, 15, 430, 1050
    height = top + max(len(ascii_art), len(lines)) * lh + 10
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" font-family="Consolas,'
        f"'DejaVu Sans Mono',Menlo,monospace\" width=\"{width}px\" height=\"{height}px\" font-size=\"16px\">",
        "<style>",
        f".key{{fill:{c['key']}}}.value{{fill:{c['value']}}}.dots{{fill:{c['dots']}}}"
        f".add{{fill:{c['add']}}}.sub{{fill:{c['sub']}}}text,tspan{{white-space:pre}}",
        "</style>",
        f'<rect width="{width}px" height="{height}px" fill="{c["bg"]}" rx="15"/>',
        f'<text x="{left_ascii}" y="{top}" fill="{c["text"]}" xml:space="preserve">',
    ]
    for i, row in enumerate(ascii_art):
        out.append(f'<tspan x="{left_ascii}" y="{top + i * lh}">{escape(row)}</tspan>')
    out.append("</text>")
    out.append(f'<text x="{left_text}" y="{top}" fill="{c["text"]}" xml:space="preserve">')
    for i, spans in enumerate(lines):
        if not spans:
            continue
        inner = "".join(
            escape(t) if cls == "text" else f'<tspan class="{cls}">{escape(t)}</tspan>'
            for cls, t in spans)
        out.append(f'<tspan x="{left_text}" y="{top + i * lh}">{inner}</tspan>')
    out.append("</text>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- main

def main() -> int:
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    mock = "--mock" in sys.argv

    if mock:
        gh = {"repos": 6, "stars": 2, "followers": 3, "commits": 214, "loc_add": 31452, "loc_del": 6118}
        lab = {"updated": int(time.time()), "uptime_seconds": 23 * 86400 + 4 * 3600,
               "containers_running": 15, "mem_used_bytes": 19_700_000_000, "mem_total_bytes": 67_400_000_000}
    else:
        gh, lab = cache.get("github"), cache.get("homelab")
        try:
            gh = github_stats(os.environ["GH_STATS_TOKEN"])
        except Exception as exc:  # keep the last good values
            print(f"::warning::GitHub stats failed: {exc}")
        try:
            lab = homelab_stats(os.environ["HOMELAB_TOKEN"])
        except Exception as exc:
            print(f"::warning::Homelab stats failed: {exc}")
        if gh is None:
            print("::error::No GitHub stats and no cache")
            return 1
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps({"github": gh, "homelab": lab}, indent=2) + "\n")

    ascii_art = (ROOT / "ascii.txt").read_text().rstrip("\n").split("\n")
    lines = build_lines(gh, lab, int(time.time()))
    for theme in THEMES:
        (ROOT / f"{theme}_mode.svg").write_text(render(theme, ascii_art, lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
