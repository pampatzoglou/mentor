---
name: secrets
description: 'Canonical secret-handling contract across the platform — the Vault path convention, the three credential source modes (chart-internal, external reference, Vault dynamic), the in-container mount path and *_FILE env convention, and the dev-prod parity rule. Use whenever a task involves a credential, password, API key, token, ExternalSecret, VaultDynamicSecret, SecretStore, or a secret reaching a container. Owns the vocabulary that helm, docker-compose, devbox, terraform, and kubernetes all consume; those skills own their own syntax.'
---

# Secrets

One credential, one path, one env var — identical on a laptop and in production. Everything here exists to make that literally true, because the moment dev and prod resolve a secret differently, the application needs two code paths and the "works on my machine" gap reopens at the worst possible layer.

## Load first

This skill defines the contract; the syntax that implements it lives elsewhere. The moment the
task moves from *deciding* to *writing*, load:

- `helm` — chart credential blocks and the `ExternalSecret` / `VaultDynamicSecret` templates
  (`postgres.md` and `kafka.md` carry the concrete ones)
- `kubernetes` — where the `external-secrets` operator, its `SecretStore`, and the sync waves
  that order them belong

Quoting a Vault path or naming the `*_FILE` env for a credential needs neither.

## Ownership boundary

This skill owns the **contract**: where a secret lives, what path it lands on in the container, and how the app reads it. Each platform skill owns its own **syntax** for implementing that contract.

| Surface | Who owns the syntax | This skill's job |
|---|---|---|
| Chart values credential blocks, `VaultDynamicSecret`/`ExternalSecret` templates | `helm` (`SKILL.md`, `postgres.md`, `kafka.md`, `patterns.md`) | Define the three modes, the mount path, and the `*_FILE` convention those templates implement |
| `docker-compose.yaml` `secrets:` and `environment:` | `docker-compose` | Require the *same* target path and env var as the chart |
| Developer shell secret fetch (`init_hook`) | `devbox` | Require the same Vault paths the workload reads in-cluster |
| Build-time registry credentials (`RUN --mount=type=secret`) | `dockerfile` | Require that no credential ever becomes a layer — see *Build time* below |
| Terraform consume/persist, state sensitivity | `terraform` (its **Secrets** section) | Define the persist-to-backend rule and the path convention it writes to |
| `external-secrets` operator install, sync waves, `SecretStore` placement | `kubernetes` (`resource-standards.md`, `conventions.md`) | Nothing — that's cluster plumbing |
| Which *keys* a secret contains | the consuming service | Nothing |

**The rule:** if a skill needs to state where a secret comes from or lands, it cites this file rather than restating it. A second copy of a path convention is a path convention that drifts.

## The invariant

```
Vault path                     →  the one source of truth
  ├── in-cluster:  ExternalSecret → k8s Secret → mounted at /var/run/secrets/<block>/<key>
  └── on a laptop: task secrets:pull → ./secrets/<block>/<key> → mounted at the same path
                                                                  ▲
                        the app reads <BLOCK>_<KEY>_FILE ─────────┘  identical in both
```

The application only ever knows a **file path from an env var**. It never knows whether Vault, `external-secrets`, or a developer's `vault kv get` put the bytes there.

## Canonical paths and names

### Vault

| Kind | Path shape | Example |
|---|---|---|
| Static KV (v2) | `secret/<app>/<env>` | `secret/payments/dev` |
| Dynamic database creds | `database/creds/<role>` | `database/creds/payments-rw` |
| Dynamic cloud creds | `<cloud>/sts/<role>` | `aws/sts/payments-s3` |

One Vault path per credential block, holding all of that block's keys — not a path per key. Fetch once, extract the keys (see `devbox`'s `init_hook` pattern); a `vault` call per env var is a round-trip per env var.

`secret/<app>/<env>` puts the environment in the *path*, which is what lets one Vault role per environment be scoped by policy. Don't encode the env in the key names.

### In-container mount path

```
/var/run/secrets/<block>/<key>
```

`<block>` is the credential block from chart values (`db`, `kafka`, `redis`) — **not** the service name, which is already implied by the pod. `<key>` is the key within that secret (`username`, `password`, `token`).

```
/var/run/secrets/db/username
/var/run/secrets/db/password
/var/run/secrets/kafka/password
```

