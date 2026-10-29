---
name: argo-applicationset
description: Author ArgoCD ApplicationSets for service repos. Covers Go template syntax, matrix generators (apps × envs, apps × variants), values file layering, managedNamespaceMetadata labels, sync waves, singleton vs variant split, and the app-of-apps connection.
requires: [helm, kubernetes]
---

# ArgoCD ApplicationSet

## Load first

- `helm` — values file layering (`values.yaml` → `defaults/` → `<env>/`) that the ApplicationSet must mirror exactly
- `kubernetes` — resource standards, namespace labels, sync policy conventions

## What this skill covers

Authoring the ApplicationSet(s) that live in `deploy/argo/` and are synced by a parent app-of-apps in the platform repo. This skill does **not** cover the platform app-of-apps itself — that is a platform concern.

## How deploy/argo/ connects to ArgoCD

```
platform repo
└── argocd/sync/
    └── <project>-app.yaml        ← ApplicationSet (app-of-apps)
          source.path: deploy/argo
          source.repoURL: <service-repo>
          source.targetRevision: <branch>
```

ArgoCD syncs `deploy/argo/` and discovers every ApplicationSet file there. Each file becomes an ApplicationSet resource in the `argocd` namespace, which then generates Application CRs pointing at `deploy/charts/<app>`.

**Result**: adding a new chart to `deploy/charts/` + a list entry in the ApplicationSet is all that's needed to deploy a new service.

## File layout

```
deploy/argo/
├── applicationset.yaml     # services that vary by environment or a second axis
└── singletons.yaml         # services that deploy once with no variant axis
```

Split when a meaningful subset of services has no variant axis (e.g., a management console, a one-off job). A single `applicationset.yaml` is fine when everything varies the same way.

## Go templates — always

Go template syntax here is used for field substitution in ApplicationSet generator output (variable references like `{{ .app }}`, `{{ .env }}`). For Helm chart template patterns (conditionals, named helpers, `toYaml`) see the `helm` skill.

Use `goTemplate: true` on every ApplicationSet. The legacy `{{app}}` syntax is deprecated and less expressive.

```yaml
spec:
  goTemplate: true
  goTemplateOptions:
    - missingkey=default   # missing keys render as empty string, not an error
```

With Go templates, fields use `{{ .fieldName }}` instead of `{{fieldName}}`.

## Generator patterns

### Pattern A — apps × envs

One Application per service per environment:

```yaml
generators:
  - matrix:
      generators:
        - list:
            elements:
              - app: api
                namespace: backend
                wave: "10"
              - app: worker
                namespace: backend
                wave: "10"
        - list:
            elements:
              - env: dev
              - env: prod
```

Template name: `{{ .app }}-{{ .env }}`  
Values: `{{ .env }}/values.yaml`

### Pattern B — apps × second axis (variant)

One Application per service per variant — used when a service is deployed once per region, tenant, shard, or any other repeating dimension. The variant is just a key in the list element:

```yaml
generators:
  - matrix:
      generators:
        - list:
            elements:
              - app: data-processor
                wave: "10"
              - app: api-gateway
                wave: "10"
        - list:
            elements:
              - variant: us-east
              - variant: eu-west
              - variant: ap-south
```

Template name: `{{ .variant }}-{{ .app }}`  
Values: `dev/{{ .variant }}.yaml` (variant-specific overrides within the environment)

The variant key name is yours to choose (`region`, `tenant`, `shard`, `chain`, etc.) — name it after what it actually represents in your domain.

### Pattern C — singletons (no variant axis)

Single list generator, no matrix:

```yaml
generators:
  - list:
      elements:
        - app: management-console
          namespace: platform
          wave: "5"
        - app: metrics-exporter
          namespace: monitoring
          wave: "5"
```

Template name: `{{ .app }}`

### Combining patterns in one file

Use multiple top-level generator entries (ArgoCD merges their outputs) to handle mixed topologies — some services vary by a second axis, others don't:

```yaml
generators:
  - matrix:                      # variant services
      generators:
        - list:
            elements:
              - app: data-processor
                wave: "10"
        - list:
            elements:
              - variant: us-east
              - variant: eu-west
  - list:                        # singletons alongside
      elements:
        - app: management-console
          namespace: platform
          wave: "5"
```

