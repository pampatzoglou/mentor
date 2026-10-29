---
name: taskfile
description: 'Standard Taskfile conventions across all projects. Covers the core principle (CI calls tasks not inline commands), standard task naming, the action:env convention, the variables pattern, and CI integration.'
---

# Taskfile

All project automation lives in `Taskfile.yaml` (go-task). CI, local dev, and scripts call the same task commands — no divergence between "how it runs locally" and "how CI runs it."

## Core principle

CI must call project tasks, not contain inline command logic:

```yaml
# BAD — logic lives in CI, can't reproduce locally the same way
- run: helm lint ./charts && kubescape scan framework nsa .argo/

# GOOD — CI delegates to project automation
- run: task audit:dev
```

Benefits: local/CI parity, portability across CI platforms, single source of truth for how things run.

## Standard task names

Use these names consistently so developers don't re-learn per repo:

| Task | Purpose |
|---|---|
| `default` | `task --list` — show available tasks |
| `fmt` | Format source files |
| `validate` | Validate syntax/schema |
| `lint` | Static analysis (after fmt + validate) |
| `test` | Run tests |
| `build` | Build artifacts |
| `scan` | Security scan |
| `audit` | Full pre-merge gate: fmt → validate → lint → scan |
| `clean` | Remove generated artifacts |
| `docs` | Regenerate documentation |

Domain-specific tasks extend this set (e.g., `template`/`plan`/`apply` for Helm and Terraform).

**`audit` is always "the full pre-merge gate" — what it composes is domain-specific.** The
generic shape is fmt → validate → lint → scan; a Helm repo's `audit:<env>` renders the charts
and runs `kubescape` (see `helm-tasks.md`), and a Terraform repo's runs `tflint` + `tfsec` to
JSON. Keep the *name* and the *meaning* fixed so CI can always call `task audit` (or
`audit:<env>`) without knowing the stack; let the body differ. `scan` stays the
security-scanner step that `audit` calls, so it exists in every repo that has a scanner.

## Environment task naming convention

Tasks with environment variants follow **`action:env`** ordering — action first, environment as a suffix. The bare action (no suffix) iterates all known environments sequentially:

```bash
task plan         # iterate all environments: dev → staging → prod
task plan:dev     # dev only
task plan:prod    # prod only
```

Implementation pattern — the bare task calls each env variant in order:

```yaml
tasks:
  plan:
    desc: Plan all environments
    cmds:
      - task: plan:dev
      - task: plan:staging
      - task: plan:prod

  plan:dev:
    desc: Plan dev
    cmds:
      - task: _plan
        vars: { ENV: dev }

  plan:staging:
    desc: Plan staging
    cmds:
      - task: _plan
        vars: { ENV: staging }

  plan:prod:
    desc: Plan production
    cmds:
      - task: _plan
        vars: { ENV: prod }

  _plan:
    internal: true
    cmds:
      - <do the work for {{.ENV}}>
```

**Destructive actions (`apply`, `destroy`) do not get a bare all-envs variant** — requiring an explicit `task apply:dev` prevents accidental multi-environment mutations.

`task --list` groups naturally by action, and tab-completion on `task plan:<TAB>` discovers available environments.

## Variables pattern

Additional dimensions (e.g., chart name, region) stay as `KEY=VALUE` variables alongside the `action:env` suffix:

```bash
task template:dev                          # all charts, dev
task template:dev CHART_NAME=api           # one chart, dev
task template:prod CHART_NAME=api          # one chart, prod
```

Declare variables with defaults at the top of each task:

```yaml
tasks:
  template:dev:
    vars:
      CHART_NAME: '{{.CHART_NAME | default ""}}'
    cmds:
      - task: _template
        vars: { ENV: dev, CHART_NAME: "{{.CHART_NAME}}" }
```

## Canonical Taskfile skeleton

