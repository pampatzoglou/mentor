# Audit Triage

How to help the user work through findings produced by `task audit`. Read this when:

- The user has just run `task audit` and it failed
- The user asks Claude to look at `audit-results/`
- At the end of a code-writing session, Claude is offering to run an audit pass

## The division of labour

**The scanners decide what's a finding.** `tflint` and `tfsec` are deterministic; their output is the source of truth. Claude does not produce, invent, or "remember" findings — Claude reads `audit-results/tflint.json` and `audit-results/tfsec.json` and works with what's actually there.

**Claude triages and helps fix.** That's where the value is: explaining a finding in context, judging severity for *this* codebase, proposing the patch, and (optionally) producing a documented suppression for false positives.

If `audit-results/` doesn't exist, Claude does not pretend to audit. Claude tells the user to run `task audit` first.

## When to offer an audit

At the end of substantial Terraform work — scaffolding, module changes, secret-handling changes, IAM/network changes, CI changes — Claude proactively offers:

> "Want to run `task audit` before we wrap? It runs tflint + tfsec and dumps JSON I can walk through with you."

If the user says yes and the environment supports it, Claude runs `task audit` (it's a read-only operation, allowed by the operational boundary). If `task audit` exits non-zero, Claude proceeds to triage.

If the user has already run `task audit` themselves and pasted the output (or pointed Claude at `audit-results/`), skip the offer and go straight to triage.

Don't offer an audit:
- After trivial edits (typos, formatting)
- If the user has explicitly said they're prototyping and don't want guardrails
- More than once per session unless code has changed

## Triage procedure

1. **Read both JSON files.**

   ```bash
   cat audit-results/tflint.json
   cat audit-results/tfsec.json
   ```

   Parse them. Don't summarise from memory.

2. **Group findings.** For each finding, classify:

   - **Real and fixable** — a genuine issue Claude can patch in the code (most findings)
   - **Real but contextual** — genuine but the fix is a design decision the user should make (e.g. "make this S3 bucket private" when it's intentionally public for a CDN origin)
   - **False positive** — the rule doesn't apply here (rare; default to "real" unless clearly wrong)

3. **Present a structured summary**, not a wall of JSON. Use a compact table:

   ```
   tfsec — 4 findings:
     CRITICAL  AWS017  S3 bucket without encryption     modules/storage/main.tf:12
     HIGH      AWS018  S3 bucket without versioning     modules/storage/main.tf:12
     MEDIUM    AWS002  S3 bucket without access logs    modules/storage/main.tf:12
     LOW       AWS077  S3 bucket without lifecycle      modules/storage/main.tf:12

   tflint — 1 finding:
     WARN      terraform_unused_declarations  variable.region is declared but never used     variables.tf:14
   ```

   Sort by severity. Show file + line. Show the rule code so the user can look it up.

4. **Walk through findings, highest severity first.** For each one:

   - State what the rule is checking and why
   - Show the offending code
   - Propose the fix as a concrete patch
   - Note if it's a design decision rather than a clear fix
   - Ask before patching multiple files at once

5. **Don't bulk-fix silently.** Even when fixes are obvious, present them and confirm. The user is the reviewer of last resort.

6. **Re-run after fixing.** After patches, ask the user to re-run `task audit` and confirm clean. If new findings have appeared (a fix introduced a different issue), iterate.

## Severity calibration

`tfsec` severities are sometimes more aggressive than warranted for a given context. Rough guide:

- **CRITICAL / HIGH** — fix unless there's a documented reason not to
- **MEDIUM** — usually fix; sometimes context-dependent
- **LOW / INFO** — judgment call; fixing is good hygiene but not always urgent

`tflint` issues are mostly hard-and-fast (unused variables, wrong types, syntax-adjacent issues). Default to fixing all of them.

The user's risk appetite governs. A throwaway dev-account experiment can ship with LOW findings; a production data-tier module shouldn't.

## Suppressions (when a finding is genuinely a false positive)

`tfsec` ignores live in code comments next to the offending resource:

```hcl
resource "aws_s3_bucket" "public_assets" {
  bucket = "myorg-public-assets"
  # tfsec:ignore:aws-s3-encryption-customer-key — public CDN content, no PII; encryption adds no security here
}
```

Rules for adding a suppression:

- ❌ Never suppress without a comment explaining *why* (the inline comment is part of the suppression)
- ❌ Never suppress with a vague "false positive" — say what makes this case different
- ❌ Never wrap a whole module in suppressions; suppress per-resource
- ❌ Never suppress CRITICAL or HIGH findings without explicit user approval (Claude proposes, user decides)
- ✅ Always link to a ticket / decision record if one exists
- ✅ Always re-run `task audit` after adding a suppression to confirm the JSON is now clean

Equivalent for `tflint` — `.tflint.hcl` config:

```hcl
rule "terraform_unused_declarations" {
  enabled = true
}

# Suppress for a specific module if genuinely needed
config {
  module = false
}
```

Prefer inline suppression to global config — the context is preserved next to the code.

## Findings that map to skill rules

When a finding overlaps with a hard rule from this skill, point it out explicitly. Examples:

- tfsec flagging plaintext password in code → links to SKILL.md's Secrets rule "never a literal in version control"
- tfsec flagging unencrypted state backend → links to the hard rule on remote, encrypted, per-env state
- tflint flagging missing `description` on a variable → links to the module-design rule "every variable gets a description"
- tfsec flagging `0.0.0.0/0` ingress → links to the least-privilege networking rule

This helps the user see the audit not as a separate ritual but as a confirmation of guidelines the skill has been pushing all along.

## What Claude must NOT do

- ❌ **Do not run scanners directly.** Use `task audit` so the configuration is consistent.
- ❌ **Do not invent findings** that aren't in the JSON output, even if you suspect them. If you suspect something tfsec missed, point it out as a *concern*, clearly distinguished from audit findings.
- ❌ **Do not silently bulk-suppress** to make the audit pass. The point is to fix, not to mute.
- ❌ **Do not mark a finding "fixed" without re-running** the audit. Patching code in chat doesn't update `audit-results/`.
- ❌ **Do not apply fixes to live infrastructure.** Patching `.tf` is fine; running `task apply:<env>` is the user's job (operational boundary).

## Reporting back to the user

After triage, summarise plainly:

> "Audit found 5 issues. We fixed 3 (encryption, versioning, unused variable). 1 is a documented design decision suppressed inline (public bucket). 1 we agreed to defer (lifecycle policy — tracked in INFRA-432). Re-running task audit shows clean."

Concise, factual, with provenance for every decision.
