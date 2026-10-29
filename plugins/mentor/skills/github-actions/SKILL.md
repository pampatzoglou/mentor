---
name: github-actions
description: 'GitHub Actions CI that delegates all job logic to Taskfile tasks: the checkout + setup-tools + task pattern, the reusable setup-tools composite action and its version parity with devbox.json, SHA pinning, security hardening, OIDC auth, matrix strategies, environment protection, and the PR / merge / release workflow split. Use when editing files under .github/workflows/ or .github/actions/, pinning actions by SHA, setting permissions, wiring OIDC to a cloud, or adding a matrix or environment gate. For generating a repo''s CI from scratch use the ci skill.'
license: Apache-2.0
---

# GitHub Actions

All CI workflows follow one principle: **the workflow handles infrastructure (checkout, tool installation, auth, caching); tasks handle logic (`task X`)**. Workflows with inline commands are harder to reproduce locally, harder to test, and harder to maintain.

## Core pattern

Every job: check out, install the tools this job needs, then call a task.

```yaml
- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
  with:
    persist-credentials: false
- uses: ./.github/actions/setup-tools     # installs pinned tools — see below
  with:
    helm: "true"
    kubectl: "true"
- run: task audit:dev
```

**Do not use devbox in CI.** Devbox is the *developer's* environment manager — it owns the
laptop, not the runner. On a runner it adds a large Nix closure to restore on every job, a
third-party action in every job's critical path, and an opaque failure mode (`task: command
not found` meaning "the Nix install failed"). Install tools with their own pinned setup
actions instead.

What devbox is still authoritative for: **the version numbers**. `devbox.json` declares the
toolchain; CI installs the same versions through different means. That parity is an obligation,
not a nicety — see **Keeping CI and devbox in sync** below. If they drift, a chart renders one
way on a laptop and another way in CI, and you find out from a failed deploy.

See the `devbox` skill for the package list and the `taskfile` skill for task conventions.

This file covers the generic foundations. For Kubernetes/ArgoCD delivery, two reference files go deeper: `kubernetes-ci.md` (PR-time lint/template/audit) and `cross-repo-promotion.md` (merge-time image-tag promotion into the GitOps repo).

## The setup-tools composite action

Installing tools inline in every job means the same pinned SHA and version pasted into six
places, which drifts the moment one gets bumped. Put it in one composite action with a toggle
per tool, so each job asks for exactly what it needs.

`.github/actions/setup-tools/action.yml`:

```yaml
name: Setup tools
description: Install the pinned toolchain. Versions must match devbox.json — see the github-actions skill.

inputs:
  task:        { description: Install go-task,     default: "true" }
  helm:        { description: Install helm,        default: "false" }
  kubectl:     { description: Install kubectl,     default: "false" }
  kubeconform: { description: Install kubeconform, default: "false" }
  kubescape:   { description: Install kubescape,   default: "false" }
  terraform:   { description: Install terraform,   default: "false" }

runs:
  using: composite
  steps:
    # go-task is on by default — every job's entry point is `task <name>`.
    - name: Install go-task
      if: inputs.task == 'true'
      uses: go-task/setup-task@a00fbb05ce67b35648be3c78cbc9fd85354c757e # v2.2.0
      with:
        version: 3.40.1                 # devbox.json: go-task@3.40

    - name: Install helm
      if: inputs.helm == 'true'
      uses: azure/setup-helm@9bc31f4ebc9c6b171d7bfbaa5d006ae7abdb4310 # v5.0.1
      with:
        version: v3.16.4                # devbox.json: helm@3.16

    - name: Install kubectl
      if: inputs.kubectl == 'true'
      uses: azure/setup-kubectl@bda439f5f36b99b262ebdcd3613869bddb064c8e # v5.2.0
      with:
        version: v1.33.4                # devbox.json: kubectl@1.33

    - name: Install terraform
      if: inputs.terraform == 'true'
      uses: hashicorp/setup-terraform@dfe3c3f87815947d99a8997f908cb6525fc44e9e # v4.0.1
      with:
        terraform_version: 1.9.8        # devbox.json: terraform@1.9
        terraform_wrapper: false        # the wrapper mangles exit codes task relies on

    # Tools with no maintained setup action: fetch the release, arch-detected.
    - name: Install kubeconform
      if: inputs.kubeconform == 'true'
      shell: bash
      env:
        VERSION: "0.7.0"                # devbox.json: kubeconform@0.7
      run: |
        set -euo pipefail
        arch=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
        curl -fsSL "https://github.com/yannh/kubeconform/releases/download/v${VERSION}/kubeconform-linux-${arch}.tar.gz" \
          | tar -xz -C /usr/local/bin kubeconform

    - name: Install kubescape
      if: inputs.kubescape == 'true'
      shell: bash
      env:
        VERSION: "3.0.34"               # devbox.json: kubescape@3
      run: |
        set -euo pipefail
        arch=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
        curl -fsSL -o /usr/local/bin/kubescape \
          "https://github.com/kubescape/kubescape/releases/download/v${VERSION}/kubescape-ubuntu-${arch}"
        chmod +x /usr/local/bin/kubescape
