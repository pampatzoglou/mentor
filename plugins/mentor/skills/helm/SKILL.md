---
name: helm
description: Helm chart authoring — chart anatomy, values file layering (values.yaml → defaults/ → env/ → overlay), _helpers.tpl, template foundations, and local validation.
---

# Helm — Foundations

Helm packages Kubernetes workloads as charts. This file covers chart structure, values organization, helpers, and validation. For template patterns, workload variants, observability, and operational requirements see `patterns.md`. For Kubernetes resource-level standards (security context, probes, resource limits) see the `kubernetes` skill's `resource-standards.md`.

## Do you need a new chart?

Before scaffolding:
- If a similar chart exists, **extend it with a values overlay** — don't fork.
- A one-off Job or debug pod doesn't need a chart — a plain manifest is fine.
- A new chart is justified when the workload has >3 resources, needs per-environment values, or will be reused across teams.

When Helm is the wrong tool entirely:

| Situation | Use instead |
|---|---|
| Simple static manifests, single environment | Raw YAML or Kustomize |
| Platform-level resources managed by operators | Operator CRs directly (CNPG, Strimzi, etc.) |
| Heavy chart logic with many conditionals | Reconsider the design — charts should configure, not program |
| Library chart with no templates | A shared `_helpers.tpl` snippet included via chart dependency |

## Chart layout

```
my-chart/
├── Chart.yaml
├── values.yaml              # scaffold defaults — chart works on kind out of the box
├── values.schema.json       # recommended — catches typos and wrong types at lint time
├── defaults/
│   └── values.yaml          # DRY operational baseline — true for every cluster deployment
├── dev/
│   ├── values.yaml          # dev env deltas
│   └── <variant>.yaml       # optional — one per variant/chain/tenant
├── prod/
│   ├── values.yaml
│   └── <variant>.yaml
├── templates/
│   ├── _helpers.tpl
│   ├── deployment.yaml      # or cronjob.yaml, statefulset.yaml
│   ├── service.yaml
│   ├── serviceaccount.yaml
│   ├── rbac.yaml            # Role/RoleBinding — only when the workload calls the API
│   ├── networkpolicy.yaml   # ingress/egress segmentation
│   ├── configmap.yaml       # non-secret config — behind config.enabled
│   ├── secrets.yaml
│   ├── hpa.yaml
│   ├── pdb.yaml
│   ├── servicemonitor.yaml  # or podmonitor.yaml — behind metrics.enabled
│   ├── prometheusrule.yaml  # behind metrics.enabled
│   ├── extra-manifests.yaml
│   └── NOTES.txt
└── README.md
```

### Variant overlay axis

When the same chart is deployed multiple times per environment (per blockchain, per tenant, per region), each variant gets its own overlay file under `<env>/<variant>.yaml`. The ArgoCD ApplicationSet matrix generator produces the cross-product: `charts × envs × variants`.

To disable a variant in a specific environment, set `replicaCount: 0` in its overlay file — never in the base `values.yaml`. The base chart must always be deployable standalone on a local kind cluster with `replicaCount: 1`.

## Values file layering

Precedence — later overrides earlier:

```
values.yaml → defaults/values.yaml → <env>/values.yaml → <env>/<variant>.yaml
```

| Layer | Purpose |
|---|---|
| `values.yaml` | Scaffold defaults with commented-out recommended shapes. Chart works on kind with just this file. |
| `defaults/values.yaml` | Operational baseline: pull secrets, security context, pod labels, reloader annotation, common volumes. Anything true for every cluster deployment. |
| `<env>/values.yaml` | Environment-specific deltas: hostnames, resource sizes, ExternalSecret names, monitoring opt-ins. |
| `<env>/<variant>.yaml` | Variant-specific overrides: replica count, chain/tenant config, topic names, RPC endpoints. Set `replicaCount: 0` here to disable. |

