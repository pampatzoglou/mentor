---
name: dockerfile
description: 'Generate a 4-stage Dockerfile (base → build → develop/production) and a matching .dockerignore: layer-cache ordering, a develop stage for the docker-compose/skaffold inner loop, and a distroless/slim production stage with an explicit non-root user, --chown on every COPY, declared VOLUMEs and a digest-locked base image. Use when writing, reviewing or fixing a Dockerfile or .dockerignore, containerizing a service, choosing a base image, or acting on hadolint/trivy findings. Triggers on Dockerfile, .dockerignore, "containerize", "docker build", "multi-stage", distroless.'
license: Apache-2.0
---

# Generate Dockerfile

Generate a 4-stage Dockerfile and matching `.dockerignore` by analyzing the project's language, framework, dependencies, and entry point.

## The 4-stage model

```
                       ┌──► develop      (dev tooling + hot-reload CMD;
base ──► build ────────┤                  used by docker-compose & skaffold)
  │   (deps + compile, └──► production   (distroless/slim, non-root, --chown,
  │    cache-ordered)                      VOLUME, artifacts COPY --from=build)
  └─ OS deps, CA certs, WORKDIR
```

| Stage | Purpose | Who uses it |
|---|---|---|
| `base` | OS packages, CA certs, `WORKDIR` — no app code, no user | shared foundation for every downstream stage |
| `build` | Install dependencies and compile/transpile, ordered for layer caching (manifests → deps → source → build) | produces the artifacts both `develop` and `production` consume |
| `develop` | `FROM build` + dev tooling (hot-reload daemon, debugger) and the dev `CMD` | docker-compose, skaffold local dev |
| `production` | Slim/distroless + explicit non-root user + artifacts `COPY --from=build` with `--chown` + VOLUME | CI image push, cluster deployments |

`build` is the cache-optimisation layer: because dependency install happens before the source `COPY`, editing code re-runs only the compile step, not the (slow) dependency resolution.

## Non-negotiable rules

1. **Verify before adding.** Read the actual source files and manifests before writing any instruction. Never assume a package is needed. Ask if uncertain.
2. **Architecture-agnostic through `develop`.** `base`, `build`, and `develop` must build natively on any builder — an arm64 laptop and amd64 CI from the same Dockerfile. Use multi-arch official images, never hardcode `amd64`/`arm64`/`x86_64`, and detect arch dynamically (`TARGETARCH`, `uname -m`) for any binary download. For a compiled language, cross-compile from the native builder rather than emulating the target — see *Cross-compiling for multi-arch* in the build stage. Production keeps this property too, but is additionally locked — see rule 6.
3. **No HEALTHCHECK.** Health endpoints are application-specific and cannot be verified from analysis. Users add their own.
4. **Explicit non-root user in production.** On distroless (the default choice) use the built-in `nonroot` account and switch with numeric `USER 65532:65532`; on Alpine/Debian create an `app` user. Either way every production `COPY` carries `--chown` matching that exact uid, and `USER` comes before `CMD`. **The uid here is the single source of truth** — compose `user:` and the chart's `runAsUser`/`runAsGroup`/`fsGroup` mirror it, never the reverse.
5. **Explicit COPY everywhere.** Never `COPY . .` in any stage — copy only what each stage needs.
6. **Pin base images; lock production to a digest.** Never `:latest` — derive the version from project files. The `production` runtime base should be pinned by digest (`FROM …@sha256:…`), preferably the **multi-arch manifest-list digest** so it stays arch-agnostic (rule 2) while being immutable and reproducible. Dev-side stages (`base`/`build`/`develop`) can pin by tag for convenience; production is the one that gets pushed and deployed, so it gets the digest lock. Tags drift; digests don't.
7. **Production is read-only; writable paths are declared `VOLUME`s.** The production image is built to run with a read-only root filesystem. Every directory the app writes to at runtime (`/tmp`, caches, work dirs) must be declared with `VOLUME`. That list is a **breadcrumb for whoever writes the deployment** — it travels with the image, survives in `docker inspect`, and tells the chart author and the compose author exactly which writable mounts to create. No runtime reads it for you: Kubernetes ignores Dockerfile `VOLUME` outright, and Docker turns each one into an anonymous volume. Enforcement comes from `readOnlyRootFilesystem: true` plus explicit mounts; the `VOLUME` list is what makes those mounts reviewable instead of archaeological. Declare them anyway — see *Read-only root filesystem* below.

---

## Step 0: check for existing files

