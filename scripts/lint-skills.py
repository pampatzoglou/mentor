#!/usr/bin/env python3
"""Lint skill frontmatter, sizes and links for every plugin in the marketplace.

Checks, per SKILL.md:
  - name matches the directory and is a valid skill name
  - description is present, at most 1024 characters, and has a when-clause
  - license is present; no top-level keys outside the Agent Skills spec
  - metadata.requires names skills that exist
  - body is under 500 lines
Per skill directory:
  - reference files over 100 lines open with a '## Contents' section
  - relative markdown links resolve
  - no dotfiles (templates belong in assets/ under plain names)
Per plugin:
  - LICENSE and NOTICE are present and match the repository root

Stdlib only, so it runs anywhere python3 does. Exits 1 on any failure.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MAX_DESCRIPTION = 1024
MAX_BODY_LINES = 500
TOC_THRESHOLD = 100
TOC_WINDOW = 15
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
WHEN_RE = re.compile(r"\b(use (this skill )?(when|whenever|for)|triggers? (on|include))\b", re.I)
LINK_RE = re.compile(r"\]\(([^)#\s]+)(#[^)]*)?\)")
ALLOWED_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}


def parse_frontmatter(text):
    """Parse the flat subset of YAML that SKILL.md frontmatter uses."""
    if not text.startswith("---\n"):
        raise ValueError("missing frontmatter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("unterminated frontmatter")
    fields, parent = {}, None
    for line in text[4:end].split("\n"):
        if not line.strip():
            continue
        nested = line.startswith("  ")
        key, sep, value = line.strip().partition(":")
        if not sep:
            raise ValueError(f"unparseable frontmatter line: {line!r}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1].replace("''", "'") if value[0] == "'" else value[1:-1]
        if nested:
            if parent is None:
                raise ValueError(f"indented line without a parent key: {line!r}")
            fields[parent][key] = value
        elif value == "":
            fields[key], parent = {}, key
        else:
            fields[key], parent = value, None
    return fields, text[end + 5:]


def in_fence_free_lines(text):
    fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if not fence:
            yield line


def lint_skill(skill_dir, known, errors):
    rel = skill_dir.relative_to(ROOT)
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        errors.append(f"{rel}: missing SKILL.md")
        return
    try:
        fm, body = parse_frontmatter(skill_md.read_text())
    except ValueError as exc:
        errors.append(f"{rel}/SKILL.md: {exc}")
        return

    name = fm.get("name", "")
    if name != skill_dir.name:
        errors.append(f"{rel}/SKILL.md: name {name!r} does not match directory {skill_dir.name!r}")
    if not NAME_RE.match(name) or len(name) > 64:
        errors.append(f"{rel}/SKILL.md: invalid name {name!r}")

    desc = fm.get("description", "")
    if not desc:
        errors.append(f"{rel}/SKILL.md: missing description")
    elif len(desc) > MAX_DESCRIPTION:
        errors.append(f"{rel}/SKILL.md: description is {len(desc)} chars (max {MAX_DESCRIPTION})")
    if desc and not WHEN_RE.search(desc):
        errors.append(f"{rel}/SKILL.md: description has no when-clause ('Use when ...')")

    if not fm.get("license"):
        errors.append(f"{rel}/SKILL.md: missing license")
    for key in sorted(set(fm) - ALLOWED_KEYS):
        errors.append(f"{rel}/SKILL.md: unknown top-level key {key!r} (put extensions under metadata:)")

    metadata = fm.get("metadata", {})
    if not isinstance(metadata, dict):
        errors.append(f"{rel}/SKILL.md: metadata must be a mapping")
        metadata = {}
    for dep in metadata.get("requires", "").split():
        if dep not in known:
            errors.append(f"{rel}/SKILL.md: requires unknown skill {dep!r}")

    body_lines = body.count("\n")
    if body_lines >= MAX_BODY_LINES:
        errors.append(f"{rel}/SKILL.md: body is {body_lines} lines (max {MAX_BODY_LINES - 1})")

    for path in sorted(skill_dir.rglob("*")):
        prel = path.relative_to(ROOT)
        if path.name.startswith("."):
            errors.append(f"{prel}: dotfile in a skill directory; move it to assets/ without the dot")
            continue
        if path.suffix != ".md" or not path.is_file():
            continue
        text = path.read_text()
        if path.name != "SKILL.md" and text.count("\n") > TOC_THRESHOLD:
            head = text.split("\n")[:TOC_WINDOW]
            if "## Contents" not in head:
                errors.append(f"{prel}: over {TOC_THRESHOLD} lines without a '## Contents' section")
        for line in in_fence_free_lines(text):
            for target, _ in LINK_RE.findall(line):
                if re.match(r"^[a-z]+:", target):
                    continue
                if not (path.parent / target).exists():
                    errors.append(f"{prel}: broken link {target!r}")


def lint_plugin(plugin_dir, errors):
    rel = plugin_dir.relative_to(ROOT)
    for legal in ("LICENSE", "NOTICE"):
        src, dst = ROOT / legal, plugin_dir / legal
        if not dst.is_file():
            errors.append(f"{rel}: missing {legal} (only the plugin directory ships on install)")
        elif src.is_file() and src.read_bytes() != dst.read_bytes():
            errors.append(f"{rel}/{legal}: differs from the repository root {legal}")

    skills_dir = plugin_dir / "skills"
    if not skills_dir.is_dir():
        return
    # Dot-directories hold local, gitignored tool state (e.g. .claude/settings.local.json).
    skill_dirs = sorted(p for p in skills_dir.iterdir() if p.is_dir() and not p.name.startswith("."))
    known = {p.name for p in skill_dirs}
    for skill_dir in skill_dirs:
        lint_skill(skill_dir, known, errors)


def main():
    marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    errors = []
    for plugin in marketplace["plugins"]:
        lint_plugin((ROOT / plugin["source"]).resolve(), errors)
    for err in errors:
        print(f"error: {err}", file=sys.stderr)
    if errors:
        print(f"{len(errors)} error(s)", file=sys.stderr)
        return 1
    print(f"ok: {len(marketplace['plugins'])} plugins")
    return 0


if __name__ == "__main__":
    sys.exit(main())
