---
name: tagging
description: Canonical metadata and tagging taxonomy for infrastructure resources, applied consistently across Terraform, AWS, Docker/OCI images, GitHub, ArgoCD, Vault, Prometheus, Loki, and OpenTelemetry. Use when defining or reviewing tags, labels, or metadata on any of those platforms, designing a tagging strategy, or wiring up cost allocation and dashboards that depend on consistent keys. For Kubernetes workload labels the `helm` and `kubernetes` skills own the contract — this skill supplies the values they consume, it does not redefine the label set.
requires: [helm, kubernetes]
---

# Resource Tagging

## Load first

This skill owns the tag *vocabulary and values*, not each platform's key syntax. When the task
reaches Kubernetes, load the skills that own the keys these values feed:

- `helm` — the `_helpers.tpl` labels helper and the `patterns.md` component label that
  interpolate these values
- `kubernetes` — `resource-standards.md`, which fixes the required label set on every workload

For Terraform, AWS, OCI, GitHub, Vault, or observability targets, the mappings below are
self-contained.

## Why a canonical model

The common failure mode is per-platform tag vocabularies: `app_name` in one repo, `application` in another, `Application` (capitalized) in AWS console clicks, `app.kubernetes.io/name` in Helm charts that never makes it into Terraform. Once that happens, cost allocation, dashboards, and alerts can't join across platforms without a translation layer, and the translation layer rots.

The fix is a single canonical key *vocabulary*, defined once, then mapped onto each platform's native tagging mechanism. The mapping is mechanical — same concepts, same values, platform-native syntax.

## Ownership boundary — read before applying to Kubernetes

This skill owns the **vocabulary and the values**. It does not own every platform's key syntax.

| Surface | Who owns the keys | This skill's job |
|---|---|---|
| Kubernetes workload labels/selectors | `helm` (`_helpers.tpl` labels helper, `patterns.md` component label) and `kubernetes` (`resource-standards.md`) | Supply the *values* (`app`, `service`, `component`, `team`…) that the helpers interpolate. **Never** emit a competing bare-key label set alongside `app.kubernetes.io/*`. |
| ArgoCD Application/ApplicationSet metadata | `argo-applicationset` | Supply `owner`/`team` values for its `labels` and `managedNamespaceMetadata` blocks |
| Terraform resource tags | this skill | Full ownership — `locals.common_tags` + `merge()` |
| AWS, OCI image labels, GitHub, Vault, Prometheus/Loki/OTel | this skill | Full ownership |

The rule: **on Kubernetes, canonical keys with an `app.kubernetes.io/*` equivalent are expressed as that standard key.** Only keys with no upstream equivalent (`team`, `owner`, `cost-center`, `environment`…) appear as bare keys, and then as annotations unless something actually selects on them.

## Core rules

- **One vocabulary everywhere.** If a concept has a canonical key (`service`, `team`, `environment`…), use that concept on every platform. Don't let `svc`, `service_name`, and `service` coexist.
- **Never encode multiple values in one tag.** `service=payments`, `environment=prod`, `team=platform` — not `service=payments-prod-platform`. Compound tags can't be filtered, grouped, or aggregated on independently.
- **Distinguish identity tags from operational tags.** Identity (`app`, `service`, `component`, `team`) rarely changes. Operational (`version`, `git-sha`, `deployment`) changes on every release. Don't mix their lifecycles — and never put an operational key in a Kubernetes selector, which is immutable (see `helm`).
- **Lowercase kebab-case, no spaces, strings only** — `cost-center`, not `CostCenter` or `cost_center`. Tag keys get compared literally across tools that don't normalize case. Two documented exceptions: shell/CI env vars are upper-cased by convention, and `app.kubernetes.io/managed-by` carries a tool-cased value (see below).
- **Required vs optional.** Every resource gets the Tier 1 keys. Tiers 2–4 are added when the automation or reporting that consumes them actually exists — don't cargo-cult an `sla` tag if nothing reads it.

## Canonical taxonomy

### Tier 1 — Identity & ownership (required on every resource)