Before generating, check if `Dockerfile` and `.dockerignore` already exist and read them. If they exist, audit against this skill's patterns and improve rather than overwrite.

---

## Step 1: analyse the project

Read thoroughly before writing a single line. Shallow analysis produces broken Dockerfiles.

### 1.1 Language and runtime version

Find the language from source file extensions and dependency manifests (`go.mod`, `package.json`, `requirements.txt`/`pyproject.toml`, `Cargo.toml`, `Gemfile`, etc.). Extract the required runtime version from:
- Version files (`.nvmrc`, `.python-version`, `.tool-versions`)
- Manifest engine constraints (`engines.node` in `package.json`, `python_requires` in `pyproject.toml`)
- CI configuration
- `devbox.json` packages

If no version is found, look up the current LTS/stable.

### 1.2 Application type

Trace the entry point and its imports to determine what the app does:
- **HTTP service** — look for port binding, route registration, server start
- **Worker / consumer** — look for queue consumers, scheduled tasks
- **CLI tool** — look for argument parsing, `os.Args`, `click`, `cobra`, etc.
- **Static site** — look for build output config, no server code

Application type determines the develop CMD, the production entry point, and whether EXPOSE is appropriate.

### 1.3 Build requirements

- Does the app need a compile/transpile step? (Go → binary, TS → JS, Rust → binary)
- What is the build command? (verify in the manifest or Taskfile)
- What is the output? (binary path, `dist/` dir, `.next/`, etc.)

### 1.4 System dependencies

Search the codebase for calls to external binaries (`exec`, `subprocess`, `os.system`, `Command`, etc.). Every binary the app calls at runtime must be present in the production image. When in doubt, ask.

### 1.5 Environment variables

Search for env var reads (`os.Getenv`, `process.env`, `os.environ`, `std::env::var`). Check `.env.example` or `.env.sample` for documented variables. Distinguish required (no default, app fails) from optional (has fallback).

### 1.6 Port

Search for port binding with concrete evidence. Only add `EXPOSE` if a port is found. Never guess.

### 1.7 Writable paths at runtime

Search for file writes, temp file creation, log file writes, and cache directories. Common patterns: `os.TempDir()`, `ioutil.TempFile`, `tempfile.mktemp`, `/tmp/`, `/var/cache/`, `/var/log/`. Every writable path that isn't a mounted volume in the container runtime must be declared with `VOLUME` in the Dockerfile.

### 1.8 Integration with skaffold / docker-compose

Check for `skaffold.yaml` and `docker-compose.yaml`. Note which build target they use (or should use) and what volumes they mount. The `develop` stage must match what these tools expect.

---

## Step 2: write the Dockerfile

### Stage 1 — `base`

```dockerfile
# syntax=docker/dockerfile:1
# ── base ──────────────────────────────────────────────────────────────────────
# Shared OS foundation: packages and CA certs. No application code, no app user.
FROM <language-image>:<version>-<variant> AS base

# Install only OS-level packages required at both dev and runtime.
# Clean cache in the same layer.
RUN <pkg-manager> install -y --no-install-recommends \
        <package-1> \
        <package-2> && \
    <clean-cache-command>

WORKDIR /app
```

**Base stage rules:**
- Multi-arch official images only (official images are multi-arch by default).
- Only packages needed by both develop and production. Dev-only tools go in develop; any production-only runtime library goes in production.
- Set `WORKDIR /app` here so it's inherited.
- Do **not** create the app user here — each downstream stage has different security requirements.

### Stage 2 — `build`

```dockerfile
# ── build ─────────────────────────────────────────────────────────────────────
# Install dependencies and compile. Ordered for layer caching: manifests → deps →
# source → build, so a source-only change doesn't reinstall dependencies.
FROM base AS build

# Build-time tools not needed at runtime (compilers, headers, codegen).
RUN <install-build-tools>

# 1. Dependency manifests FIRST — this layer is cached until the manifests change.
COPY <manifest-files> ./
RUN <install-all-deps>      # include dev/build deps; production starts clean anyway

# 2. Source SECOND — editing code doesn't bust the dependency layer above.
COPY <src-dir> ./

# 3. Build the artifact to a well-known path.
RUN <build-command>         # e.g. go build -o /app/server .  |  npm run build  |  cargo build --release
```