```

Rules for this file:

- **Every `uses:` is SHA-pinned** — composite actions are not exempt (see **Pinning actions to digests**).
- **Every version carries a `# devbox.json: <pkg>@<constraint>` comment.** That comment is what makes the parity checkable by a human *and* by the script below.
- **Default to `false`** for everything except `task`. A job that only runs unit tests shouldn't install helm.
- **No arch hardcoding** in the `curl` fallbacks — detect it, same rule as the `dockerfile` skill.
- `terraform_wrapper: false` — the wrapper wraps stdout/exit codes and breaks `task`'s error propagation.

## Keeping CI and devbox in sync

`devbox.json` declares the constraint (`helm@3.16`); CI pins a patch inside it (`v3.16.4`). The
obligation is that **the CI version satisfies the devbox constraint** — same major.minor, patch
free to differ. Enforce it rather than trusting it:

```bash
# task ci:versions — fails if a CI pin drifts outside its devbox constraint
set -euo pipefail
status=0
while IFS= read -r line; do
  ver=$(printf '%s' "$line" | sed -n 's/.*version[_a-z]*:[[:space:]]*v\{0,1\}\([0-9][0-9.]*\).*/\1/p')
  pkg=$(printf '%s' "$line" | sed -n 's/.*devbox\.json:[[:space:]]*\([a-z0-9-]*\)@.*/\1/p')
  want=$(printf '%s' "$line" | sed -n 's/.*devbox\.json:[[:space:]]*[a-z0-9-]*@\([0-9.]*\).*/\1/p')
  [ -n "$ver" ] && [ -n "$want" ] || continue
  case "$ver" in
    "$want"|"$want".*) ;;
    *) echo "✗ $pkg: CI pins $ver but devbox.json declares $want"; status=1 ;;
  esac
done < <(grep -n 'devbox\.json:' .github/actions/setup-tools/action.yml)
[ "$status" -eq 0 ] && echo "✓ CI tool versions match devbox.json"
exit "$status"
```

Wire it into `task lint` so a bump in one place fails until it's made in both. Bumping a tool
is then a two-line change in two files — annoying by design, because the alternative is silent
dev/CI divergence.

## Standard workflow structure

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read          # minimum — don't grant write unless the job needs it

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true    # cancel older runs on the same ref

jobs:
  audit:
    name: Audit
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: ./.github/actions/setup-tools
        with:
          helm: "true"
          kubeconform: "true"
          kubescape: "true"
      - run: task audit
```

## Security hardening

| Practice | How |
|---|---|
| Minimal permissions | `permissions: contents: read` at workflow level; add only what individual jobs actually need |
| OIDC over long-lived tokens | `id-token: write` + cloud OIDC action; never store static credentials in secrets when OIDC is available |
| Pin actions to a commit SHA | Pin **every** `uses:` to a full-length commit SHA — never a tag or branch. Tags are mutable and re-pointable (the `tj-actions/changed-files` 2025 supply-chain attack). Keep the version in a trailing comment; let Dependabot/Renovate bump it. See **Pinning actions to digests** below. |
| No credential persistence | `persist-credentials: false` on `actions/checkout` when downstream steps don't need git push |
| No script injection | Never interpolate untrusted inputs (PR titles, branch names) into `run:` commands |
| Avoid `pull_request_target` | Has secret access but can checkout fork code — dangerous combination |
| Environment protection | Use GitHub Environments with required reviewers for production deploys |
| Cross-repo writes | Mint a scoped GitHub App token (`actions/create-github-app-token`) for git/PR ops against another repo — never store a long-lived PAT |

OIDC example (AWS):
```yaml
permissions:
  id-token: write
  contents: read

steps:
  - uses: aws-actions/configure-aws-credentials@e1253824e5c10ff9df46874f81ed3ec929e19cfd # v6.3.0
    with:
      role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
      aws-region: us-east-1
```

## Pinning actions to digests

Tags (`@v4`, `@v4.2.2`) and branches (`@main`) are **mutable** — whoever controls the action's repo can move them to point at new code. A leaked maintainer token or a poisoned tag re-point then runs arbitrary code in your pipeline with your secrets and `GITHUB_TOKEN`. This is not hypothetical: the March 2025 `tj-actions/changed-files` compromise retroactively altered tags and leaked secrets from thousands of workflows. A full-length commit SHA is immutable — it pins the exact tree you reviewed.

```yaml
# ✅ pinned to a digest; version in a trailing comment for readability + Dependabot
- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
- uses: go-task/setup-task@a00fbb05ce67b35648be3c78cbc9fd85354c757e # v2.2.0

