---
name: git
description: 'Git workflow helper — crafts Conventional Commit messages and PR overview descriptions. For commits: analyses staged diff, picks the right type/scope, presents a pre-filled git commit command for the user to confirm. For PRs: writes a concise overview description (not a changelog) from the branch diff.'
---

# Git Helper

Two modes: **commit** (default) and **pr**. Both start by reading the actual diff — never guess from filenames alone.

---

## Mode 1: Commit

### Step 1 — Understand the state

```bash
git status
git diff --staged
```

If nothing is staged, also run `git diff` to see unstaged changes, then:
- List the changed files grouped by concern
- Ask whether to stage everything or split into multiple commits
- If splitting: propose the groupings, stage the first group, then loop

### Step 2 — Analyse the diff

Read the staged diff and answer:
- **What type of change is this?** (see type table below)
- **What is the scope?** The component, module, or area affected — use the directory name or logical grouping, not a filename
- **What did it actually do?** One sentence, imperative mood, present tense — describe the outcome, not the mechanism
- **Is a body needed?** Only if the why is non-obvious or there's a constraint worth recording

### Step 3 — Draft the message

Follow the Conventional Commits spec:

```
<type>(<scope>): <subject>

[optional body — the WHY, not the WHAT]

[optional footer — BREAKING CHANGE: ..., Closes #N]
```

**Rules for the subject line:**
- Imperative mood: "add", "fix", "remove" — not "added", "fixes", "removes"
- No capital first letter, no period at the end
- 72 characters max
- Describes the result, not the method ("remove redundant skill descriptions" not "edit SKILL.md files")

**Type table:**

| Type | Use when |
|------|----------|
| `feat` | New capability the user can use |
| `fix` | Corrects a bug or broken behaviour |
| `docs` | Documentation only — no code change |
| `refactor` | Code restructure with no behaviour change |
| `style` | Formatting, whitespace, naming — no logic change |
| `chore` | Tooling, dependencies, config — not user-facing |
| `ci` | CI/CD workflow changes |
| `perf` | Performance improvement |
| `test` | Adding or updating tests |
| `revert` | Reverting a previous commit |

**Breaking changes:** append `!` after the type: `feat!:` or `fix(api)!:`. Add `BREAKING CHANGE: <explanation>` in the footer.

**Scope guidance:**
- Use the top-level directory or logical area: `modules`, `skills`, `docs`, `taskfile`, `flake`, `ci`
- Omit scope when the change is genuinely cross-cutting
- Never use a filename as the scope

### Step 4 — Present and confirm

Show the exact command the user will run:

```
git commit -m "<subject>" -m "<body if needed>"
```

Or for multi-line:

```
git commit -m "$(cat <<'EOF'
feat(skills): add git commit and PR helper skill

Covers conventional commit message drafting, staging assistance,
and PR overview descriptions in a single skill.
EOF
)"
```

Then ask: **"Run this commit? (yes / edit message)"**

- If yes: run it
- If edit: show the message in an editable block, re-confirm, then run

### Step 5 — Multiple commits

If the original changes were split into groups:
- After each commit, stage the next group and loop back to Step 2
- At the end, summarise all commits made

---

## Mode 2: PR

Triggered when the user asks for a PR description, PR overview, or runs `/git pr`.

### Step 1 — Read the branch diff

```bash
git log main..HEAD --oneline
git diff main..HEAD --stat
git diff main..HEAD
```

If the base branch is not `main`, infer it from context or ask.

### Step 2 — Write the overview

The PR description is a **narrative overview**, not a commit log. Structure:

```markdown
## What

One paragraph. What does this PR change or add at a high level?
Write as if explaining to a reviewer who hasn't seen the code.
Do not list every file changed.

## Why

One paragraph. What problem does this solve, or what goal does it serve?
If it's a refactor, explain the before/after improvement.
If it's a new feature, explain the need.

## Notable changes

A short bulleted list (3–6 items max) of changes that reviewers should
pay close attention to — non-obvious decisions, potential risk areas,
or things that changed in a surprising way.
Omit if there's nothing worth calling out.
```

**Do not include:**
- A commit-by-commit breakdown
- A changelog (`## v1.2.3`)
- A list of every file modified
- Boilerplate like "Please review this PR"

**Do include on request only:**
- Breaking changes section
- Migration guide
- Changelog entry

### Step 3 — Present

Show the description as a markdown block. Ask: **"Use this description? (yes / edit)"**

If the user asks for a changelog instead, switch to a `## vX.Y.Z — YYYY-MM-DD` format listing user-facing changes grouped by type.

---

## Tips

- If `git diff --staged` is empty and `git diff` is also empty, there is nothing to commit — say so and stop.
- If the diff is very large (>500 lines), summarise by directory/module rather than reading every line.
- Never invent context not visible in the diff. If the why is unclear, leave the body blank and note that the user may want to add it.
- For fixup commits or WIP commits during active development, suggest `git commit --fixup` or `--amend` when appropriate.