**Build stage rules:**
- **Manifests before source.** Copy dependency manifests and install deps *before* the source `COPY`. This is the whole point of the stage — a code edit then re-runs only the build layer, not the slow dependency install.
- Install everything the compile needs here; build tools never reach the final image because `production` starts from a clean runtime base.
- Emit a predictable artifact path (`/app/server`, `/app/dist`, a wheel) that both downstream stages consume.
- With BuildKit, add `RUN --mount=type=cache,target=<pkg-cache>` for the package-manager/compiler cache (Go build cache, `~/.npm`, pip cache) to speed repeat builds further.

#### Private dependency registries — build secrets, never layers

A token needed to *install dependencies* is still a secret: `ARG NPM_TOKEN` lands in the image
history, and an `ENV`/`COPY`-then-delete stays in the layer that added it. Use a BuildKit secret
mount, which is present only for the lifetime of that `RUN` and never becomes a layer:

```dockerfile
# syntax=docker/dockerfile:1
RUN --mount=type=secret,id=npm_token \
    NPM_TOKEN="$(cat /run/secrets/npm_token)" npm ci --omit=dev
```

```bash
docker build --secret id=npm_token,env=NPM_TOKEN .    # from the environment
docker build --secret id=npm_token,src=./token .      # from a file
```

The `/run/secrets/<id>` above is BuildKit's own flat build-time mount and has nothing to do with
the runtime layout at `/var/run/secrets/<block>/<key>` — different mechanism, different lifetime,
and the built image contains neither.

- **SSH-based Go/Git deps** use the agent mount instead: `RUN --mount=type=ssh git config --global url."git@github.com:".insteadOf "https://github.com/" && go mod download`, built with `docker build --ssh default`.
- **In CI**, feed the secret from the OIDC-obtained short-lived token, not a long-lived PAT — the `github-actions` skill owns that wiring.
- **Never** `ARG`/`ENV` a token, and never `COPY` a credential file into any stage. The `secrets` skill's "Never" list applies to build time as much as runtime.
- Build secrets are for *fetching dependencies*. A runtime credential never enters the image at all — it arrives as a mounted file at `/var/run/secrets/<block>/<key>` (the `secrets` skill).

#### Cross-compiling for multi-arch

When production is built for more than one platform (`docker buildx build --platform linux/amd64,linux/arm64`), the naive Dockerfile runs the entire build stage under QEMU for the foreign arch — often 5–10× slower, and a frequent source of mysterious toolchain failures. For a compiled language, run the build stage **natively on the builder** and cross-compile to the target:

```dockerfile
FROM --platform=$BUILDPLATFORM golang:1.23-alpine AS build
ARG TARGETOS TARGETARCH          # provided automatically by BuildKit
...
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -o /app/server .
```

- `BUILDPLATFORM` is the machine doing the build; `TARGETOS`/`TARGETARCH`/`TARGETPLATFORM` describe what is being built for. Declare the `ARG`s in each stage that uses them — they don't cross stage boundaries.
- The `production` stage stays plain `FROM <runtime>@sha256:…` (no `--platform`): buildx selects the right arch from the manifest list per target, which is why rule 6 wants the manifest-list digest.
- **Only for languages that cross-compile cleanly** — Go and Rust (with the target installed). For cgo, Python wheels with native extensions, or anything invoking a platform-specific toolchain, drop the `--platform=$BUILDPLATFORM` and let buildx emulate, or build each arch on a native runner and merge with `docker buildx imagetools create`.
- `develop` and `base` remain plain `FROM` — they are built natively for the developer's own machine (rule 2), never cross-compiled.

### Stage 3 — `develop`

```dockerfile
# ── develop ───────────────────────────────────────────────────────────────────
# Built on top of build, so deps, source, and artifacts are already present and
# cached. Adds hot-reload tooling and the dev entry point.
# Used by docker-compose (bind mount for hot reload) and skaffold (sideloaded to kind).
FROM build AS develop

# Dev-only tooling: hot-reload daemon, test runner, debugger.
RUN <install-dev-tools>

# Dev entry point: hot-reload or direct run.
# docker-compose overrides this with a volume mount; skaffold uses it directly.
CMD ["<dev-entry-point>"]    # e.g., air, nodemon, uvicorn --reload, go run .
```

**Develop stage rules:**
- `FROM build` — reuses the cached dependency and compile layers; no second install.
- Add only tools that must NOT ship in production (hot reload, debuggers, test runners).
- The `CMD` is the dev entry point — docker-compose may override it; skaffold sideloads this image and expects it to start the service.

**docker-compose target:**
```yaml
services:
  app:
    build:
      context: .
      target: develop
    volumes:
      - .:/app               # mount source for hot reload
    ports:
      - "8080:8080"
```