A **directory per block, one file per key** — this is what a mounted Kubernetes Secret produces naturally, and it's why compose has to mount to the same nested path rather than a flat file. A flat `/run/secrets/db_password` cannot be produced by a k8s Secret volume without a `subPath` per key, so the chart shape is the one both sides adopt.

`/var/run` is a compatibility symlink to `/run` on Debian (including the distroless Debian bases the `dockerfile` skill selects), so the two resolve to the same file. Write `/var/run/secrets/...` consistently anyway — matching strings are what make the parity auditable.

### Everything derives from the block token

The block token is the one name you choose. Every other identifier is derived from it mechanically
— there is nothing else to decide, and nothing to remember per service:

| Block token | Mount path | Secret name | Env prefix | Chart values key |
|---|---|---|---|---|
| `db` | `/var/run/secrets/db/<key>` | `<fullname>-db` | `DB_` | `database:` |
| `kafka` | `/var/run/secrets/kafka/<key>` | `<fullname>-kafka` | `KAFKA_` | `kafka:` |
| `redis` | `/var/run/secrets/redis/<key>` | `<fullname>-redis` | `REDIS_` | `redis:` |

The **chart values key is the only one allowed to be spelled out** (`database:` reads better than
`db:` in a values file). Everything the application or the cluster sees — path, Secret name, env
var — comes from the short token, so `db` never appears as `database` in a path or an env var.

Non-secret connection parameters in the same block take the same prefix: `DB_HOST`, `DB_PORT`,
`DB_NAME`. One block, one prefix, no exceptions — a `DATABASE_HOST` next to a `DB_PASSWORD_FILE`
is the drift this table exists to prevent.

### Env var convention

`<BLOCK>_<KEY>_FILE`, pointing at the path above:

```
DB_PASSWORD_FILE=/var/run/secrets/db/password
KAFKA_PASSWORD_FILE=/var/run/secrets/kafka/password
```

`<KEY>` is the **Secret key**, not a synonym for it: the file is `username`, so the env var is
`DB_USERNAME_FILE` — never `DB_USER_FILE`. Vault's `database/creds/<role>` returns `username`, so
that spelling is the one you don't get to pick; the chart-internal mode has to match it or the
filename changes with the credential source.

Some upstream images use `FILE__<NAME>` instead (linuxserver) or only accept a directory. Match what the image actually supports and document the deviation next to it — you don't own a third-party image's convention.

**Never** put a secret value in `environment:` / `env:` as a **literal**, even in dev. That rule does not bend — a literal is a committed secret the moment the file is committed.

### Files always; env only where the code actually reads env

The credential volume is mounted **unconditionally** — every source mode, every service, whether or
not the application reads it. That is what makes the three modes indistinguishable to the workload
and keeps the path identical on a laptop and in the cluster. It costs one volume and it is the
thing a reviewer can check.

Plenty of code — and every third-party image — only knows env vars. Don't fight it: inject the env
var **from the same Secret**, via `secretKeyRef` in the chart, alongside the mount that stays.

```
mounted file   /var/run/secrets/db/password     ← always present, the contract
env var        DB_PASSWORD (secretKeyRef)       ← added when the app reads env
```

- **`secretKeyRef` is allowed; a literal is not.** The value still lives in the Secret, still comes
  from Vault, still rotates. What you lose is containment: an env var is readable by every process
  in the container and by anything that can `docker inspect` / read `/proc/<pid>/environ`, and it
  is captured in crash dumps and inherited by child processes. That's the price of the
  accommodation — pay it knowingly, per service, not by default.
- **One source, two views.** The env var and the file must resolve to the same Secret key. Never
  wire the env from a second place (a different Secret, a `.env`, a CI variable) — that's two
  sources of truth for one credential, and they will drift.
- **Prefer `*_FILE` when the app supports it** (`DB_PASSWORD_FILE` over `DB_PASSWORD`), and prefer
  teaching new code to read files. Reach for env injection for third-party images and for code you
  can't change today.
- **In compose, don't reproduce env injection with a literal.** There is no `secretKeyRef` locally,
  so if the app needs the env var, populate it in the entrypoint from the mounted file
  (`export DB_PASSWORD="$(cat "$DB_PASSWORD_FILE")"`) — the same shim then works unchanged in the
  cluster, and the compose file stays free of credential values.

## The three source modes

Exactly three, in priority order. A chart resolves the first that's enabled; `helm`'s credential blocks implement this and `postgres.md` / `kafka.md` carry the templates.