## Canonical ApplicationSet template

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: <project>-apps
  namespace: argocd
  annotations:
    argocd.argoproj.io/refresh: hard
    description: "One-line description of what this ApplicationSet manages"
  labels:
    owner: <team>
    argocd.argoproj.io/instance: <project>   # groups apps in ArgoCD UI
spec:
  goTemplate: true
  goTemplateOptions:
    - missingkey=default

  generators:
    - matrix:
        generators:
          - list:
              elements:
                - app: my-service
                  namespace: backend
                  wave: "10"
          - list:
              elements:
                - env: dev
                - env: prod

  template:
    metadata:
      name: "{{ .app }}-{{ .env }}"
      annotations:
        argocd.argoproj.io/sync-wave: "{{ .wave }}"
        argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
        argocd.argoproj.io/wave-verification: "true"
      labels:
        argocd.argoproj.io/instance: <project>
        owner: <team>
    spec:
      project: default
      source:
        repoURL: https://github.com/<org>/<repo>
        targetRevision: <branch>            # see targetRevision section below
        path: "deploy/charts/{{ .app }}"
        helm:
          releaseName: "{{ .app }}-{{ .env }}"
          valueFiles:
            - values.yaml
            - defaults/values.yaml
            - "{{ .env }}/values.yaml"
          ignoreMissingValueFiles: true
      destination:
        name: local                         # or server: https://kubernetes.default.svc
        namespace: "{{ .namespace }}"
      syncPolicy:
        automated: {}
        managedNamespaceMetadata:
          labels:
            owner: <team>
            audit.kubernetes.io/enabled: "true"
            backup.velero.io/backup: "true"
            pod-security.kubernetes.io/audit: restricted
            pod-security.kubernetes.io/enforce: restricted
            pod-security.kubernetes.io/enforce-version: latest
            pod-security.kubernetes.io/warn: restricted
            pod-security.kubernetes.io/warn-version: latest
            policies.kyverno.io/enforce: "false"
            quota.kubernetes.io/enforced: "false"
            monitoring: "true"
        syncOptions:
          - Validate=true
          - CreateNamespace=true
          - ApplyOutOfSyncOnly=true
          - ServerSideApply=true
          - Wait=true
```

## targetRevision

| Strategy | When to use |
|---|---|
| Static branch (`main`, `deploy`) | Service repo where CI pushes image tag updates to a deploy branch |
| `HEAD` | Same-repo GitOps where the branch is the source of truth |
| Cluster label (`{{ index .metadata.labels "targetRevision" }}`) | Platform/multi-cluster repos where different clusters track different revisions |

The `deploy` branch strategy is common: `main`/`develop` holds application source and `deploy` holds CI-updated values (image tags). ArgoCD watches `deploy`.

## Values file wiring

The `valueFiles` list must match exactly what `helm template` and `task template:<env>` use. The canonical layer ordering and its rationale live in the `helm` skill.

```yaml
valueFiles:
  - values.yaml
  - defaults/values.yaml
  - "{{ .env }}/values.yaml"
ignoreMissingValueFiles: true     # always — not every chart has an override for every env
```

When a second axis adds per-variant overrides:

```yaml
valueFiles:
  - values.yaml
  - defaults/values.yaml
  - "{{ .env }}/values.yaml"
  - "{{ .env }}/{{ .variant }}.yaml"
ignoreMissingValueFiles: true
```

## Naming conventions

| Pattern | Template name | releaseName |
|---|---|---|
| service only | `{{ .app }}` | `{{ .app }}` |
| service + env | `{{ .app }}-{{ .env }}` | `{{ .app }}-{{ .env }}` |
| variant + service | `{{ .variant }}-{{ .app }}` | `{{ .app }}-{{ .variant }}` |
| variant + service + env | `{{ .variant }}-{{ .app }}-{{ .env }}` | `{{ .app }}-{{ .variant }}-{{ .env }}` |

Application names must be unique across the cluster — include enough dimensions in the name to guarantee uniqueness. `releaseName` must be stable: changing it recreates all Helm-managed resources.

## Sync waves

Add a `wave` field to each list element and reference it in the template annotation. Waves order creation within a sync operation:

```yaml
elements:
  - app: schema-migrator     # must complete before the app starts
    namespace: backend
    wave: "0"
  - app: api
    namespace: backend
    wave: "10"
  - app: worker
    namespace: backend
    wave: "10"