**Mental test before adding a value:** true in two or more environments? → `defaults/`. Environment-specific? → `<env>/values.yaml`. Variant-specific? → `<env>/<variant>.yaml`. Copy-pasting the same value into both dev and prod is a signal to promote it to `defaults/`.

## Chart.yaml

```yaml
apiVersion: v2
name: my-chart
description: One-line description of what this deploys.
type: application
version: 0.1.0          # bump on every change — ArgoCD uses this for change detection
appVersion: "1.0.0"     # tracks the actual application version — not the scaffold default
kubeVersion: ">=1.28.0"
maintainers:
  - name: team-name
```

Bump `version` on every change, even non-breaking ones. Both ArgoCD and Helm use it to detect that something changed.

Set `appVersion` to the real application version. Don't leave the `helm create` default (`"1.16.0"`) — it's meaningless and misleading.

Ensure `name` matches the chart directory name. A mismatch breaks ArgoCD and confuses everyone.

**Chart dependencies** (`dependencies:` in `Chart.yaml`) pull in sub-charts at `helm dependency update` time. Use them for shared `_helpers.tpl` logic packaged as a library chart (`type: library`) or bundling a sidecar chart. Do **not** use chart dependencies as a replacement for ArgoCD `ApplicationSet` — each independently deployed component gets its own chart.

## values.yaml — structure and style

### Grouping by resource boundary

Group values by the Kubernetes resource or external dependency they configure. Each block should be self-contained: connection config + credentials + ExternalSecret toggle together. An ops person reading the values should see exactly which Secret they're configuring without cross-referencing other sections.

```yaml
# -- Replica count. Base chart defaults to 1 for local kind development.
# -- Set >= 2 for HA — PDB and topology spread activate automatically.
replicaCount: 1

image:
  repository: ""
  tag: ""                # pin to tag or digest; never 'latest'
  digest: ""             # optional — sha256 digest for immutable deploys
  pullPolicy: IfNotPresent

# -- Database connection and credentials.
# -- Maps to the `-db` Secret, DB_* env vars, and /var/run/secrets/db/* files.
database:
  host: ""
  port: "5432"
  database: ""
  username: "postgres"
  password: "postgres"
  mountPath: /var/run/secrets/db    # always mounted; files: .../db/<key>
  externalSecret:
    enable: false
    name: ""                 # name of a pre-existing Secret
    usernameKey: username
    passwordKey: password
  vault:
    enable: false
    method: GET
    provider:
      server: http://vault.vault:8200
      version: v2
    resultType: Data    
    path: ""                 # Vault path — active when top-level vault.enable: true
    usernameKey: username        # key name in the Vault-generated Secret
    passwordKey: password
    refreshInterval: "1h"

# -- Kafka connection and SASL credentials.
# -- Maps to the `-kafka` Secret and KAFKA_* env vars.
kafka:
  brokers: ""
  securityProtocol: "SASL_PLAINTEXT"
  sasl:
    mechanism: SCRAM-SHA-512
    username: ""
    password: ""
    mountPath: /var/run/secrets/kafka    # always mounted; files: .../kafka/<key>
    externalSecret:
      enable: false
      name: ""                           # name of a pre-existing Secret
      usernameKey: username
      passwordKey: password
    vault:
      enable: false
      method: GET
      provider:
        server: http://vault.vault:8200
        version: v2
      resultType: Data
      path: ""                           # e.g. "kafka/creds/my-role"
      usernameKey: username
      passwordKey: password
      refreshInterval: "1h"

# -- Chart-level Vault Kubernetes auth — shared by all credential blocks.
# -- Each credential block's vault.provider.server carries its own Vault URL.
vault:
  mountPath: kubernetes      # Vault Kubernetes auth mount
  role: ""                   # Vault role — must have bound_service_account_names + bound_service_account_namespaces set
```