| Mode | Enabled by | What renders | Use when |
|---|---|---|---|
| **Chart-internal** | both `externalSecret.enable` and `vault.enable` false | a `Secret` with inline values from `values.yaml` | local kind only — the base chart must deploy with no secret infrastructure |
| **External reference** | `externalSecret.enable: true` | nothing; references a pre-existing `Secret` by name | the secret is managed outside this chart (platform-provisioned, another team) |
| **Vault dynamic** | `vault.enable: true` + `vault.path` set | `VaultDynamicSecret` + `ExternalSecret`, always as a pair | anything real — dev cluster included |

**Chart-internal is a local-development affordance, not a deployment mode.** It exists so `helm template` works on a bare kind cluster with only `values.yaml`. An inline credential must never survive into `defaults/values.yaml` or an `<env>/values.yaml` — that's a committed secret.

**Prefer dynamic over static.** A leaked dynamic credential expires on its own; a static KV credential is valid until somebody notices. Reach for static KV only when the backend offers nothing dynamic.

## Local development parity

`./secrets/` is gitignored and populated from **the same Vault paths the cluster reads**, into the same nested layout the chart mounts:

```sh
# task secrets:pull
set -euo pipefail
mkdir -p secrets/db && chmod 700 secrets secrets/db
creds=$(vault kv get -format=json secret/myapp/dev)
printf '%s' "$creds" | jq -r '.data.data.username' > secrets/db/username
printf '%s' "$creds" | jq -r '.data.data.password' > secrets/db/password
unset creds
# 0644, not 0600: compose bind-mounts these preserving host ownership and mode, and the
# container runs as a different uid (the Dockerfile's USER, e.g. 65532). The long-syntax
# uid/gid/mode keys are swarm-only, so a 0600 file owned by you is simply unreadable in the
# container — on Linux and in CI; Docker Desktop remaps ownership and hides it. The 0700
# directory above is what keeps other host users out; the bind mount is performed by the
# daemon as root, so the container never traverses it.
chmod 644 secrets/db/*
```

Then compose mounts each file to the path the chart uses, so the env var is byte-identical across both:

```yaml
secrets:
  db_username: { file: ./secrets/db/username }
  db_password: { file: ./secrets/db/password }

services:
  app:
    environment:
      - DB_PASSWORD_FILE=/var/run/secrets/db/password   # same string as the chart
    secrets:
      - source: db_password
        target: /var/run/secrets/db/password                  # nested, not flat
```

`.gitignore`:

```gitignore
# Local dev secret material — never commit
secrets/
```

Two things that break parity, both easy to miss:

- **A flat compose target** (`/run/secrets/db_password`) — the env var then differs between dev and prod, which is the exact failure this convention exists to prevent.
- **A different Vault path for dev** — if the laptop reads `secret/myapp/local` and the cluster reads `secret/myapp/dev`, the key names drift silently and nothing catches it until prod.

Secrets stay in files and in the shell env only; nothing is written to a committed file, and nothing is `echo`ed. See `devbox` for why the fetch lives in `init_hook` rather than a task, and let the fetch fail open so an unreachable Vault doesn't block shell entry.

## Build time

A token used to *install dependencies* — a private npm registry, a PyPI index URL with basic auth,
`GOPRIVATE` over SSH, a Debian repo key — is a secret with a different delivery mechanism, not an
exception to the rules. Two things make it different from a runtime credential:

- **It never reaches the running container.** It exists only inside one `RUN`, and the image that
  ships has no trace of it. A runtime credential is the opposite: it never enters the image and
  always arrives as a mounted file.
- **It can't come from a mount the app reads**, so the `*_FILE` convention doesn't apply. Use a
  BuildKit secret mount, which exposes the value at `/run/secrets/<id>` for that instruction only:

```dockerfile
RUN --mount=type=secret,id=npm_token \
    NPM_TOKEN="$(cat /run/secrets/npm_token)" npm ci --omit=dev
```

```bash
docker build --secret id=npm_token,env=NPM_TOKEN .
```

For Git-over-SSH dependencies use `RUN --mount=type=ssh` with `docker build --ssh default` instead
of copying a key. The `dockerfile` skill carries the full pattern; this skill's rule is the one it
implements: **nothing that could be exfiltrated from `docker history` or a pulled layer.**

In CI, the build secret should be an OIDC-obtained short-lived token, never a long-lived PAT in a
repo secret — the `github-actions` skill owns that exchange.

