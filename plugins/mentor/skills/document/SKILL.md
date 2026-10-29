---
name: document
description: 'Analyze a repository and generate or update its documentation suite — README.md, docs/ARCHITECTURE.md (with embedded Mermaid diagrams), and any domain-specific docs (module READMEs for Terraform, chart READMEs for Helm, API docs for services). Interactive: analyzes first, presents findings, generates based on confirmed choices.'
---

# Document

Generate or update the documentation suite for the current repository through an interactive conversation. Analyzes the codebase, presents what it finds, confirms scope, then writes the docs.

## Hard rules

- **Mermaid first, SVG as fallback.** Prefer embedded Mermaid — it's plain text, version-controlled, and renders natively in GitHub, GitLab, and most doc sites. When a diagram is too complex for Mermaid or requires precise layout, use an SVG file (also text/XML, diffable). Never use `.png`, `.jpg`, `.drawio`, or other binary image formats.
- **Docs describe the current code, not aspirations.** Only document what exists. Do not document planned features, TODOs, or hypothetical future state.
- **No placeholder sections.** If a section can't be filled in from the codebase, omit it rather than writing "TBD" or leaving it empty.
- **Don't duplicate what the code already says.** README quick-starts show *how to run*, not line-by-line explanations of what the code does. Architecture docs show *structure and relationships*, not implementation details.
- **Update, don't overwrite.** If a `README.md` or `docs/ARCHITECTURE.md` already exists, read it, preserve sections that are accurate, and update or add what's missing or stale.

## Process

Execute sequentially. Do not batch all questions upfront.

```
PHASE 1: ANALYZE  →  PHASE 2: CONFIRM  →  PHASE 3: GENERATE
```

### Phase 1: Analyze the repository

Read the codebase to understand what to document. Cover:

**Project type and tech stack**
- Primary language(s), frameworks, runtimes
- Is this a service, library, CLI tool, IaC project, platform repo, or monorepo?

**Entry points and interfaces**
- For services: HTTP/gRPC handlers, public API surface
- For libraries: exported functions, types, packages
- For CLIs: commands and flags
- For IaC: root modules, environments, outputs

**Dependencies and integrations**
- External services, databases, queues, caches this project talks to
- Cloud providers or infrastructure it depends on
- Upstream/downstream data flows

**Existing automation**
- `Taskfile.yaml` / `Makefile` — what commands exist? (`task --list` is the quick start)
- `devbox.json` — what tools are required?
- CI workflows — what does the pipeline do?

**Existing documentation**
- Read every `.md` file that already exists
- Identify what's accurate, what's stale, and what's missing

**Domain-specific signals**
- Terraform: modules, environments (`vars/`), backends, remote state consumers
- Helm: chart structure, values layers, ArgoCD ApplicationSets
- Kubernetes service: ArgoCD/GitOps wiring, ingress, external secrets

### Phase 2: Confirm scope

Present a short summary of what you found and what you plan to generate:

```markdown
## Analysis

**Type**: Go HTTP service  
**Stack**: Go 1.23, Postgres, Redis, deployed via Helm + ArgoCD  
**Automation**: Taskfile (build, test, lint, audit, template:dev, template:prod)  
**Existing docs**: README.md (outdated — references old build command), no docs/

**I'll generate:**
- README.md (update — fix build command, add architecture link)
- docs/ARCHITECTURE.md (new — service diagram, data flow, deployment topology)
- deploy/charts/my-service/README.md (new — values table, usage example)

Does this look right? Anything to add or skip?
```

Wait for confirmation before writing any files.

### Phase 3: Generate

Write the confirmed files. Follow the templates and conventions below.

---

## Documents

### `README.md` (root)

Every project has one. Sections in order:

1. **One-line description** — what does this do, in a sentence
2. **Prerequisites** — tools required (link to devbox if present: `devbox shell` installs everything)
3. **Quick start** — fewest steps to run locally; if a Taskfile exists, use `task --list` then the most common tasks
4. **Directory structure** — annotated tree of top-level dirs only (not every file)
5. **Links** — `docs/ARCHITECTURE.md` for deeper context; CI badge if applicable

Keep it short. If it exceeds ~80 lines, something belongs in `docs/` instead.

### `docs/ARCHITECTURE.md`

The authoritative architecture reference. Sections:

1. **Overview** — what problem this solves; scope (what it is and is not)
2. **Architecture diagram** — Mermaid `graph` or `flowchart`; shows components and their relationships
3. **Components** — one paragraph per major component explaining its role
4. **Data flow** — how data moves through the system; use a Mermaid sequence or flowchart diagram
5. **Deployment topology** — environments (dev, staging, prod), how the service is deployed; Mermaid diagram if non-trivial
6. **External dependencies** — what services, APIs, databases, queues this depends on; include direction (reads from / writes to / subscribes to)
7. **Configuration** — environment variables or config files the service reads at runtime (names and purpose, never values)
8. **Security** — auth model, secret handling, network exposure

Omit sections that don't apply (a CLI tool has no deployment topology section).

#### Mermaid conventions

```markdown
# Component diagram
​```mermaid
graph LR
  client([Client]) --> api[API Service]
  api --> db[(Postgres)]
  api --> cache[(Redis)]
  api --> queue([Kafka Topic])
​```

# Sequence diagram
​```mermaid
sequenceDiagram
  participant C as Client
  participant A as API
  participant D as Database
  C->>A: POST /orders
  A->>D: INSERT order
  D-->>A: ok
  A-->>C: 201 Created
​```

# Deployment diagram
​```mermaid
graph TB
  subgraph dev[Dev Cluster]
    app-dev[my-service-dev]
  end
  subgraph prod[Prod Cluster]
    app-prod[my-service-prod]
  end
  registry[Container Registry] --> app-dev
  registry --> app-prod
​```
```

Use `graph LR` for component/dependency diagrams. Use `sequenceDiagram` for request flows. Use `graph TB` for deployment topology. Keep diagrams focused — one diagram, one concern.

### Domain-specific documents

#### Terraform: `modules/*/README.md`

If the project has a Taskfile with a `docs` task (typically `terraform-docs`), run it:

```bash
task docs
```

If not, generate manually for each module:

```markdown
# module-name

One sentence: what does this module create?

## Usage

​```hcl
module "example" {
  source = "./modules/module-name"

  # required inputs here
  vpc_id  = "vpc-123"
  region  = "us-east-1"
}
​```

## Inputs

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `vpc_id` | `string` | yes | VPC to deploy into |

## Outputs

| Name | Description |
|------|-------------|
| `endpoint` | DNS name of the created resource |
```

Terraform's `docs/ARCHITECTURE.md` must also include:
- A remote state dependency table (if this repo reads from others)
- Environment differences table (what changes between dev/staging/prod)
- State management section (backend, locking, workspace strategy)

#### Helm: `deploy/charts/<name>/README.md`

```markdown
# chart-name

One sentence: what does this chart deploy?

## Usage

​```bash
helm template my-release . \
  -f values.yaml \
  -f defaults/values.yaml \
  -f dev/values.yaml
# or via Taskfile:
task template:dev
​```

## Values

| Key | Default | Description |
|-----|---------|-------------|
| `replicaCount` | `1` | Number of replicas |
| `image.repository` | `registry/image` | Container image |
```

Document every key in `defaults/values.yaml` and `<env>/values.yaml` that a chart consumer is expected to set. Skip internal/computed keys.

#### Service with HTTP API: `docs/api.md`

Only generate this if there is an actual API (HTTP handlers, gRPC definitions, or OpenAPI spec). Sections:

1. **Authentication** — how callers authenticate
2. **Base URL** — per environment
3. **Endpoints** — method, path, request body shape, response shape, error codes
4. **Rate limiting / quotas** (if applicable)

If an OpenAPI spec (`openapi.yaml`) already exists, reference it rather than duplicating it:

```markdown
See [openapi.yaml](../openapi.yaml) for the full API specification.
```

---

## What not to generate

- Changelogs (`CHANGELOG.md`) — those come from git history or release tooling, not from analysis
- Contributing guides — out of scope unless the user asks
- License files — not documentation
- Docs for planned/future features
- Binary image files (`.png`, `.jpg`, `.drawio`) — use Mermaid or SVG instead

## References to other skills

When the repo type matches, read the relevant skill before generating docs:

| Repo type | Read first |
|-----------|-----------|
| Terraform project | `terraform` skill — documentation requirements, `task docs` for module READMEs |
| Kubernetes / Helm | `kubernetes` and `helm` skills — chart README conventions, values table format |
| Service with CI/CD | `github-actions` skill — understand what the pipeline does before documenting it |

## Companion skills — offer after completing

When docs are written or updated, check the repo and offer whichever of these are missing or incomplete:

| Skill | Offer when |
|-------|-----------|
| `devbox` | No `devbox.json` in the repo root — the quick start in README will reference it |
| `taskfile` | No `Taskfile.yaml` / `Taskfile.yml` — the quick start should show `task --list` |
| `ci` | No `.github/workflows/` — CI pipeline worth documenting doesn't exist yet |

Ask as a single grouped question — not mid-task, not separately for each.