The **`secrets` skill owns this contract** — the three source modes below, the Vault path convention, the `/var/run/secrets/<block>/<key>` mount path, and the `*_FILE` env naming that `docker-compose` must match exactly. Read it before adding or changing a credential block; the templates that implement it are in `postgres.md` and `kafka.md`.

Each top-level resource block maps 1:1 to a credential source:

| Mode | Activated by | What renders |
|---|---|---|
| Chart-internal | `database.vault.enable: false` + `externalSecret.enable: false` | Secret with inline `user`/`password` values |
| External reference | `database.vault.enable: false` + `externalSecret.enable: true` | Nothing — references a pre-existing Secret by name |
| Vault dynamic | `database.vault.enable: true` + `vault.path` set | VaultDynamicSecret + ExternalSecret |

See `postgres.md` for the full database template chain and `kafka.md` for Kafka SASL. See `patterns.md` for general patterns (extraObjects, file mounts, multi-secret naming).

### Commented-out recommended values

Features are off by default but include the recommended production shape as comments. This serves as both documentation and a copy-paste starting point for env overlays.

**This is a statement about the base layer only.** `resources: {}` in `values.yaml` is correct — the base chart has no way to know a workload's CPU/memory profile, and it must still render on a bare kind cluster. It is *not* correct in the rendered output: `defaults/values.yaml` or the env overlay must fill it in, and the `kubernetes` skill flags an empty `resources` in a rendered manifest as blocker-tier. Same field, two layers, two verdicts — check which layer you're looking at before calling it a finding.

```yaml
resources: {}
# resources:
#   requests:
#     cpu: 100m
#     memory: 128Mi
#   limits:
#     cpu: "1"
#     memory: 512Mi

autoscaling:
  enabled: false
#   minReplicas: 2
#   maxReplicas: 10
#   targetCPUUtilizationPercentage: 80
#   behavior:
#     scaleDown:
#       stabilizationWindowSeconds: 300

pdb:
  enabled: false
#   enabled: true
#   maxUnavailable: 1

metrics:
  enabled: false
# metrics:
#   podMonitor:
#     enabled: true
#     interval: 30s
#     additionalLabels:
#       release: prometheus
#   prometheusRule:
#     enabled: true
#     rules:
#       - alert: HighErrorRate
#         expr: rate(http_errors_total[5m]) > 0.05
#         for: 10m
```

### Feature toggle pattern

Use `enabled: false` at the top of feature sections and guard the entire Kubernetes resource with `{{- if .Values.<feature>.enabled }}`. Don't guard individual lines inside a resource.

**Anything that would block or complicate local development defaults off in the base `values.yaml`** — NetworkPolicy, strict egress restrictions, `rbac.clusterScope`, ExternalSecret-only credentials. The base chart must deploy on a bare `kind` cluster (and work alongside `docker-compose`) with just `values.yaml`. Put the real rules in the base file as commented examples, and switch them on in `defaults/values.yaml` or the per-env overlay — never in the base.

### Standard infrastructure keys

Every chart should define these (even if empty) so overlays can set them without knowing whether the chart "supports" them:

```yaml
nameOverride: ""
fullnameOverride: ""
partOf: ""               # app.kubernetes.io/part-of — the larger app/suite; defaults to chart name
imagePullSecrets: []
podAnnotations: {}
podLabels: {}
podSecurityContext: {}
securityContext: {}
nodeSelector: {}
affinity: {}
tolerations: []
topologySpreadConstraints: []
priorityClassName: ""
volumes: []
volumeMounts: []
extraObjects: []
```

Set `podSecurityContext` and `securityContext` values from the `kubernetes` skill's `resource-standards.md` — don't invent security context defaults here.

### ServiceAccount

```yaml
serviceAccount:
  create: true
  automount: false       # default false — only true when the workload calls the API server
  annotations: {}
  name: ""
```

Default `automount: false`. Workloads that don't talk to the Kubernetes API shouldn't have a token mounted.

## values.schema.json

