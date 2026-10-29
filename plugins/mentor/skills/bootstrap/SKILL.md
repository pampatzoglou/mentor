---
name: bootstrap
description: Scaffold a new project repository — directory structure, .gitignore, and sequenced skill invocation (devbox → taskfile → helm → ci → document). Handles single-service and multi-service monorepo layouts.
requires: [devbox, taskfile, helm, ci, document]
---

# Bootstrap

Bootstrap scaffolds the standard project structure and then drives each skill in sequence so a new repository is production-ready in one pass.

## What bootstrap does NOT do

- **ApplicationSet**: handled by a dedicated skill — `deploy/argo/` is created but left empty for it.
- **Crossplane**: future skill — skip for now; use `deploy/terraform/` for service-owned cloud resources.
- **Application source code**: bootstrap creates the repo skeleton, not the service implementation.

## Process

```
PHASE 1: GATHER  →  PHASE 2: SCAFFOLD  →  PHASE 3: SKILLS
```

Execute sequentially. Do not batch all questions upfront — ask one phase at a time.

---

### Phase 1: Gather

Ask these questions **in order**, waiting for each answer before the next.

#### 1.1 Project layout (blocking gate)

```
Is this a single-service repo or a multi-service monorepo?

1. Single service  — source at repo root, one chart
2. Multi-service   — source under services/<name>/, one chart per service
```

#### 1.2 Service name(s)

- Single service: "What is the service name?" — used for the Helm chart directory.
- Multi-service: "List the services (space-separated)." — one chart dir and one symlink per service.

#### 1.3 Source location (multi-service only)

"Where does each service's source live?"

- Default: `services/<name>/` — confirm or let user specify a different path.
- Skip for single-service (source is at root).

#### 1.4 Service-owned cloud resources

```
Does this repo manage its own cloud resources (e.g. S3 bucket, RDS, IAM role)?

1. No   — skip deploy/terraform/
2. Yes  — scaffold deploy/terraform/
```

#### 1.5 Confirm plan

Present a summary before touching the filesystem:

```markdown
## Bootstrap plan

**Layout**: multi-service monorepo
**Services**: api, worker
**Source**: services/<name>/
**Cloud resources**: yes → deploy/terraform/

**Will scaffold:**
README.md
docs/
.github/workflows/
deploy/charts/api/
deploy/charts/worker/
deploy/argo/          ← ApplicationSet skill fills this later
deploy/terraform/
services/api/
  chart → ../../deploy/charts/api
services/worker/
  chart → ../../deploy/charts/worker
.argo/                ← gitignored

**Then run skills in order:**
1. devbox
2. taskfile
3. helm  (api, worker)
4. ci
5. document

Proceed?
```

Wait for confirmation before writing anything.

---

### Phase 2: Scaffold

#### Directory structure

Create all directories. Use `.gitkeep` only where Git would otherwise drop the empty dir (e.g. `deploy/argo/` before the ApplicationSet skill runs, `docs/` before document skill runs).

```
README.md                          # stub — document skill will fill
docs/
  .gitkeep
.github/
  workflows/
    .gitkeep
deploy/
  argo/
    .gitkeep
  charts/
    <service>/                     # one per service — helm skill populates
  terraform/                       # only if cloud resources: yes
    .gitkeep
services/                          # multi-service only
  <service>/
    chart -> ../../deploy/charts/<service>   # symlink
.argo/                             # gitignored — render target + CI artifact dir
```

#### `.gitignore`

Add or append:

```gitignore
# Helm render output and CI artifact staging
.argo/
```

If a `.gitignore` already exists, append only if `.argo/` is not already listed.

#### `README.md` stub

Create a minimal stub so the document skill has something to update rather than create from nothing:

```markdown
# <repo-name>

> Scaffolded by bootstrap — run `/document` to generate full documentation.
```

#### Symlinks (multi-service only)

For each service, create the symlink from the source dir to the chart:

```bash
ln -s ../../deploy/charts/<service> services/<service>/chart
```

Verify the symlink resolves correctly after creation.

---

### Phase 3: Run skills in sequence

Invoke each skill in order. Each skill is interactive — let it run its own flow fully before starting the next.

| Step | Skill | Notes |
|------|-------|-------|
| 1 | `devbox` | Pin tool versions; creates `devbox.json`, `devbox.lock`, `.envrc` |
| 2 | `taskfile` | Standard task set; references the tools devbox pinned |
| 3 | `helm` | Run once per service; chart goes into `deploy/charts/<service>/` |
| 4 | `ci` | GitHub Actions workflows; calls tasks devbox+taskfile defined (orchestrates the `github-actions` skill) |
| 5 | `document` | README.md + `docs/ARCHITECTURE.md`; references chart READMEs helm wrote |

After all skills complete, tell the user:

```
Bootstrap complete.

deploy/argo/ is ready — run /argo-applicationset to generate the ApplicationSet
that ArgoCD will sync from.
```

---

## Canonical structure reference

### Single-service (flat)

```
README.md
docs/
.github/workflows/
deploy/
  argo/
  charts/<service>/
  terraform/          # if cloud resources
.argo/                # gitignored
```

### Multi-service monorepo

```
README.md
docs/
.github/workflows/
deploy/
  argo/
  charts/
    <service-a>/
    <service-b>/
  terraform/          # if cloud resources
services/
  <service-a>/
    chart -> ../../deploy/charts/<service-a>
  <service-b>/
    chart -> ../../deploy/charts/<service-b>
.argo/                # gitignored
```

## Companion skills — offer after completing

Bootstrap drives the core skills inline. After the sequence completes, check and offer:

| Skill | Offer when |
|-------|-----------|
| `argo-applicationset` | `deploy/argo/` is empty — this should always be offered |
| `skaffold` | No `skaffold.yaml` and the project has a local dev use case |