# ❌ mutable — never in real workflows
- uses: actions/checkout@v4
- uses: actions/checkout@main
```

Rules:
- Pin **every** `uses:` to a 40-character commit SHA — first-party `actions/*` included. "Trusted org" is not the same as "immutable ref".
- Keep the human-readable version in a trailing `# vX.Y.Z` comment so the pin stays reviewable and bumpable.
- Pin Docker-based actions by digest too: `uses: docker://image@sha256:...`.
- **Automate the bumps** so SHA-pinning doesn't mean stale actions — Dependabot or Renovate updates both the SHA and the comment.

Resolve a tag to its SHA, or convert a whole repo in bulk:
```sh
gh api repos/actions/checkout/commits/v4.2.2 --jq .sha   # one action
pinact run          # or: ratchet pin — rewrites every tag in .github/workflows to a SHA
```

Dependabot keeps them current:
```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
```

> The `@vX` tags shown elsewhere in this skill and its companion files (`kubernetes-ci.md`, `cross-repo-promotion.md`) are written that way for readability — real workflows must SHA-pin as above.

## Matrix strategies

Use matrix for running the same job across environments, platforms, or named dimensions:

```yaml
strategy:
  fail-fast: false         # show all failures, not just the first
  matrix:
    env: [dev, prod]

steps:
  - run: task audit:${{ matrix.env }}
```

`fail-fast: false` is almost always correct — seeing all failures at once is more useful than stopping at the first.

## Caching

The setup actions above are fast and need no caching of their own. For language-level caches, add after the setup step:

```yaml
# Go modules
- uses: actions/cache@55cc8345863c7cc4c66a329aec7e433d2d1c52a9 # v6.1.0
  with:
    path: ~/go/pkg/mod
    key: go-${{ runner.os }}-${{ hashFiles('**/go.sum') }}

# npm
- uses: actions/cache@55cc8345863c7cc4c66a329aec7e433d2d1c52a9 # v6.1.0
  with:
    path: ~/.npm
    key: node-${{ runner.os }}-${{ hashFiles('**/package-lock.json') }}

# Cargo
- uses: actions/cache@55cc8345863c7cc4c66a329aec7e433d2d1c52a9 # v6.1.0
  with:
    path: ~/.cargo
    key: cargo-${{ runner.os }}-${{ hashFiles('**/Cargo.lock') }}
```

## Workflow split: PR vs merge vs release

| Trigger | Workflow | Jobs |
|---|---|---|
| Pull request | `ci.yaml` | audit (+ plan for IaC) |
| Push to main | `ci.yaml` | apply/deploy (gated by environment) |
| Tag push | `release.yaml` | build + publish artifacts/images |

Keep release concerns out of the PR workflow — image pushes, package publishes, and environment deploys triggered by tags live in a separate `release.yaml`.

## Uploading artifacts

Upload scan/audit results even on failure so they're available for triage:

```yaml
- uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2
  if: always()
  with:
    name: audit-results
    path: audit-results/
    retention-days: 7
```

## Secrets and fork PRs

Fork PRs cannot access base repo secrets. Use `if: secrets.X != ''` to skip steps that need secrets:

```yaml
- name: Run integration tests
  if: secrets.API_KEY != ''
  run: task test:integration
  env:
    API_KEY: ${{ secrets.API_KEY }}
```

Document required secrets in the workflow file with setup instructions:

```yaml
# Required secrets:
# AWS_ROLE_ARN — IAM role ARN for OIDC federation
# Create via: gh secret set AWS_ROLE_ARN
```

## Concurrency: cancel vs serialize

`cancel-in-progress: true` — correct for PR checks. Cancel the old run when a new push arrives.

`cancel-in-progress: false` — correct for deploys. Never cancel an in-progress apply or deploy.

```yaml
# For deploy jobs:
concurrency:
  group: deploy-${{ matrix.env }}-${{ github.ref }}
  cancel-in-progress: false
```

## Common failure patterns

| Symptom | Cause |
|---|---|
| `task: command not found` | the `setup-tools` step was omitted, or its `task` input was set to `"false"` |
| `task X` hangs | Task waiting for stdin — add `--yes` or non-interactive flags |
| a tool works locally but not in CI | its version is missing from `setup-tools`, or drifted from `devbox.json` — run the parity check |
| Cache miss every run | Cache key changes each run — check that lockfiles aren't being modified before the cache step |
| Fork PRs skip steps | Expected — forks can't access base secrets; guard with `if: secrets.X != ''` |
| Job slow on first run | Cold Nix store — subsequent runs hit the cache |

## Kubernetes CI/CD — reference files

For Helm/ArgoCD repos the pipeline splits across two companion files; read the one that matches the task:

| File | Covers | When |
|---|---|---|
| `kubernetes-ci.md` | lint/template/audit matrix over environments, the `.argo/` render check, canonical `ci.yaml`, branch protection | PR-time checks |
| `cross-repo-promotion.md` | promoting the built image tag into the separate GitOps repo via a scoped GitHub App token and an auto-merged PR | merge-time deploy |

## Companion skills — offer after completing

When the CI workflow is done, check the repo and offer whichever of these are missing or incomplete:

| Skill | Offer when |
|-------|-----------|
| `devbox` | No `devbox.json` — CI does not use it, but it is the declared source of the versions `setup-tools` must match |
| `taskfile` | No `Taskfile.yaml` / `Taskfile.yml` in the repo root — CI calls tasks, so this is a blocker if missing |
| `document` | No `docs/ARCHITECTURE.md`, or existing README doesn't describe the CI/CD pipeline |

Ask as a single grouped question — not mid-task, not separately for each.
