---
name: skaffold
description: Skaffold + kind for local development inner loop. Image sideloading to kind without a registry, canonical skaffold.yaml, devbox cluster scripts, and when skaffold is and isn't the right tool.
requires: [devbox, helm]
---

# Skaffold (local dev with kind)

## Load first

Before starting, load these skills:

- `devbox` — tool pinning, `.envrc`, cluster lifecycle scripts (`cluster:up`, `cluster:reset`)
- `helm` — chart structure and values layering that `valuesFiles` must match exactly

Skaffold provides the inner dev loop: edit → rebuild → kind picks up the new image → pod rolls. It targets a local `kind` cluster only. All other environments go through ArgoCD off committed manifests.

## Mental model

```
developer machine
├── kind cluster   (local k8s, managed via devbox scripts)
└── docker daemon  (shared with kind for image sideloading)
```

Loop:
1. Build image locally with docker
2. **Sideload** into kind (`kind load docker-image`) — no registry push, no round-trip
3. Render Helm chart with dev values
4. Apply rendered manifests to kind cluster
5. Watch source for changes → repeat

## Prerequisites

Use the Kubernetes tooling package list and cluster lifecycle scripts from the `devbox` skill — it includes `skaffold`, `kind`, `helm`, `kubectl`, and the `cluster:up` / `cluster:down` / `cluster:reset` scripts. Don't duplicate the package list here.

Each developer runs `devbox run cluster:up` once. The cluster persists between sessions until explicitly deleted.

## Canonical skaffold.yaml

```yaml
apiVersion: skaffold/v4beta11
kind: Config
metadata:
  name: my-service

build:
  local:
    push: false           # sideload to kind, never push to a registry
    useBuildkit: true
  artifacts:
    - image: my-service   # bare local name — no registry prefix needed for kind
      context: .
      docker:
        dockerfile: Dockerfile
        target: develop   # REQUIRED — see "Build the develop stage" below
      sync:
        manual: []        # add infer patterns here for hot-reload without full rebuild

manifests:
  helm:
    releases:
      - name: my-service
        chartPath: deploy/charts/my-service
        valuesFiles:
          - deploy/charts/my-service/values.yaml
          - deploy/charts/my-service/defaults/values.yaml
          - deploy/charts/my-service/dev/values.yaml
        setValueTemplates:
          image.repository: '{{.IMAGE_REPO_my_service}}'
          image.tag: '{{.IMAGE_TAG_my_service}}'

deploy:
  kubeContext: kind-dev   # fail fast if pointed at the wrong cluster
```

## Build the develop stage

`target: develop` is not optional. Omitting it makes Docker build the **last** stage in the
Dockerfile — which the `dockerfile` skill defines as `production`: distroless, no shell, no
hot-reload daemon, read-only rootfs. Skaffold will happily sideload it and the pod will run,
so the failure is quiet: you get an inner loop that never reloads, and `skaffold dev`'s file
sync has nothing to sync into.

The `develop` stage exists precisely for this and for `docker-compose` — both consume the
same stage, so the image is identical across the two local loops.

| Symptom | Cause |
|---|---|
| Edits don't appear without a full rebuild | `target: develop` missing — you're running `production` |
| `exec: "sh": executable file not found` on `skaffold debug` | Same — distroless has no shell |

## Image naming for kind

Use a bare local name (`my-service`, no registry prefix). In `dev/values.yaml`, override image settings so kind serves the sideloaded image:

```yaml
image:
  repository: my-service    # matches the artifact image name above
  pullPolicy: IfNotPresent  # use what's sideloaded — don't pull
imagePullSecrets: []        # disable registry pull secrets from defaults/
```

## Common usage

```bash
skaffold dev      # build + deploy + watch + tail logs (primary inner loop)
skaffold run      # one-shot build + deploy without watching
skaffold render   # render manifests skaffold would apply, without applying
skaffold delete   # tear down what skaffold deployed
```

## Behavior notes

- **Values ordering must match `task template:<env>`** — if `task template:dev` works but `skaffold dev` doesn't, check that `valuesFiles` are in the same order with the same files.
- **Sideloading takes a few seconds per rebuild.** Use multi-stage Dockerfiles and `sync.infer` for source-only changes that don't need a full rebuild.
- **Skaffold doesn't know about ArgoCD.** Resources placed in the kind cluster are unrelated to what ArgoCD reconciles — keep the kind cluster in separate namespaces.
- **Profiles are for local dev variations** (overlay selection, debug builds), not for targeting different clusters.

## Chart-specific configuration

### dev/values.yaml overrides for kind

```yaml
image:
  repository: my-service    # bare local name, matches the skaffold artifact name
  pullPolicy: IfNotPresent  # use what's sideloaded — don't pull from registry
imagePullSecrets: []        # disable registry pull secrets set in defaults/values.yaml
```

### Third-axis overlay profiles (optional)

For charts with a third-axis overlay (chain, region, tenant), add a Skaffold profile that appends the overlay values file:

```yaml
profiles:
  - name: <overlay-value>
    patches:
      - op: add
        path: /manifests/helm/releases/0/valuesFiles/-
        value: deploy/charts/my-service/dev/<overlay-value>.yaml
```

Activate with `skaffold dev -p <overlay-value>`. Profiles are local dev variations only — never use them to target real clusters.

## When skaffold isn't the right tool

| Goal | Use instead |
|---|---|
| Render manifests for a PR check | `task template:<env>` |
| Test against the real dev/staging cluster | Push branch, let ArgoCD sync |
| Run unit or integration tests | `task test` via language test runner |
| Deploy to any cluster ArgoCD manages | Commit + ArgoCD sync |

## Companion skills — offer after completing

When skaffold setup is done, check the repo and offer whichever of these are missing or incomplete:

| Skill | Offer when |
|-------|-----------|
| `helm` | No Helm chart exists alongside the skaffold config |
| `devbox` | No `devbox.json` in the repo root |
| `document` | No `docs/ARCHITECTURE.md` or README doesn't describe the local dev loop |

Ask as a single grouped question — not mid-task, not separately for each.
