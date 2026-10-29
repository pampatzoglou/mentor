# Team Conventions

This file describes a specific team's GitOps platform conventions. Apply these only when the user is working in a repo that follows them. Tells:
- A `defaults/values.yaml` next to environment dirs (`dev/`, `prod/`) inside a chart
- ArgoCD `Application`/`ApplicationSet` files with `argocd.argoproj.io/sync-wave` annotations
- References to `linstor-csi-lvm` (storage class) or `linstor-scheduler`
- A `Taskfile.yaml` (go-task) with `template`, `lint`, and `audit` tasks taking `ENV` / `CHART_NAME` (and the team's `CHAIN` overlay variable) variables

If none of these match, ignore this file and use the generic guidance in the other references.

## Two repo types

The team uses two distinct repo layouts. Identify which one before suggesting any structural changes.

### Platform repo

A monorepo of cluster-level components. **Top-level folders are namespaces**; each namespace contains one or more charts.

```
platform-repo/
├── cert-manager/                 # ← namespace
│   └── cert-manager/             # ← chart (same name is fine)
│       ├── Chart.yaml
│       ├── values.yaml
│       ├── defaults/values.yaml
│       ├── dev/values.yaml
│       ├── prod/values.yaml
│       └── templates/
├── monitoring/                   # ← namespace with multiple charts
│   ├── prometheus/               # ← chart
│   │   ├── Chart.yaml
│   │   ├── values.yaml
│   │   ├── defaults/values.yaml
│   │   ├── dev/values.yaml
│   │   └── ...
│   └── grafana/                  # ← chart
│       └── ...
├── argo/                         # ArgoCD Applications + ApplicationSets for the platform
│   └── *.yaml
├── Taskfile.yaml
└── ...
```

Rules:
- The folder name at the top level **is** the Kubernetes namespace. If the chart deploys to `monitoring`, it lives under `monitoring/`. No exceptions — `external-dns` deploys to namespace `external-dns`, etc.
- A namespace can contain multiple charts (e.g., `monitoring/datadog` and `monitoring/grafana`). The chart folder name is free-form.
- `argo/` at the top level holds the ArgoCD `Application`/`ApplicationSet` resources that point at these charts.

### Services repo

A repo containing a team's service(s) and its deployment manifests alongside the application code.

```
my-service-repo/
├── src/                          # application code
├── deploy/
│   ├── charts/
│   │   ├── my-service/           # primary chart
│   │   │   ├── Chart.yaml
│   │   │   ├── values.yaml
│   │   │   ├── defaults/values.yaml
│   │   │   ├── dev/values.yaml
│   │   │   ├── dev/variant.yaml          # optional overlay (see below)
│   │   │   ├── prod/values.yaml
│   │   │   ├── prod/variant.yaml
│   │   │   └── templates/
│   │   └── my-service-worker/    # additional charts allowed (worker, cron, etc.)
│   │       └── ...
│   └── argo/                     # ApplicationSets ONLY — see below
│       └── *.yaml
├── Taskfile.yaml
└── ...
```

Rules:
- `deploy/charts/` can contain multiple charts. Use this for separating concerns (main API + background worker + cron jobs) rather than stuffing everything into one mega-chart.
- Chart folder names are free-form; they don't have to match the repo name.
- **`deploy/argo/` holds `ApplicationSet` resources only — no individual `Application` files.** Per-chart Applications are generated from the ApplicationSet. If you find yourself wanting to write an `Application` directly, that's a signal to extend the ApplicationSet instead.

### Why the split

- **Platform repo**: ArgoCD bootstraps the cluster from this repo, so it needs to know about every namespace and CRD wave explicitly. Folder-as-namespace makes the topology obvious.
- **Services repo**: lives with the application code so devs can ship app + manifest changes in the same PR. ApplicationSets keep deployment configuration uniform across environments without per-env Application drift.

## Values file hierarchy

The three layers serve distinct purposes — putting a value in the wrong one is a common mistake.

```
<chart>/
├── values.yaml              # helm create scaffold + commented placeholders
├── defaults/values.yaml     # DRY layer: true in every cluster deployment
├── dev/values.yaml          # dev-specific deltas only
├── dev/<variant>.yaml         # optional variant overlay (services repo only, certain charts)
├── prod/values.yaml         # prod-specific deltas only
└── prod/<variant>.yaml        # optional variant overlay
```

**Precedence (later overrides earlier):** `values.yaml` → `defaults/values.yaml` → `<env>/values.yaml` → `<env>/<chain>.yaml` (when applicable).

The two cluster environments are `dev` (shared dev cluster used as staging) and `prod`. Both are real clusters and follow the same precedence — there is no local-only environment in the values overlay.

### What goes in each layer

**`values.yaml`** — the framework defaults from `helm create`, plus commented-out placeholders.
- Don't put real config here.
- When the chart introduces a new templated feature (e.g., a `prometheusRules` block, an `ingress` section), add commented-out example values in `values.yaml` showing the shape. This makes `values.yaml` double as inline documentation of every knob the chart exposes.
- Example:
  ```yaml
  # prometheusRules:
  #   enabled: true
  #   rules:
  #     - alert: HighErrorRate
  #       expr: rate(http_errors_total[5m]) > 0.05
  #       for: 10m
  ```

**`defaults/values.yaml`** — the DRY layer. Anything true for every cluster deployment of this chart.
- Image pull secrets, container registry hosts
- Default security context overrides the chart applies on top of upstream
- Common labels and annotations
- Monitoring opt-ins that should always be on
- Sensible request/limit defaults the team standardized on

**`<env>/values.yaml`** — strictly environment-specific deltas.
- Replica count (1 in dev, 3+ in prod)
- Hostnames (`api.dev.example.com` vs `api.example.com`)
- Resource sizes that legitimately differ per env
- Per-env credential references (`ExternalSecret` names — never literal credentials)
- Per-env feature flags

### Mental test for placement

Before adding a value to `<env>/values.yaml`, ask: **is this value true in two or more environments?**
- If yes → it belongs in `defaults/values.yaml`
- If no → keep it in `<env>/values.yaml`

This prevents the most common drift: copy-pasting the same setting into both env files. If you find yourself doing that, stop — promote it to `defaults/`.

## CHAIN overlay (this team's third-axis values overlay)

This team's services run the same workload against multiple blockchains, so a third-axis overlay variable named `CHAIN` is added to the Taskfile on top of the canonical `ENV` + `CHART_NAME` axes. This is a specific instance of the generic "third-axis overlay" pattern described in the `taskfile` skill — other teams that need a third axis pick their own name (`REGION`, `TENANT`, etc.).

Layout for chain-aware charts:

```
<chart>/
├── dev/
│   ├── values.yaml           # base dev values (applied to every chain)
│   ├── variant1.yaml               # dev + variant
│   └── variant2.yaml              # dev + variant
└── prod/
    ├── values.yaml
    ├── variant1.yaml
    └── variant2.yaml
```

Precedence (later overrides earlier):
```
values.yaml → defaults/values.yaml → <env>/values.yaml → <env>/<chain>.yaml
```

The Taskfile reads `CHAIN=<name>` and appends `<env>/<chain>.yaml` after the env file. Skipped silently when the chain file doesn't exist — charts that aren't chain-aware are unaffected.

Rules:
- **Chain-aware charts only.** Most charts in the repo don't have chain files; the Taskfile skips the overlay for them automatically.
- **Services repo only.** The platform repo doesn't have chains.
- **Don't duplicate across chain files.** If a value is the same for every chain in an env, promote it to `<env>/values.yaml`. Same DRY principle as `defaults/` vs `<env>/`.

CI matrix for this team includes the chain axis — see the `github-actions` skill "Kubernetes CI" section for the pattern.

## ArgoCD sync waves

Wave ordering (lower waves apply first; ArgoCD waits for each wave to be healthy before proceeding):

| Wave | Tier | What goes here |
|------|------|----------------|
| -10 | Absolute prerequisites | CRDs that everything else depends on (e.g., `datadog-crds`) |
| -8 | Security foundations | `external-secrets`, `vault`, anything that provides credentials to other components |
| -5 | Networking essentials | `cert-manager`, `external-dns`, Gateway API CRDs |
| 0 | Core operators | `cnpg`, `strimzi`/`redpanda`, `clickhouse-operator` — operators that own database/queue CRDs |
| 3 | Monitoring stack | `datadog`, `trivy`, `grafana`, `prometheus` |
| 5 | Platform tools | `reloader`, `kubescape`, `velero`, supporting utilities |
| 10+ | Workloads | Actual user-facing applications (services-repo charts default here) |

Set on each `Application` (or `ApplicationSet` template) with:
```yaml
metadata:
  annotations:
    argocd.argoproj.io/sync-wave: "-5"
```

When in doubt about a new component's wave, ask: "what would break if this came up *before* its dependencies finished?" That answer points to the right tier.

## ApplicationSet pattern (services repo)

Services repos use `ApplicationSet` to generate one `Application` per chart × environment. This avoids hand-maintaining N Applications and is the only allowed pattern in `deploy/argo/`.

A minimal generator over the `deploy/charts/` directory. The `argo-applicationset` skill owns
the full canonical template (sync options, `managedNamespaceMetadata`, `targetRevision`
strategies) — this is the trimmed shape, and it must stay consistent with that skill:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: my-service
  namespace: argocd
spec:
  goTemplate: true                    # always — legacy {{path}} syntax is deprecated
  goTemplateOptions: [missingkey=default]
  generators:
    - matrix:
        generators:
          - git:
              repoURL: <repo>
              revision: main
              directories:
                - path: deploy/charts/*
          - list:
              elements:
                - env: dev
                - env: prod
  template:
    metadata:
      name: '{{ .path.basename }}-{{ .env }}'
      annotations:
        argocd.argoproj.io/sync-wave: "10"
    spec:
      project: workloads
      source:
        repoURL: <repo>
        path: '{{ .path.path }}'
        helm:
          valueFiles:
            - values.yaml
            - defaults/values.yaml
            - '{{ .env }}/values.yaml'
          ignoreMissingValueFiles: true
      destination:
        server: https://kubernetes.default.svc
        namespace: my-service-{{ .env }}
      syncPolicy:
        automated: { selfHeal: true }   # prune omitted => false; see argo-applicationset
```

Single source of truth: change the ApplicationSet, and every generated Application updates.

**`prune` stays off.** `prune: true` lets a chart deletion cascade into deleting live
resources — including PVCs. Enable it per-Application only for genuinely stateless
components, as the `argo-applicationset` skill describes.

## Templating locally

Use `task template:dev` (or `task template:prod`) — the `action:env` form the `taskfile`
skill defines. This is equivalent to:

```bash
helm template <release> deploy/charts/<chart> \
  -f deploy/charts/<chart>/values.yaml \
  -f deploy/charts/<chart>/defaults/values.yaml \
  -f deploy/charts/<chart>/<env>/values.yaml \
  -f deploy/charts/<chart>/<env>/<variant>.yaml \   # only when CHAIN is set and the file exists
  --output-dir .argo/<env>
```

`.argo/` is a gitignored local render artifact. ArgoCD does **not** read it — the
ApplicationSet points at `deploy/charts/<chart>` and renders the chart itself (see the
`argo-applicationset` skill). Rendering locally is how you review what the cluster will
get before pushing.

## Priority classes

- `high` — for critical platform components (operators, ingress controllers, CNI). Use sparingly; abusing this causes preemption storms.
- Default (no `priorityClassName`) — for everything else.

## Component placement: which wave for what

A handful of common cases:

| Component | Wave | Reason |
|---|---|---|
| `external-secrets` operator | -8 | Other components reference its CRDs (`ExternalSecret`, `SecretStore`) |
| `cert-manager` + ClusterIssuers | -5 | Certificates referenced by ingresses in wave 10+ |
| `velero` | 5 | Backup tooling — runs after the things it backs up exist |
| Application charts (services repo) | 10+ | Actual user-facing services |

## CRD handling

CRDs go in dedicated charts (`*-crds`) at low waves. Don't bundle CRDs into the same chart that uses them — Helm's `crds/` directory has unhelpful upgrade behavior, and ArgoCD wave ordering needs them as a separate Application anyway.

## Pre-commit checks

Before opening a PR:

```bash
# Snapshot the current render, make your change, then compare
task template:dev && cp -r .argo/dev /tmp/argo-before

# ... edit the chart ...

task template:dev && diff -ru /tmp/argo-before .argo/dev
```

`.argo/` is gitignored, so `git diff .argo/` shows nothing — compare against a snapshot
instead. The rendered diff is the clearest view of what your chart change actually does to
the cluster, so review it alongside the source change, not instead of it.
