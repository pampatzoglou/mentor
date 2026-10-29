---
name: tidy
description: Hunt for mechanical inconsistencies — missing separators, empty template variables, trailing whitespace, inconsistent quoting, mixed indentation, and similar style drift across Helm, Terraform, YAML, Go, and Python.
---

# Tidy

Scan the target files or directories for mechanical inconsistencies that don't affect logic but signal neglect or cause subtle bugs. Report every finding with file path and line number. Fix only when explicitly asked.

## Process

1. Identify the file types in scope (Helm templates, YAML, Terraform, Go, Python, general config)
2. Run each checklist below for matching types
3. Group findings by file, ordered by line number
4. Report a summary count per category at the end

---

## Helm Templates

### Separators and structure
- [ ] Every template file starts with `---`
- [ ] Multiple documents in a single file are separated by `---`
- [ ] No `---` at the end of a file (trailing separator)
- [ ] No consecutive blank lines (more than one empty line between blocks)

### Empty and always-null variables
- [ ] No `{{ .Values.x }}` references where `x` is not defined in `values.yaml`
- [ ] No values that are always empty string `""` or `null` with no override path
- [ ] No `{{ if .Values.x }}` guards around blocks where `x` has no plausible non-empty value
- [ ] No template variables assigned but never rendered

### Hardcoded values

Templating hygiene only — a literal in a template that should have been a value. Whether the
*value itself* is acceptable is the `kubernetes` skill's call (`:latest` is blocker-tier there);
report the hardcoding, don't re-grade the severity.

- [ ] No image tag literal in a template — it belongs in `values.yaml` as `image.tag`
- [ ] No hardcoded namespace strings that should come from `.Release.Namespace`
- [ ] No hardcoded replica counts that should be configurable values

### Quoting consistency
- [ ] String values in `values.yaml` use consistent quote style throughout the file
- [ ] Template string outputs wrapped in quotes where the value could contain colons or special YAML characters

### Indentation
- [ ] All templates use 2-space indentation consistently
- [ ] `indent` / `nindent` used correctly — no manual space padding with repeated spaces

---

## YAML (general)

- [ ] No trailing whitespace on any line
- [ ] File ends with exactly one newline (no missing, no double)
- [ ] No mixed indentation (tabs mixed with spaces)
- [ ] No duplicate keys at the same level
- [ ] Boolean values consistent — pick one style (`true`/`false`) and don't mix with `yes`/`no`/`on`/`off`
- [ ] No lines exceeding 120 characters (flag, don't auto-wrap)
- [ ] Multiline strings use `|` or `>` consistently; no escaped `\n` in plain strings

---

## Terraform

### Naming consistency
- [ ] All variables, locals, and outputs use `snake_case`
- [ ] Resource names follow `<type>_<descriptor>` pattern consistently within the file
- [ ] No single-letter or cryptic variable names

### Missing metadata
- [ ] Every `variable` block has a `description`
- [ ] Every `output` block has a `description`
- [ ] Every resource that supports tags has a `tags` argument (the `tagging` skill owns *which* keys — flag the absence, not the contents)

### Structural consistency
- [ ] Argument order within resource blocks is consistent (required args first, optional after)
- [ ] No inline `lifecycle` blocks mixed with separate `lifecycle` blocks in the same module
- [ ] `terraform.tfvars` keys match declared variable names exactly (no orphaned keys)

### Whitespace
- [ ] No trailing whitespace
- [ ] Consistent blank line between top-level blocks (exactly one)
- [ ] File ends with a single newline

---

## Go

- [ ] No unused imports (flag — `goimports` can fix)
- [ ] Error variables named `err` consistently, not `e`, `er`, `error`
- [ ] No `_ = err` suppression of errors that should be handled
- [ ] Exported identifiers have doc comments
- [ ] No `fmt.Println` / `fmt.Printf` left in non-main packages (debug output)
- [ ] No commented-out `log.` or `fmt.` lines
- [ ] Constants grouped in `const ( ... )` blocks, not scattered as single declarations

---

## Python

- [ ] Imports grouped: stdlib → third-party → local, separated by blank lines
- [ ] No mixed single and double quotes within the same file (pick one style)
- [ ] No bare `except:` — always catch a specific exception type
- [ ] No `print()` statements outside of CLI entry points
- [ ] f-strings used instead of `%` or `.format()` for new code
- [ ] No mutable default arguments (`def f(x=[])`)

---

## General (all file types)

- [ ] No CRLF line endings in a repo that uses LF
- [ ] No BOM (byte-order mark) at file start
- [ ] No debug-only config values committed (`debug: true`, `log_level: trace`, etc.)

## Not this skill's job

`tidy` fixes formatting — whitespace, quoting, indentation, separators. **Removal is `prune`'s.**
Two skills reporting one finding is how a repo gets a style fix and a deletion proposal for the
same lines, and in a `housekeeping` sweep `tidy` runs first and auto-fixes, so it would delete
content `prune` is required to only flag.

Leave these to `prune` and don't report them here:

- Commented-out code blocks
- Stale or abandoned TODO / FIXME comments
- Redundant docs, verbose comments, placeholder config values
- Unreferenced values, unused helpers, orphaned or dead files

If you spot one while tidying, mention it in one line and point at `prune` — don't act on it.
