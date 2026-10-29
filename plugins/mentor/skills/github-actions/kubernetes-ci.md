# GitHub Actions — Kubernetes CI

## Contents

- [Standard matrix](#standard-matrix)
- [Render check](#render-check)
- [Third-axis matrix (when applicable)](#third-axis-matrix-when-applicable)
- [Canonical Kubernetes ci.yaml](#canonical-kubernetes-ciyaml)
- [Branch protection](#branch-protection)
- [Common Kubernetes CI failures](#common-kubernetes-ci-failures)

Companion to `SKILL.md` (foundations: core pattern, security, matrix, caching). This file covers **PR-time** CI for repos that deploy Helm charts — lint, template, and audit run as a matrix over environments. For the **merge-time** deploy half (promoting image tags into a GitOps repo) see `cross-repo-promotion.md`.

## Standard matrix

```yaml
strategy:
  fail-fast: false    # see all environment failures at once
  matrix:
    env: [dev, prod]
```

## Render check

`.argo/` is a gitignored build artifact — ArgoCD renders `deploy/charts/<app>` itself via the
ApplicationSet's `helm.valueFiles` (see the `argo-applicationset` skill). So there is nothing
to compare against a committed copy; the job's value is proving the chart *renders* for every
environment before merge, and handing the output to `kubescape`.

```yaml
- run: task template:${{ matrix.env }}
- name: Verify the render produced manifests
  run: |
    if [ -z "$(find .argo/${{ matrix.env }} -name '*.yaml' -print -quit 2>/dev/null)" ]; then
      echo "::error::task template:${{ matrix.env }} produced no manifests."
      exit 1
    fi
```

> Do **not** gate on `git diff .argo/`. `git diff` only reports modifications to *tracked*
> files, so freshly rendered files are invisible to it, and on a gitignored path the check
> passes unconditionally — it reads as a guarantee while asserting nothing.

## Third-axis matrix (when applicable)

If the repo uses a third-axis overlay (chain, region, tenant), add it to the matrix:

```yaml
matrix:
  env: [dev, prod]
  chain: [variant1, variant2]

steps:
  - run: task template:${{ matrix.env }} CHAIN=${{ matrix.chain }}
```

## Canonical Kubernetes ci.yaml

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint-charts:
    name: lint (${{ matrix.env }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        env: [dev, prod]
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: ./.github/actions/setup-tools
        with:
          helm: "true"
      - run: task lint:${{ matrix.env }}

  template-charts:
    name: template (${{ matrix.env }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        env: [dev, prod]
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: ./.github/actions/setup-tools
        with:
          helm: "true"
      - run: task template:${{ matrix.env }}
      - name: Verify the render produced manifests
        run: |
          if [ -z "$(find .argo/${{ matrix.env }} -name '*.yaml' -print -quit 2>/dev/null)" ]; then
            echo "::error::task template:${{ matrix.env }} produced no manifests."
            exit 1
          fi

  audit-charts:
    name: audit (${{ matrix.env }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        env: [dev, prod]
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: ./.github/actions/setup-tools
        with:
          helm: "true"
          kubeconform: "true"
          kubescape: "true"
      - run: task audit:${{ matrix.env }}

  test:
    name: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: ./.github/actions/setup-tools
      - run: task test
```

## Branch protection

Require all matrix job names as separate required checks: `lint (dev)`, `lint (prod)`, `template (dev)`, `template (prod)`, `audit (dev)`, `audit (prod)`, `test`.

## Common Kubernetes CI failures

| Failure | Cause |
|---|---|
| `lint failed` on one chart | Missing required value in `defaults/values.yaml` |
| render check finds no manifests | Every chart failed to template, or `CHARTS_DIR` doesn't match the repo layout |
| `audit` fails with kubescape findings | Fix the manifest or add to `.kubescape/exceptions.json` with a `reason` |
