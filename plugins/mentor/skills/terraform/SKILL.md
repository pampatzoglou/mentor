---
name: terraform
description: 'Use whenever the user is working with Terraform or HashiCorp Configuration Language (HCL), or asks broadly about "infrastructure", observability strategy, disaster recovery, or cost optimization. Triggers on terraform, .tf files, .tfvars, HCL, "infrastructure as code", "infra", devbox+terraform, or Taskfiles for IaC. IMPORTANT: this skill operates in plan/validate/review mode only — it never applies infrastructure changes.'
requires: [devbox, taskfile]
---

# Terraform Infrastructure as Code

A skill for writing, structuring, and operating Terraform projects. The skill is opinionated: it standardizes on **devbox** for tool versions, **go-task** for commands, and **embedded Mermaid diagrams** for documentation. Everything is plain text and git-committable — no binaries, no generated images.

## Load first

Before starting any task, load these skills — they define conventions this skill builds on:

- `devbox` — tool version pinning, `.envrc` setup, `devbox run` in CI
- `taskfile` — `action:env` naming (`plan:dev`, not `dev:plan`), standard task set, `prompt:` guards

Also load `github-actions` when the task involves CI/CD setup, and `document` when the task involves README or ARCHITECTURE.md.

## Operational boundary — read this first

**Claude operates in plan / validate / review mode only. Claude never applies, destroys, imports, or otherwise mutates real infrastructure.**

Allowed (when a working environment is available):

- ✅ `task fmt`, `task validate`, `task lint`, `task scan`, `task audit`, `task check`
- ✅ `task plan:<env>` (read-only — generates a plan file, makes no changes)
- ✅ `terraform init` (downloads providers, configures backend; does not change resources)
- ✅ `terraform state list` and `terraform state show` (read-only inspection)
- ✅ `terraform fmt`, `terraform validate` (read-only)

Forbidden — refuse and explain:

- ❌ `task apply:<env>` / `terraform apply`
- ❌ `task destroy:<env>` / `terraform destroy`
- ❌ `terraform import` / `import {}` block executions
- ❌ `terraform state mv`, `terraform state rm`, `terraform state push`
- ❌ `terraform force-unlock`
- ❌ Any `local-exec` or `remote-exec` provisioner that mutates external systems
- ❌ Any direct cloud CLI call that mutates resources (`aws ... create/update/delete`, `gcloud ... create`, etc.)

If a user asks Claude to apply, destroy, or do state surgery, Claude must:
1. Refuse the execution itself.
2. Offer to **write or review the code, generate the plan, or document the runbook** the user will execute themselves.
3. For state surgery, produce the exact commands as a documented runbook (in a markdown file or inline) for the user to run after they've taken a state backup.

This boundary applies even when the user has connected credentials, even when they explicitly authorize the action, even in dev environments. The skill's value is in safe, reviewable artifacts — not in pushing buttons.

## Core principles (apply to every Terraform task)

1. **All commands go through `task`, never raw `terraform`.** This enforces fmt → validate → lint → plan → apply ordering and works identically locally and in CI.
2. **Tool versions live in `devbox.json`.** No "works on my machine."
3. **Documentation is mandatory, not optional.** Every project has `docs/ARCHITECTURE.md` with embedded Mermaid diagrams; every module has its own `README.md`.
4. **State is remote, locked, encrypted, and separated per environment.**
5. **Secrets flow through a secrets backend, never through Terraform state as the source of truth.** Vault and AWS Secrets Manager are the supported backends. Generated secrets are persisted back to the backend in the same module. Consumers read from the backend, never from `terraform output`. See **Secrets** below.

## When to use this skill — quick decision

| User is doing… | Action |
|----------------|--------|
| Starting a new Terraform project | Copy the asset files listed below; produce the full directory structure that follows |
| Adding/editing a module | Apply "Variable and module design" below; ensure the module README is updated |
| Writing or fixing a Taskfile | Use this skill's `Taskfile.yml` as the baseline; also read the shared `taskfile` skill for conventions |
| Writing or fixing devbox.json or .envrc | Use this skill's `devbox.json` as the baseline; also read the shared `devbox` skill |
| Setting up GitHub Actions or pre-commit | Read the shared `github-actions` skill; use this skill's `github-actions.yml` and `.pre-commit-config.yaml` |
| Running an audit / triaging `task audit` findings | Read `audit-triage.md` — Claude reads JSON, triages, proposes fixes |
| Anything involving secrets, credentials, passwords, API keys, tokens | Apply the **Secrets** section below — it has hard rules about consume/persist patterns |