```yaml
version: "3"

tasks:
  default:
    desc: List available tasks
    cmds:
      - task --list

  fmt:
    desc: Format all source files
    cmds:
      - <formatter>

  validate:
    desc: Validate configuration syntax
    deps: [fmt]
    cmds:
      - <validator>

  lint:
    desc: Run static analysis
    deps: [fmt, validate]
    cmds:
      - <linter>

  test:
    desc: Run tests
    cmds:
      - <test-runner>

  scan:
    desc: Security scan
    cmds:
      - <scanner>

  audit:
    desc: Full pre-merge check — fmt, validate, lint, scan
    cmds:
      - task: fmt
      - task: validate
      - task: lint
      - task: scan

  clean:
    desc: Remove generated artifacts
    cmds:
      - rm -rf <output-dirs>
```

## Task dependencies

`deps:` runs tasks in parallel before the current task's `cmds`. Explicit `task:` calls within `cmds` run sequentially:

```yaml
audit:
  cmds:
    - task: fmt         # sequential — each waits for the previous
    - task: validate
    - task: lint
    - task: scan
```

Use `deps:` when order doesn't matter and parallel execution is safe. Use sequential `task:` calls when ordering is required.

## CI integration

```yaml
- uses: ./.github/actions/setup-tools   # pinned tools; versions match devbox.json
  with:
    helm: "true"
- run: task audit
```

CI installs tools via pinned setup actions, not devbox — devbox is the developer environment.
The task name is the contract either way: the same `task audit` runs on a laptop and on a
runner. See the `github-actions` skill for the composite action and the version-parity check.

## Destructive tasks — always use `prompt:`

go-task's `prompt:` field blocks execution until the user confirms. Required on any task that deletes data, applies infrastructure changes, or is hard to reverse:

```yaml
tasks:
  destroy:prod:
    desc: Destroy production infrastructure
    prompt: Destroy ALL resources in prod. Are you absolutely sure?
    cmds:
      - task: _destroy
        vars: { ENV: prod }

  db:drop:
    desc: Drop and recreate the local database
    prompt: This will delete all local data. Continue?
    cmds:
      - psql -c "DROP DATABASE IF EXISTS myapp_dev"
      - psql -c "CREATE DATABASE myapp_dev"
```

`prompt:` fires even when called as a dependency of another task. Bare all-envs variants of destructive actions must not exist — require an explicit `task destroy:prod`, never `task destroy`.

## Helm chart tasks

For repos that deploy Helm charts, add `template`, `lint`, and `audit` tasks following
the `action:env` naming convention. The full reference — core variables, output-directory
layout, the canonical Helm `Taskfile.yaml`, and kubescape configuration — lives in
**`helm-tasks.md`**. Load it when a `deploy/charts/` directory is present.

## What not to add

- **Hyphenated or reversed environment names** (`lint-dev:`, `dev:lint:`) — the environment is a `:`-suffixed axis, so it's `lint:dev`. This is the *only* axis that gets a suffix.
- **A `:`-suffix for any other dimension** (`template:dev:api:`, `plan:dev:eu-west:`) — every dimension beyond the environment is a `KEY=VALUE` variable: `task template:dev CHART_NAME=api`. Suffixing them multiplies the task list combinatorially.
- **Inline logic that belongs in the build system** — if `npm build` exists, call it; don't rewrite it in shell.
- **Destructive tasks without `prompt:`** — see above.
- **A bare all-envs variant of a destructive action** — no `destroy:`, no `apply:`.

## Companion skills — offer after completing

When Taskfile setup is done, check the repo and offer whichever of these are missing or incomplete:

| Skill | Offer when |
|-------|-----------|
| `devbox` | No `devbox.json` in the repo root — tasks won't have pinned tools without it |
| `github-actions` | No `.github/workflows/` directory, or existing workflows don't call tasks |
| `document` | No `docs/ARCHITECTURE.md` or README doesn't document the available tasks |

Ask as a single grouped question — not mid-task, not separately for each.