**skaffold target:**
```yaml
build:
  artifacts:
    - image: my-service
      docker:
        dockerfile: Dockerfile
        target: develop
```

### Stage 4 — `production`

```dockerfile
# ── production ────────────────────────────────────────────────────────────────
# Minimal runtime: explicit non-root user, --chown on every COPY, declared VOLUMEs.
# Lock to a digest (preferably the multi-arch manifest list) — immutable + arch-agnostic.
FROM <runtime-image>:<version>@sha256:<digest> AS production

# Create a dedicated non-root user and group.
# Alpine syntax:
RUN addgroup -S app && adduser -S app -G app
# Debian/slim syntax (use one or the other, matching the base image):
# RUN groupadd --system app && useradd --system --gid app --no-create-home app

WORKDIR /app

# Copy artifacts from the build stage with explicit ownership.
# --chown ensures files are owned by app:app from the moment they enter the layer,
# not by root with a later USER switch — this is the minimal-attack-surface pattern.
#
# For compiled languages (single binary):
COPY --from=build --chown=app:app /app/<binary> /app/<binary>
#
# For interpreted languages (copy selectively — never the full build stage):
# COPY --from=build --chown=app:app /app/<prod-deps-dir> /app/<prod-deps-dir>
# COPY --from=build --chown=app:app /app/<src-dir> /app/<src-dir>

# Declare every directory the application writes to at runtime.
# In Kubernetes with readOnlyRootFilesystem: true, mount these as emptyDir volumes.
VOLUME ["/tmp"]
# Add others as needed: VOLUME ["/var/cache/app", "/var/log/app"]

USER app

EXPOSE <port>      # only if verified in Step 1.6

CMD ["<executable>", "<arg>"]    # exec form always — never shell form in production
```

**Production user patterns by base image:**

| Base image | Create user | COPY ownership |
|---|---|---|
| Alpine | `RUN addgroup -S app && adduser -S app -G app` | `--chown=app:app` |
| Debian slim | `RUN groupadd --system app && useradd --system --gid app --no-create-home app` | `--chown=app:app` |
| Distroless (preferred) | No `RUN` possible — use built-in `nonroot` user (uid 65532) | `--chown=65532:65532` or `--chown=nonroot:nonroot` |

**On distroless, don't create a user — use the one it ships.** `nonroot` (uid/gid `65532`) already exists in every `*:nonroot` distroless tag, and `65532` is the value the whole toolchain expects: compose `user:`, and the chart's `runAsUser`/`runAsGroup`/`fsGroup` (see `resource-standards.md`). Reaching for a named `app` user here buys nothing and is the usual source of a uid mismatch.

```dockerfile
FROM gcr.io/distroless/static-debian12:nonroot AS production
WORKDIR /app
COPY --from=build --chown=65532:65532 /app/binary /app/binary
VOLUME ["/tmp"]
USER 65532:65532          # numeric — resolves without /etc/passwd
CMD ["/app/binary"]
```

Prefer the **numeric** `USER 65532:65532` over `USER nonroot`: a numeric uid needs no `/etc/passwd` lookup, and Kubernetes `runAsNonRoot: true` validates a numeric uid without having to resolve a name.

If a *named* `app` user is genuinely required (some third-party tooling insists), copy the account database from a helper stage and keep every uid reference identical:

```dockerfile
FROM alpine:3.21 AS user-setup
# Pin the uid explicitly — `adduser -S` otherwise picks the first free system id,
# which won't match the --chown below.
RUN addgroup -S -g 65532 app && adduser -S -u 65532 -G app app

FROM gcr.io/distroless/static-debian12 AS production
COPY --from=user-setup /etc/passwd /etc/group /etc/
COPY --from=build --chown=65532:65532 /app/binary /app/binary
USER app
```