If a task spans multiple categories (e.g. "scaffold a new project with CI"), work through them in the order above.

## Required project structure

Every Terraform project produced or reviewed under this skill MUST have this layout:

```
terraform-project/
├── devbox.json              # Tool versions (required)
├── Taskfile.yml             # Standard commands (required)
├── .gitignore               # Required
├── .pre-commit-config.yaml  # Recommended
├── main.tf                  # Root module orchestration
├── variables.tf             # Inputs with type + description + validation
├── outputs.tf               # Outputs with descriptions
├── providers.tf             # Provider config
├── versions.tf              # Version constraints
├── backend-dev.hcl          # Backend config per env
├── backend-prod.hcl
├── vars/
│   ├── dev.hcl
│   ├── staging.hcl
│   └── prod.hcl
├── modules/
│   └── <module-name>/
│       ├── main.tf
│       ├── variables.tf
│       ├── outputs.tf
│       └── README.md         # Required per module
├── docs/
│   └── ARCHITECTURE.md       # Required, with embedded Mermaid
├── audit-results/            # Generated by `task audit`, gitignored
└── README.md                 # Required
```

When asked to "set up" or "scaffold" a project, produce all of the required files at once. Don't produce a partial skeleton.

## Repo organization — one domain per repo

Infrastructure is split across **multiple repos by domain**, not concentrated in a single monorepo. Each repo owns one logical concern and publishes its outputs via remote state for downstream repos to consume.

Typical decomposition:

```
infra-network/        → VPCs, subnets, transit gateways, DNS zones
infra-platform/       → IAM roles, KMS keys, shared logging, monitoring
infra-data/           → Databases, caches, object storage, data pipelines
infra-app-<name>/     → Application-specific compute, queues, secrets
```

**Why polyrepo:**
- Blast radius: a mistake in `infra-app-foo` cannot touch `infra-network`.
- Permissions: each repo's CI principal gets only the IAM scope it needs.
- Cadence: network changes are rare and reviewed heavily; app changes are frequent and routine. Different repos = different review processes.
- State boundaries: one state file per domain, not one giant state file.

**Reading state from another repo** (the standard pattern):

```hcl
data "terraform_remote_state" "network" {
  backend = "s3"
  config = {
    bucket = "myorg-tfstate-prod"
    key    = "infra-network/terraform.tfstate"
    region = "us-east-1"
  }
}

resource "aws_instance" "app" {
  subnet_id = data.terraform_remote_state.network.outputs.private_subnet_ids[0]
  vpc_security_group_ids = [
    data.terraform_remote_state.network.outputs.app_sg_id,
  ]
}
```

**Rules for remote state consumers:**

- Treat the upstream repo's `outputs.tf` as a public API contract. Document it in `docs/ARCHITECTURE.md`.
- Read state in **read-only** mode. Never modify another repo's state, even if you have access.
- The IAM principal for a downstream repo's CI gets `s3:GetObject` (and `kms:Decrypt`) on the upstream state file — no write permissions.
- If you find yourself wanting to write to another repo's state, the boundary is wrong: refactor the dependency.
- Document remote-state dependencies in your `docs/ARCHITECTURE.md` ("This repo depends on outputs from `infra-network` and `infra-platform`").

**Rules for remote state producers:**

- Outputs are an API. Don't break them without coordination — add new outputs, don't rename.
- Mark sensitive outputs with `sensitive = true`. Anyone with state-bucket read access can see them.
- Keep the output set narrow — only what consumers genuinely need.

## Standard workflow

```bash
devbox shell          # Enter env with pinned tool versions
task --list           # Discover commands
task check            # fmt + validate + lint            ← Claude can run this
task plan:dev         # Plan against dev                 ← Claude can run this
task plan             # Plan all environments            ← Claude can run this
# task plan:prod      # Plan against prod                ← Claude can run this if creds are scoped read-only; otherwise USER ONLY
# task apply:dev      # Apply to dev                     ← USER ONLY
# task apply:prod     # Apply to prod                    ← USER ONLY
```

Claude's role in this workflow:

1. Write and edit the `.tf` code.
2. Run `task check` and `task plan:<env>` to validate.
3. Present the plan output to the user with analysis: what will change, what looks risky, what to double-check.
4. **Offer `task audit`** at the end of substantial work — see `audit-triage.md`. The audit is a deterministic scanner run (`tflint` + `tfsec`); Claude reads the JSON output and helps triage findings.
5. **Stop there.** The user runs `task apply:<env>` themselves.

Never suggest or execute `task apply:<env>`. Even when asked. Even with `-auto-approve`. Even in dev. The user is the only one who applies.

Raw `terraform` commands are acceptable only for the read-only operations listed in the operational boundary section above.

## Variable and module design (summary)

- **Strong types always.** Use `object({...})` and `map(object({...}))` rather than untyped maps.
- **Validate inputs.** Every variable that has a constrained value gets a `validation` block.
- **No defaults for required inputs.** Force callers to be explicit.
- **No defaults for environment-specific values.** Put them in `vars/<env>.hcl`.
- **Module interface = variables in, outputs out.** No side channels, no reading remote state from inside a leaf module.

- **`for_each` over `count`** for anything whose identity should survive a neighbour being added or removed — `count` re-indexes and destroys/recreates. `count` is fine for a genuine on/off toggle (`count = var.enabled ? 1 : 0`).
- **`dynamic` blocks sparingly.** One or two for a genuinely variable-length nested block is fine; a module built out of them is unreadable — reconsider the interface instead.

## Documentation

See the `document` skill for conventions (README.md structure, docs/ARCHITECTURE.md with Mermaid-first diagrams, SVG as fallback, what not to generate).

Terraform-specific additions on top of the standard doc set:

- **`modules/*/README.md`** — run `task docs` (terraform-docs) if the Taskfile has it; otherwise generate manually with inputs/outputs tables.
- **`docs/ARCHITECTURE.md`** extra sections: remote-state dependency table (which repos this reads from and what outputs it uses), environment differences table (what changes between dev/staging/prod), state management section (backend, locking strategy).

The `document` skill owns the `ARCHITECTURE.md` structure and Mermaid conventions — follow it rather than a Terraform-specific template.

## Hard rules

- ❌ Never apply, destroy, import, or perform state surgery — see the operational boundary above
- ❌ Never put literal secret values in `.tf`, `.tfvars`, `.hcl`, or any version-controlled file — secrets come from Vault or AWS Secrets Manager (see **Secrets** above)
- ❌ Never use `terraform output` as the canonical way to retrieve a secret value — generated secrets are persisted back to the secrets backend in the same module
- ❌ Never produce a project without `devbox.json` and `Taskfile.yml`
- ❌ Never produce architecture documentation as a binary image file (`.png`, `.drawio`) — use embedded Mermaid or SVG
- ❌ Never use `count` for resources whose identity should be stable across additions/removals — use `for_each` with a map
- ❌ Never store state locally for any project that will have more than one contributor
- ❌ Never put unrelated infrastructure in the same repo — one domain per repo (see "Repo organization" above)
- ✅ Always present a plan and analyze its output before the user applies
- ✅ Always add `lifecycle { prevent_destroy = true }` on stateful production resources (databases, state buckets, KMS keys)
- ✅ Always pin provider versions in `versions.tf` with `~>` constraints
- ✅ Always read shared infrastructure (network, IAM, etc.) via `data "terraform_remote_state"` rather than duplicating definitions
- ✅ Always pair secret generation (e.g. `random_password`) with persistence to a secrets backend in the same module — output only the ARN/path, never the value

## Secrets

The **`secrets` skill owns the cross-platform contract** — Vault path conventions, the three source modes, and how a credential reaches a container. This section is the Terraform-side implementation of it; read that skill first when a task spans both.

Hard rules. These apply to every task that touches a credential, password, key, or token.

**Never a literal in version control.** No secret values in `.tf`, `.tfvars`, `.hcl`, or any committed file. `backend-*.hcl` and `vars/*.hcl` are committed precisely because they hold no secrets — keep it that way.

**Consume: read from the backend at plan time.** Reference the secret, don't copy it.

```hcl
data "aws_secretsmanager_secret_version" "db" {
  secret_id = "prod/payments/db"          # the backend is the source of truth
}

# Vault equivalent
data "vault_kv_secret_v2" "db" {
  mount = "secret"                        # per the `secrets` skill: secret/<app>/<env>
  name  = "payments/prod"
}
```