```

Negative waves run before the default (wave 0). Use them for CRDs, operators, and namespaces that downstream resources depend on.

## managedNamespaceMetadata — standard labels

Always include on every ApplicationSet that creates namespaces (`CreateNamespace=true`). These labels control PSA enforcement, Kyverno policies, quota, backup, and monitoring:

```yaml
managedNamespaceMetadata:
  labels:
    owner: <team>
    audit.kubernetes.io/enabled: "true"
    backup.velero.io/backup: "true"
    monitoring: "true"
    # Pod Security Admission — choose one profile:
    pod-security.kubernetes.io/enforce: restricted      # default for services
    # pod-security.kubernetes.io/enforce: privileged    # for system components only
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/warn-version: latest
    # Policy gates — off by default, enabled selectively:
    policies.kyverno.io/enforce: "false"
    quota.kubernetes.io/enforced: "false"
```

`privileged` PSA only for system-level DaemonSets (CNI, CSI, monitoring agents). Everything else uses `restricted`.

## syncPolicy

```yaml
syncPolicy:
  automated: {}              # selfHeal and prune default to false — intentional
  syncOptions:
    - Validate=true
    - CreateNamespace=true
    - ApplyOutOfSyncOnly=true    # only sync resources that are out of sync
    - ServerSideApply=true       # required for large CRDs and field managers
    - Wait=true                  # wait for resources to be healthy before next wave
```

**`prune: false`** (the default) — do not auto-delete resources removed from Git. Prevents accidental data loss. Set explicitly to `true` only for stateless resources you are certain about.

**`SkipDryRunOnMissingResource=true`** belongs on the Application annotation, not in syncOptions:

```yaml
annotations:
  argocd.argoproj.io/sync-options: SkipDryRunOnMissingResource=true
```

## ignoreDifferences

Add when a controller mutates fields that ArgoCD would otherwise flag as out of sync:

```yaml
spec:
  ignoreDifferences:
    - group: ""
      kind: Secret
      jsonPointers:
        - /metadata/annotations
    - group: admissionregistration.k8s.io
      kind: ValidatingWebhookConfiguration
      jsonPointers:
        - /webhooks/0/clientConfig/caBundle
```

Common candidates: PVC annotations (storage controllers), webhook caBundle (cert-manager injects), Namespace annotations (label controllers).

## Process

1. Identify which services have a variant axis and which are singletons
2. Decide file split: one file or `applicationset.yaml` + `singletons.yaml`
3. Name the variant key after what it represents in your domain
4. Write generators — verify mentally that the matrix produces the expected application names
5. Wire `valueFiles` to match exactly what `task template:<env>` uses
6. Set `namespace` per element or derive it with a Go template expression
7. Choose `targetRevision` strategy
8. Verify with: `argocd appset generate deploy/argo/applicationset.yaml` (dry-run, no cluster needed)
9. Commit and confirm ArgoCD picks up the ApplicationSet from `deploy/argo/`

## Checklist

- [ ] `goTemplate: true` and `missingkey=default` on every ApplicationSet
- [ ] Application names are unique across the cluster (include all variant dimensions)
- [ ] `releaseName` is stable and matches the Helm convention
- [ ] `valueFiles` order matches `task template:<env>` exactly
- [ ] `ignoreMissingValueFiles: true` on every Helm source
- [ ] `managedNamespaceMetadata` present on every ApplicationSet that creates namespaces
- [ ] PSA profile is appropriate (`restricted` for services, `privileged` only for system components)
- [ ] `prune` is explicitly set (or intentionally left as default false)
- [ ] `description` annotation is present and meaningful
- [ ] `argocd.argoproj.io/instance` label is consistent across all ApplicationSets in this project

## Companion skills — offer after completing

| Skill | Offer when |
|-------|-----------|
| `helm` | Chart in `deploy/charts/<app>/` is missing or incomplete |
| `kubernetes` | Resource standards (security context, probes, limits) not yet applied to charts |
| `ci` | No CI workflow updating image tags in values files and pushing to the deploy branch |