| Key | Example | Changes? | Kubernetes equivalent |
|---|---|---|---|
| `app` | `payments` | Rare | `app.kubernetes.io/part-of` |
| `service` | `api` | Rare | `app.kubernetes.io/name` |
| `component` | `worker` | Rare | `app.kubernetes.io/component` |
| `environment` | `prod` | Frequent | *(no standard key — bare `environment`, set per overlay)* |
| `team` | `platform` | Rare | *(no standard key — bare `team`)* |
| `owner` | `platform@company.com` | Sometimes | *(annotation — too long for a label)* |
| `managed-by` | `argocd` / `terraform` / `Helm` | Rare | `app.kubernetes.io/managed-by` |
| `repository` | `github.com/company/payments` | Rare | *(annotation — contains `/`)* |

**On `managed-by`:** the value names whatever actually reconciles *that* object, so it legitimately differs by surface. In-chart it is `{{ .Release.Service }}` → `Helm` (tool-cased, set by Helm itself — don't fight it). On an ArgoCD `Application` it is `argocd`. On a Terraform-provisioned resource it is `terraform`. Same key, honest value.

### Tier 2 — Operational (automation-facing)

| Key | Example | Kubernetes equivalent |
|---|---|---|
| `version` | `2.3.1` | `app.kubernetes.io/version` — **labels only, never selectors** |
| `git-sha` | `6cde812` | annotation |
| `deployment` | `blue` | bare key |
| `region` | `eu-central-1` | bare key |
| `cluster` | `prod-eu-1` | bare key |
| `namespace` | `payments` | intrinsic — don't duplicate as a label |
| `runtime` | `kubernetes` | intrinsic — omit |

### Tier 3 — Business (cost allocation)

| Key | Example |
|---|---|
| `cost-center` | `engineering` |
| `project` | `blockchain` |
| `product` | `analytics` |
| `customer` | `internal` |
| `compliance` | `pci` |
| `criticality` | `high` |

### Tier 4 — Lifecycle (automation triggers)

| Key | Example |
|---|---|
| `lifecycle` | `permanent` |
| `expiration` | `2026-12-31` |
| `backup` | `daily` |
| `sla` | `gold` |
| `tier` | `1` |

## Applying the taxonomy

1. Identify what's being tagged and pull the Tier 1 keys that apply — every resource gets `app`, `service`, `environment`, `team`, `managed-by` at minimum.
2. Add Tier 2/3/4 keys only for what a downstream consumer (Cost Explorer, a dashboard, an expiry cron) actually reads. An unused tag is noise.
3. Translate into the target platform's native mechanism using the mappings below — **values stay identical, keys become platform-native.**
4. If a new concept seems necessary that isn't in the taxonomy, add it here first (with a tier), rather than inventing a one-off for one platform.

## Platform mappings

### Kubernetes — defer to `helm` / `kubernetes`

Do not hand-write a label block. The chart's `_helpers.tpl` labels helper (see the `helm` skill) is the only place labels are composed; this skill supplies the values it reads. Canonical keys map onto the upstream recommended set:

```yaml
# Rendered by the chart's labels helper — shown for illustration, not to copy.
metadata:
  labels:
    app.kubernetes.io/name: api             # <- service
    app.kubernetes.io/instance: api-prod    # <- release name
    app.kubernetes.io/component: worker     # <- component (required per helm/patterns.md)
    app.kubernetes.io/part-of: payments     # <- app
    app.kubernetes.io/version: "2.3.1"      # <- version   (labels only, never selectors)
    app.kubernetes.io/managed-by: Helm      # <- managed-by (set by .Release.Service)
    team: platform                          # <- no upstream equivalent
    environment: prod                       # <- no upstream equivalent, set per env overlay
  annotations:
    owner: platform@company.com
    repository: github.com/company/payments
```

Wire the values in through chart values, not by templating extra labels:

```yaml
# values.yaml — consumed by the labels helper
partOf: payments        # -> app.kubernetes.io/part-of
podLabels:
  team: platform
  environment: ""       # set in <env>/values.yaml
```

`environment` belongs in the per-env overlay (`<env>/values.yaml`), never in the base `values.yaml` — same layering rule as everything else in the `helm` skill.

**Selector safety:** only `app.kubernetes.io/name`, `instance`, and `component` may appear in a selector. `version`, `git-sha`, and `deployment` change per release and selectors are immutable — putting them in a selector makes the workload un-upgradeable.

### Terraform

Define once as a local, apply everywhere via `merge()` so per-resource tags layer on top without redefining the common set.

```hcl
locals {
  common_tags = {
    app         = "payments"
    service     = "api"
    environment = var.environment
    team        = "platform"
    managed-by  = "terraform"
  }
}

resource "aws_instance" "example" {
  tags = merge(local.common_tags, {
    component = "worker"
  })
}
```

Prefer the provider's `default_tags` block where available, so a forgotten `tags =` still gets the common set:

```hcl
provider "aws" {
  default_tags { tags = local.common_tags }
}
```

### AWS

Same keys as tags directly on the resource — this is what makes Cost Explorer usable without a mapping layer:

```
app=payments
service=api
environment=prod
team=platform
project=blockchain
cost-center=engineering
managed-by=terraform
```

### Docker images (OCI labels)

Combine standard `org.opencontainers.image.*` labels with the canonical keys. Set these in CI from the build context, not hardcoded in the Dockerfile — `environment` in particular is not a property of an image:

```dockerfile
LABEL org.opencontainers.image.title="payments-api"
LABEL org.opencontainers.image.version="2.3.1"
LABEL org.opencontainers.image.source="https://github.com/company/payments"
LABEL app="payments"
LABEL service="api"
LABEL component="worker"
```

One image is promoted across environments, so **never bake `environment` into an image label** — that's what makes the artifact non-promotable.

### GitHub Actions

Repository variables and workflow env, same concepts, upper-cased only because shell env vars conventionally are:

```yaml
env:
  APP: payments
  SERVICE: api
  TEAM: platform
```

### ArgoCD

Application/ApplicationSet labels. The `argo-applicationset` skill owns the full metadata block (including `managedNamespaceMetadata`); supply the values:

```yaml
metadata:
  labels:
    app: payments
    environment: prod
    team: platform
    owner: platform        # argo-applicationset uses `owner` for the team handle
```

### Vault

Path structure carries identity; metadata carries the rest:

```
kv/prod/payments/

metadata:
  app=payments
  environment=prod
  owner=platform
```

### Observability (Prometheus, Loki, OpenTelemetry)

Prometheus and Loki use the canonical keys directly as labels — this is what makes a dashboard built for one service work unmodified for another:

```
app="payments"
service="api"
environment="prod"
cluster="prod-eu-1"
```

Keep cardinality in mind: `git-sha` and `version` as metric labels create a new time series per release. Use them as annotations/exemplars, not labels, unless you genuinely query by them.

OpenTelemetry has its own semantic-convention names for the same concepts — map to those rather than inventing custom resource attributes:

| Canonical key | OTel resource attribute |
|---|---|
| `service` | `service.name` |
| `app` (as namespace) | `service.namespace` |
| `component` | `service.instance.id` scope, or a custom attribute |
| `environment` | `deployment.environment.name` |
| `version` | `service.version` |
| `region` | `cloud.region` |
| `cluster` | `k8s.cluster.name` |

## Checklist for a new resource

- [ ] All Tier 1 keys present and non-empty
- [ ] No compound values (one concept per tag)
- [ ] Keys are lowercase kebab-case and match the canonical vocabulary, except the two documented exceptions (CI env vars, `managed-by` tool casing)
- [ ] Tier 2–4 keys added only where something consumes them
- [ ] Same `app`/`service`/`component`/`team`/`environment` **values** used across every platform this resource touches
- [ ] On Kubernetes: labels come from the chart's labels helper, not a hand-written block; no bare-key duplicate of an `app.kubernetes.io/*` key
- [ ] No operational key (`version`, `git-sha`, `deployment`) in any Kubernetes selector
- [ ] No `environment` baked into a container image label

## Companion skills — offer after completing

| Skill | Offer when |
|-------|-----------|
| `helm` | Chart labels helper doesn't yet expose `partOf` / `podLabels` for these values |
| `argo-applicationset` | ApplicationSet `labels` or `managedNamespaceMetadata` are missing `owner`/`team` |
| `terraform` | No `default_tags` or `locals.common_tags` in the Terraform project |

Ask as a single grouped question — not mid-task, not separately for each.