**Persist: a generated secret is written back to the backend in the same module.** Generating a password and only emitting it as an output makes state the source of truth — that's the failure mode. Generate and persist together:

```hcl
resource "random_password" "db" {
  length  = 32
  special = true
}

resource "aws_secretsmanager_secret" "db" {
  name = "prod/payments/db"
}

resource "aws_secretsmanager_secret_version" "db" {
  secret_id     = aws_secretsmanager_secret.db.id
  secret_string = random_password.db.result
}

output "db_secret_arn" {
  description = "Where consumers fetch the credential. The value is never output."
  value       = aws_secretsmanager_secret.db.arn      # the ARN/path, never the secret
}
```

**Never `terraform output` as the retrieval path.** Consumers read the backend using the ARN/path. An output carrying a secret value ends up in CI logs, state, and anyone's shell history.

**State is sensitive regardless.** `random_password.result` and any `data` secret land in state in plaintext — so the backend must be encrypted (SSE-KMS) and its read access must be as tight as the secret itself. Mark every secret-adjacent output `sensitive = true`; that hides it from CLI output but *not* from state.

**Prefer dynamic over static.** Vault dynamic credentials (database, cloud STS) expire on their own, so a leak has a bounded blast radius. Reach for static KV only when nothing dynamic exists.

**Rotation is a backend concern, not a Terraform run.** Wire up the backend's native rotation (Secrets Manager rotation Lambda, Vault TTLs). Don't build rotation as "re-run `apply` to regenerate" — that couples credential lifetime to your deploy cadence.

**Local dev reads the same paths.** Developer shells pull from the same Vault paths the workload reads in-cluster (see the `devbox` skill's `init_hook` and the `helm` skill's credential blocks), so dev and prod resolve identical keys.

## Asset files (copy these into the user's project)

These live alongside this `SKILL.md` in the skill directory:

- `devbox.json` — pinned tool versions
- `Taskfile.yml` — full standard task set
- `.gitignore` — covers Terraform, audit, and plan artifacts
- `.pre-commit-config.yaml` — pre-commit hooks
- `github-actions.yml` — GitHub Actions workflow
- `audit-triage.md` — not a template; read it when triaging `task audit` output

When scaffolding, copy the first five verbatim and fill in the project-specific bits (project name, providers, regions). Don't rewrite them from scratch. For `README.md`, `docs/ARCHITECTURE.md`, and `modules/*/README.md`, the `document` skill owns the structure — see **Documentation** above for the Terraform-specific sections to add.

## Observability

When provisioning or reviewing infrastructure, apply these principles:

- **Metrics**: Prometheus + Grafana. Four Golden Signals for services (Latency, Traffic, Errors, Saturation); USE method for infrastructure (Utilization, Saturation, Errors).
- **Logs**: structured JSON to stdout/stderr; centralized aggregation (Loki, ELK, CloudWatch); correlation IDs for cross-service tracing.
- **Traces**: distributed tracing (Jaeger, Tempo, X-Ray) for multi-service flows.
- **Alerts**: alert on symptoms (user-impacting conditions), not causes. Every alert needs a runbook. Page only for user-impacting events.

## Disaster recovery

- Automated backups with **tested** restore procedures. Untested backups aren't backups. Document RPO and RTO.
- Multi-AZ (or multi-region) for production stateful resources — provision this in Terraform, not as an afterthought.
- Failover procedures written, rehearsed, and linked from runbooks.
- Add `lifecycle { prevent_destroy = true }` on stateful production resources to guard against accidental `terraform destroy`.

## Cost

- Right-size resources from actual utilization metrics, not initial guesses.
- Auto-scaling for variable workloads; reserved/committed capacity for predictable baseline.
- Spot/preemptible instances for fault-tolerant batch workloads.
- Tag every resource for cost allocation by team, service, and environment — enforce via Terraform variable + `default_tags`.
- Regular cost reviews — cloud spend drifts silently without them.

## Companion skills — offer after completing

When the main task is done (scaffolding, module work, plan review, audit triage), check the repo and offer whichever of these are missing or incomplete:

| Skill | Offer when |
|-------|-----------|
| `devbox` | No `devbox.json` in the repo root |
| `taskfile` | No `Taskfile.yaml` / `Taskfile.yml` in the repo root |
| `document` | No `docs/ARCHITECTURE.md`, or module READMEs are missing / out of date |

Ask as a single grouped question — not mid-task, not separately for each.