The failure this avoids: copying with `--chown=65534:65534` (that's `nobody`, not `nonroot`) and then `USER app` at some third uid — the process can't read its own binary, and the error is a bare permission denied.

**Production image selection:**

| Language | Preferred | Fallback |
|---|---|---|
| Go (static binary) | `gcr.io/distroless/static-debian12:nonroot` | `alpine:3.21` |
| Go (with cgo) | `gcr.io/distroless/base-debian12:nonroot` | `debian:12-slim` |
| Python | `gcr.io/distroless/python3-debian12:nonroot` | `python:3.x-slim` |
| Node.js | `gcr.io/distroless/nodejs22-debian12:nonroot` | `node:22-alpine` |
| Java | `gcr.io/distroless/java21-debian12:nonroot` | `eclipse-temurin:21-jre-alpine` |
| Rust (static) | `gcr.io/distroless/static-debian12:nonroot` | `alpine:3.21` |
| Generic binary | `gcr.io/distroless/base-debian12:nonroot` | `debian:12-slim` |

Use distroless unless the app requires a shell, a package manager, or system tools at runtime.

The distroless `nonroot` uid 65532 aligns with `runAsUser: 65532` in the `kubernetes` skill's `resource-standards.md`. **The Dockerfile `USER` is the single source of truth for the UID** — the docker-compose `user:` and the chart's `runAsUser`/`runAsGroup`/`fsGroup` both mirror this exact value. Change it here, and update those in the same commit.

**OCI labels — static in the Dockerfile, volatile from CI.**

Three labels are properties of the image itself and belong in the `production` stage; everything
that changes per build comes from CI via `--label`, because a value baked into the Dockerfile is a
value that goes stale silently:

```dockerfile
LABEL org.opencontainers.image.title="my-service" \
      org.opencontainers.image.source="https://github.com/org/my-service" \
      org.opencontainers.image.licenses="Apache-2.0"
```

```bash
# CI adds the rest from the build context — never hardcode these
docker build \
  --label org.opencontainers.image.version="$VERSION" \
  --label org.opencontainers.image.revision="$GIT_SHA" \
  --label org.opencontainers.image.created="$BUILD_TIME" .
```

The **`tagging` skill owns the label taxonomy** — which keys exist, what they mean, and the
canonical `app`/`service`/`component`/`owner` set that pairs with the OCI ones. Don't invent label
keys here. Never put `environment` on an image: the same digest is promoted across environments,
so it isn't a property of the artifact.

**Architecture-agnostic binary downloads** (when a binary must be fetched from a URL):
```dockerfile
RUN ARCH=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/') && \
    curl -fsSL "https://example.com/releases/tool-linux-${ARCH}.tar.gz" | tar -xz -C /usr/local/bin
```

Never hardcode `amd64`, `x86_64`, or `arm64` in a URL or path.

---

## Read-only root filesystem — the writable-paths contract

Production runs with a read-only root filesystem. Every path the app writes is declared as a
`VOLUME` in the Dockerfile — that list is the single source of truth — and mounted identically
everywhere: `tmpfs`/named volume plus `read_only: true` in compose, `emptyDir`/PVC plus
`readOnlyRootFilesystem: true` in Kubernetes. `VOLUME` declares, it does not enforce; read
[read-only-rootfs.md](read-only-rootfs.md) for what it does and doesn't do and how to apply it.

---

## Step 3: write the .dockerignore

The `.dockerignore` serves speed (keep large generated dirs out of the context) and security
(keep secrets out even by accident). Read [dockerignore.md](dockerignore.md) for the section menu;
emit only the sections that apply to this project.

---

## Step 4: build, run, validate

Build both targets, verify the production and develop images, lint with hadolint and scan with
trivy when available, iterate (max 5 rounds), and clean up. Follow [validation.md](validation.md)
step by step, including its symptom → cause table. Only present the Dockerfile after every step
passes and cleanup is done.

---

## Step 5: present and document

### For new Dockerfiles

Present both files to the user:

1. **Dockerfile** — with comments explaining each stage and any non-obvious decision
2. **.dockerignore** — with section headers

Then provide:
- Brief explanation of design choices (base image selection, why distroless vs slim, how writable paths were identified)
- Build commands for both targets
- docker-compose snippet with `target: develop` and volume mount
- skaffold snippet with `target: develop` (if `skaffold.yaml` is present or expected)
- How to use in CI: `docker build -t <name>:<tag> .` (production by default)
- Required environment variables or build args, with defaults and setup instructions

### For improved Dockerfiles

Present the improved files with a summary:

1. **Dockerfile** — improved version
2. **Changes made** — brief list of what changed and why:
   - Security fixes (e.g., "Added `--chown=app:app` to all COPYs — files were owned by root")
   - Pattern fixes (e.g., "Moved user creation to production stage — develop doesn't need it")
   - Missing declarations (e.g., "Added `VOLUME [\"/tmp\"]` — app writes temp files at startup")
3. **Preserved** — intentional customizations that were kept
4. **.dockerignore** — improved version if changes were needed

---

## Example workflows

Worked narrations for a new Dockerfile and for improving an existing one are in
[examples.md](examples.md).

---

## Success criteria

### Dockerfile checklist

- [ ] Builds successfully — both `--target develop` and default (production)
- [ ] Four named stages: `base`, `build`, `develop`, `production`
- [ ] `develop` is `FROM build`; `production` copies artifacts `COPY --from=build`
- [ ] No base image uses `:latest`; dev-side stages pinned by tag
- [ ] `production` base image locked by digest (`@sha256:…`), preferably the multi-arch manifest list
- [ ] No hardcoded `amd64`/`arm64`/`x86_64` anywhere; arch detected dynamically
- [ ] If built multi-arch for a cross-compilable language: `FROM --platform=$BUILDPLATFORM` on `build` with `ARG TARGETOS TARGETARCH`, and no `--platform` on `production`
- [ ] No credential reaches a layer: registry tokens via `RUN --mount=type=secret` / `--mount=type=ssh`, never `ARG`/`ENV`/`COPY`
- [ ] No `COPY . .` in any stage — all COPYs are explicit
- [ ] In `build`, dependency manifests copied and installed before source `COPY` (layer caching)
- [ ] Production runs as an explicit non-root user: distroless → built-in `nonroot`, `USER 65532:65532`; Alpine/Debian → a created `app` user
- [ ] Every `COPY` in the production stage uses `--chown` matching that exact uid (`--chown=65532:65532` for distroless, `--chown=app:app` for a created user) — no mismatch between `--chown` and `USER`
- [ ] `USER` appears before `CMD` in production
- [ ] The uid matches compose `user:` and the chart's `runAsUser`/`runAsGroup`/`fsGroup`
- [ ] All writable runtime paths declared with `VOLUME` — the contract for read-only rootfs
- [ ] Production designed for a read-only root filesystem; each `VOLUME` maps to a compose tmpfs/volume (dev) and a k8s `emptyDir` (prod)
- [ ] Production uses distroless (or slim with documented justification)
- [ ] CMD in exec form (`["executable", "arg"]`) — never shell form in production
- [ ] No HEALTHCHECK
- [ ] EXPOSE only if a port was verified in analysis
- [ ] Static OCI labels (`title`, `source`, `licenses`) in `production`; volatile ones (`version`, `revision`, `created`) left to CI `--label`; no `environment` label
- [ ] No debugging tools in production image

### .dockerignore checklist

- [ ] Excludes `.env`, `secrets/`, and all other local credential material
- [ ] Excludes large generated directories (`node_modules`, `target/`, `dist/`, etc.)
- [ ] Excludes local dev tooling (`devbox.json`, `Taskfile.yaml`, `skaffold.yaml`, `docker-compose*.yaml`)
- [ ] Does not exclude directories the Dockerfile never copies
- [ ] Scoped to this project's language(s) — the template in this skill is a multi-language menu, not the file to emit
- [ ] Roughly under 40 lines once scoped; longer is fine if the project genuinely spans several runtimes

### Validation checklist

- [ ] Production image builds without errors
- [ ] Production container starts and stays up (services) or exits 0 (one-shot)
- [ ] Develop image builds without errors
- [ ] Develop container starts with bind-mounted source
- [ ] Logs show no errors indicating application or permission failure
- [ ] `hadolint` passes (if installed)
- [ ] `trivy` shows no critical base image vulnerabilities (if installed)
- [ ] Test containers and images cleaned up

**Do not present the Dockerfile to the user until all validation checks pass.**

## Companion skills — offer after completing

Once the Dockerfile and `.dockerignore` are done, check the repo and offer whichever of these are missing or incomplete:

| Skill | Offer when |
|-------|-----------|
| `secrets` | The build pulls from a private registry (needs `--mount=type=secret`), or the repo has a `secrets/` dir the `.dockerignore` must exclude |
| `tagging` | The image ships no OCI labels, or CI doesn't pass `version`/`revision`/`created` |
| `docker-compose` | No `docker-compose.yaml` — the develop stage is built to be consumed by a compose local loop |
| `skaffold` | No `skaffold.yaml` — the develop stage exists specifically for skaffold/docker-compose local loops |
| `devbox` | No `devbox.json` in the repo root |
| `taskfile` | No `Taskfile.yaml` / `Taskfile.yml` in the repo root |
| `document` | No `docs/ARCHITECTURE.md`, or existing README doesn't describe the container stages |

Ask as a single grouped question — not mid-task, not separately for each.