Recommended for charts with complex or user-facing values. Catches typos and wrong types at `helm lint` / `helm template` time — before manifests reach the cluster. Not every chart needs one on day one, but add one when values grow beyond a handful of keys or when multiple teams consume the chart:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["image"],
  "properties": {
    "replicaCount": {
      "type": "integer",
      "minimum": 0
    },
    "image": {
      "type": "object",
      "required": ["repository"],
      "properties": {
        "repository": { "type": "string" },
        "tag":        { "type": "string" },
        "pullPolicy": {
          "type": "string",
          "enum": ["Always", "IfNotPresent", "Never"]
        }
      }
    }
  }
}
```

Cover required keys and any key whose type is easy to get wrong. You don't need to be exhaustive.

## _helpers.tpl

Every chart defines at minimum these **seven** helpers. The last two carry the
`app.kubernetes.io/component` label that `patterns.md` requires on every workload — they are
not optional extras for multi-workload charts only. Label even a single-workload chart, because
adding a component label to a live Deployment's selector later forces a delete/recreate.

```gotmpl
{{- define "my-chart.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "my-chart.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "my-chart.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "my-chart.labels" -}}
helm.sh/chart: {{ include "my-chart.chart" . }}
{{ include "my-chart.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: {{ .Values.partOf | default (include "my-chart.name" .) }}
{{- end }}

{{- define "my-chart.selectorLabels" -}}
app.kubernetes.io/name: {{ include "my-chart.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* Component-scoped variants — use these in every workload and its dependent objects.
     Call as: (dict "root" . "component" "server") */}}
{{- define "my-chart.componentLabels" -}}
{{ include "my-chart.labels" .root }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "my-chart.componentSelectorLabels" -}}
{{ include "my-chart.selectorLabels" .root }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}
```

**Selector labels must not include version.** Selectors on Deployments and StatefulSets are immutable — baking the version in means you can't upgrade without deleting and recreating the workload.

**Which helper goes where.** `componentLabels` on `metadata.labels` and the pod template;
`componentSelectorLabels` in `spec.selector.matchLabels` for Deployments and StatefulSets, and
in the selector of every Service/PDB/ServiceMonitor/NetworkPolicy that targets that workload.
Jobs and CronJobs get `componentLabels` only — they generate their own controller-owned
selector and overriding it is unsupported. Full rules and rationale in `patterns.md`,
*Component label — required on every workload*.

Add a `serviceAccountName` helper when the chart creates a ServiceAccount:

```gotmpl
{{- define "my-chart.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "my-chart.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}
```

Add a `render` helper for `extraObjects` support (see patterns.md):

```gotmpl
{{- define "my-chart.render" -}}
  {{- if typeIs "string" .value -}}
    {{- tpl .value .context }}
  {{- else -}}
    {{- tpl (.value | toYaml) .context }}
  {{- end -}}
{{- end -}}
```

## Template foundations

These patterns apply to Helm chart templates. For Go template usage in ArgoCD ApplicationSet generators (`{{ .app }}`, `{{ .env }}`, matrix generators) see the `argo-applicationset` skill.

**Conditional resource** — guard the whole resource, not individual lines:
```gotmpl
{{- if .Values.autoscaling.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
...
{{- end }}
```

**Required values:**
```gotmpl
{{ required "image.repository is required" .Values.image.repository }}
```

**Pass-through structs** — use `toYaml` for blocks the user fully controls:
```gotmpl
resources:
  {{- toYaml .Values.resources | nindent 12 }}
```

Never `printf` YAML structure — it breaks on edge cases.

**`toYaml` vs `tpl(toYaml)`** — use plain `toYaml` for values that are static data (resources, nodeSelector, tolerations, affinity). Use `tpl (toYaml .) $` when values may contain Go template expressions — specifically `topologySpreadConstraints` (label selectors referencing chart helpers), `hostnames` (domain names with environment interpolation), and `extraObjects`:

```gotmpl
{{- toYaml .Values.resources | nindent 12 }}           # static — plain toYaml
{{- tpl (toYaml .) $ | nindent 8 }}                    # dynamic — tpl wrapping
```

## Local validation

Prefer `task template:dev` when a Taskfile is present — it matches exactly what CI and ArgoCD use. Falling back to raw helm:

```bash
helm template my-release ./my-chart \
  --namespace my-namespace \
  --include-crds \
  -f values.yaml \
  -f defaults/values.yaml \
  -f dev/values.yaml
```

Stricter checks:
```bash
helm lint ./my-chart
helm template ... | kubeconform -strict -summary
```

Things to look for in rendered output:
- No `<no value>` strings
- Consistent indentation (no `nindent` off-by-one)
- `spec.selector.matchLabels` ⊂ `metadata.labels`
- CRDs render before the resources that depend on them
- Chart renders cleanly with just `values.yaml` (no overlays) for local kind use

## NOTES.txt

Optional but recommended. Rendered after `helm install` / `helm upgrade` to show useful post-install information:

```gotmpl
{{- $fullName := include "my-chart.fullname" . -}}
1. Application deployed: {{ $fullName }}
   Namespace: {{ .Release.Namespace }}

2. Check status:
   kubectl get pods -l app.kubernetes.io/instance={{ .Release.Name }} -n {{ .Release.Namespace }}
```

Include kubectl commands to verify the deployment, access logs, or port-forward to the service. Keep it short — this is what the operator sees immediately after deploy.

## .helmignore

Exclude non-chart files from the Helm package to keep it clean and avoid leaking development artifacts:

```
.DS_Store
.git/
.gitignore
.idea/
.vscode/
*.swp
*.bak
*.tmp
*.orig
*~
__pycache__/
*.pyc
chart/
docs/
README.md
```

Include `README.md` in `.helmignore` — it's for humans reading the repo, not for the Helm package. Include language-specific artifacts (`__pycache__/`, `node_modules/`, etc.) relevant to the project.

## Completion checklist

- [ ] Chart renders cleanly with `helm template` or `task template:dev`
- [ ] Chart renders and deploys on local kind with just `values.yaml` (no overlays needed)
- [ ] `Chart.yaml` version bumped; `appVersion` reflects real application version; `name` matches directory
- [ ] Values grouped by resource boundary — each block maps to one Secret / one set of env vars
- [ ] Every knob has a default; recommended production shapes are commented out
- [ ] Feature sections use `enabled: false` guard pattern
- [ ] `_helpers.tpl` defines name, fullname, chart, labels, selectorLabels, componentLabels, componentSelectorLabels
- [ ] Common labels include `app.kubernetes.io/part-of` (in the labels helper, not selectorLabels)
- [ ] Every workload carries a unique `app.kubernetes.io/component`; Deployments/StatefulSets have it in the selector, Jobs/CronJobs in labels only
- [ ] Dependent objects (Service, PDB, ServiceMonitor, NetworkPolicy) select on the same component label as the workload they target
- [ ] Selector labels don't include version
- [ ] No bare-key label duplicating an `app.kubernetes.io/*` key (see the `tagging` skill)
- [ ] `serviceAccount.automount` defaults to `false`
- [ ] `extraObjects: []` present for charts reused across teams
- [ ] All scheduling fields present in templates: nodeSelector, affinity, tolerations, topologySpreadConstraints, priorityClassName
- [ ] See `patterns.md` checklist for workload-specific items

## Companion skills — offer after completing

When chart work is done, check the repo and offer whichever of these are missing or incomplete:

| Skill | Offer when |
|-------|-----------|
| `skaffold` | No `skaffold.yaml` and the project has a local dev use case |
| `devbox` | No `devbox.json` in the repo root |
| `document` | No `docs/ARCHITECTURE.md`, or chart `README.md` is missing or minimal |

Ask as a single grouped question — not mid-task, not separately for each.