**The build context is a leak path too.** `./secrets/` sits in the repo root by design, so
`.dockerignore` must exclude it alongside `.env` — otherwise a `COPY` typo, or anything that ships
the context to a remote builder, takes the credentials with it:

```dockerignore
# Local dev secret material — never into the build context
secrets/
.env
.env.*
*.pem
*.key
```

## Rotation

Rotation is the backend's job, not a deploy step. Wire Vault TTLs or the backend's native rotation, and let the workload pick up the change:

- `external-secrets` re-syncs on its `refreshInterval` (`1h` is a reasonable default).
- **Reloader** (`reloader.stakater.com/auto: "true"`, set in `defaults/values.yaml` per the `helm` skill) restarts the pod when the Secret changes in place — without it a rotated credential sits unread until the next unrelated deploy.
- Locally, re-run `task secrets:pull` then `direnv reload`.

Never implement rotation as "re-run `apply` to regenerate" — that couples credential lifetime to deploy cadence.

## Never

- A literal secret in any committed file — `values.yaml`, `defaults/`, `<env>/`, `*.tfvars`, `*.hcl`, a workflow, a Dockerfile `ENV`, a compose `environment:`
- A secret baked into a container image at any layer (it stays in the image history even if a later layer removes it)
- A registry token passed as `ARG`/`ENV`, or a key `COPY`-ed in and deleted later — both persist in `docker history`; use `RUN --mount=type=secret` / `--mount=type=ssh`
- `terraform output` as the retrieval path for a secret value — output the ARN/path, and mark it `sensitive = true`
- A secret in a `ConfigMap`
- `echo`ing a secret value, or pasting one into a chat or a PR
- A secret as a Prometheus/Datadog label or a log field

## Checklist

- [ ] Every credential resolves through one of the three modes; chart-internal appears only in the base `values.yaml`
- [ ] Vault path follows `secret/<app>/<env>` (static) or `<engine>/creds/<role>` (dynamic)
- [ ] One Vault path per credential block, fetched once, keys extracted from it
- [ ] Path, Secret name, and env prefix all derive from one block token (`db` → `/var/run/secrets/db/`, `<fullname>-db`, `DB_`)
- [ ] Mount path is `/var/run/secrets/<block>/<key>` in the chart **and** in compose — same string, nested layout
- [ ] The Secret key is spelled the same in all three source modes — `username`, never `user` in one of them
- [ ] `<BLOCK>_<KEY>_FILE` env var points at that path, identical in both, with no literal secret in `environment:`/`env:`
- [ ] The credential volume is mounted unconditionally, even where the app currently reads env
- [ ] Any `secretKeyRef` env var resolves to the same Secret key as the mounted file — one source, two views
- [ ] Local `./secrets/` files are readable by the container's uid (`0644` files inside a `0700` directory)
- [ ] Local `./secrets/` is gitignored and populated from the same Vault paths the cluster reads
- [ ] `VaultDynamicSecret` and `ExternalSecret` render as a pair, never independently
- [ ] `refreshInterval` set, and Reloader enabled so a rotated secret is actually picked up
- [ ] Credential volume mounted `readOnly: true`, and it pairs with `readOnlyRootFilesystem: true`
- [ ] Build-time registry credentials use `--mount=type=secret`/`--mount=type=ssh`, never `ARG`/`ENV`/`COPY`
- [ ] `.dockerignore` excludes `secrets/` and `.env*` so the local credential dir can't enter the build context
- [ ] No secret in a ConfigMap, an image layer, a metric label, or a log field
- [ ] A secret scanner (`gitleaks`) runs as a pre-commit hook **and** in CI — the rules above are only as good as what enforces them (`devbox` skill)

## Companion skills — offer after completing

| Skill | Offer when |
|-------|-----------|
| `helm` | A credential block is missing its `externalSecret`/`vault` sub-keys, or the mount path doesn't match |
| `dockerfile` | A build needs a private-registry credential, or `.dockerignore` doesn't exclude `secrets/` |
| `docker-compose` | Compose mounts a flat target, or has a literal secret in `environment:` |
| `devbox` | The `init_hook` doesn't pull from the same Vault paths, or logins aren't guarded to stay idempotent |
| `terraform` | A generated secret isn't persisted back to the backend, or a value is exposed via an output |

Ask as a single grouped question — not mid-task, not separately for each.
