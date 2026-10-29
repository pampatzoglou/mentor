---
name: docker-compose
description: 'Author docker-compose.yaml for the local development inner loop, built to mirror how the workload runs in Kubernetes. Use when adding or editing a compose file, setting up local dev for a service, or running docker compose up. Every service gets named volumes (like PVCs/emptyDir), file-based secrets mounted at the same nested path the chart uses via the *_FILE env convention (the `secrets` skill owns that contract), and a securityContext-equivalent hardening block (read_only, tmpfs, cap_drop, no-new-privileges, non-root user). Triggers on docker-compose, compose.yaml, docker compose, "local dev environment", "run it locally".'
requires: [dockerfile, secrets]
---

# docker-compose for local dev (Kubernetes-parity)

## Load first

- `dockerfile` — the stage names compose builds (`target: develop`) and the `USER` uid that
  `user:` must match. The Dockerfile is the single source of truth for that uid; align compose
  to it, never the reverse.
- `secrets` — the mount path and `*_FILE` env convention this file has to reproduce verbatim.
  Compose owns the `secrets:` syntax; it does not get to re-decide the contract.

Generate a `docker-compose.yaml` for the local inner loop that behaves like the in-cluster deployment, so "works on my machine" means "works in the cluster." The bridge is built from three things every service must have: **file-based secrets at the k8s paths**, **named volumes**, and a **security block that maps to a pod `securityContext`**.

## Why parity matters

The app should read secrets, write state, and run under the same constraints locally as in production. If a secret is an env var locally but a mounted file in k8s, the app needs two code paths. Make local match prod instead.

| Local dev (compose) | Kubernetes equivalent | Why it must match |
|---|---|---|
| `secrets:` `file:` + per-service `target: /var/run/secrets/<block>/<key>` | mounted `Secret` / ExternalSecret volume | identical in-container path → no code change |
| `*_FILE` env pointing at `/var/run/secrets/<block>/<key>` | same `*_FILE` env in the chart | app reads the secret the same way both places |
| named volume / bind mount | PVC (or `hostPath`) | persistent state survives restarts |
| `tmpfs:` | `emptyDir` (memory) | writable scratch when the rootfs is read-only |
| `read_only: true` | `readOnlyRootFilesystem: true` | immutable rootfs catches accidental writes early |
| `cap_drop: [ALL]` + minimal `cap_add` | `capabilities: { drop: [ALL], add: [...] }` | least privilege, same set |
| `security_opt: [no-new-privileges:true]` | `allowPrivilegeEscalation: false` | no privilege escalation |
| `user: "65532:65532"` | `runAsUser` / `runAsGroup` (+ `runAsNonRoot`) | same non-root UID — sourced from the Dockerfile's `USER` |
| `security_opt: [seccomp:...]` | `seccompProfile.type: RuntimeDefault` | same syscall filter |
| `healthcheck:` | readiness / liveness probe | same definition of "ready" |
| `networks:` (frontend/backend) | NetworkPolicy / namespace boundaries | segment traffic the same way |
| `expose:` vs `ports:` | ClusterIP vs NodePort / Ingress | only publish what truly needs the host |

Two contracts here are owned elsewhere and must be copied, not re-decided: the **secret path and env var** belong to the `secrets` skill, and the **capability set and security context** to `kubernetes`/`resource-standards.md`. That consistency is the whole point. The UID has a single source of truth: the Dockerfile (see below).

## Secrets — always from files, never inline

**The `secrets` skill owns this contract** — the Vault path convention, the in-container mount path, and the `*_FILE` env naming. Read it before wiring anything; what follows is how compose implements it.

Define secrets once at the top level from files, then mount each into the services that need it at **the exact path the chart mounts**: `/var/run/secrets/<block>/<key>`. Never put a secret in `environment:` as a literal.

```yaml
secrets:
  db_username:
    file: ./secrets/db/username       # gitignored; one file per key, no trailing newline
  db_password:
    file: ./secrets/db/password
```

Per service, mount it and point the app at the file with the `*_FILE` convention:

```yaml
    environment:
      - DB_PASSWORD_FILE=/var/run/secrets/db/password
    secrets:
      - source: db_password
        target: /var/run/secrets/db/password
```

**Mount to the nested path, not a flat file.** `target: /run/secrets/db_password` is the tempting shorthand and it breaks the whole premise: a mounted Kubernetes Secret produces a *directory of keys*, so the chart's path is `/var/run/secrets/db/password`. Flatten it here and `DB_PASSWORD_FILE` has to differ between dev and prod — the one thing this parity exercise exists to prevent. (`/var/run` is a symlink to `/run` on Debian and distroless-Debian, so they resolve identically; write the same string as the chart so the match is auditable.)

**When the app only reads env vars.** Some code — and every third-party image — won't read a file.
The chart handles that with `secretKeyRef`; compose has no equivalent, and a literal in
`environment:` is not the substitute. Keep the mount and derive the env var from it at startup:

```yaml
    environment:
      - DB_PASSWORD_FILE=/var/run/secrets/db/password
    entrypoint: ["/bin/sh", "-c", 'export DB_PASSWORD="$$(cat "$$DB_PASSWORD_FILE")"; exec "$$@"', "--"]
```

(`$$` escapes compose's own interpolation.) Better still, put that shim in the image so the same
two lines run in the cluster — then dev and prod produce the env var the same way, from the same
file, and neither compose nor the chart holds a value. Third-party images usually ship this
already as the `*_FILE` convention (`POSTGRES_PASSWORD_FILE`, `MYSQL_ROOT_PASSWORD_FILE`) — use it
rather than writing a shim.

**Where the files come from.** `./secrets/` is gitignored and populated from the **same Vault paths the cluster reads via ExternalSecret** — see the `secrets` skill for `task secrets:pull`, and the `devbox` skill for pulling on shell entry.

`.gitignore`:

```gitignore
# Local dev secret material — never commit
secrets/
```

## Volumes — every service that has state gets one

- **Named volumes** for persistent state (`name:/path`) — the PVC equivalent.
- **Read-only bind mounts** for config you edit in the repo (`./config/app:/etc/app:ro`) — the ConfigMap equivalent; `:ro` mirrors a read-only mount.
- **`tmpfs`** for writable scratch when `read_only: true` is set — the `emptyDir` equivalent. These writable paths are the **same ones the Dockerfile declares as `VOLUME`** (the single source of truth) and the chart mounts as `emptyDir` — keep all three in sync. List every path the app writes at runtime (`/tmp`, framework caches) — but not `/run` wholesale, which would shadow the secret mounts.

```yaml
volumes:
  app_data:                 # plain named volume — portable across machines
  db_data:
# Bind a host directory only when the data lives outside the project
# (the local stand-in for a hostPath PV — avoid in shareable composes):
#  media:
#    driver: local
#    driver_opts: { type: none, o: bind, device: /srv/media }
```

Prefer plain named volumes in a shareable compose; reserve host `bind` devices for machine-specific data (it's the `hostPath` of compose — not portable).

## Platform — pin third-party images on Apple Silicon

Your own images build natively (the `dockerfile` skill's rule 2). A third-party image that ships
amd64 only will silently run under QEMU on an arm64 laptop — slow, and occasionally broken in ways
that look like application bugs. Pin it explicitly and comment why:

```yaml
    image: some/amd64-only-tool:1.4
    platform: linux/amd64            # no arm64 image published; runs emulated
```

Never add `platform:` to a service you build yourself — that forces emulation for no reason.

## Per-service hardening — the securityContext block

Apply this to every service by default; relax only with a comment explaining why (the NAS reference does exactly this — e.g. pihole omits `no-new-privileges` because `pihole-FTL` needs `setcap`).

```yaml
    read_only: true
    tmpfs:
      - /tmp                          # plus each path the Dockerfile declares as VOLUME
    user: "65532:65532"               # the Dockerfile's USER — see "One UID" below
    cap_drop: [ALL]
    cap_add: []                       # add back only what's proven necessary
    security_opt:
      - no-new-privileges:true
```

**tmpfs the specific paths the app writes, not `/run` wholesale.** Secrets land under
`/var/run/secrets/…` (which is `/run/secrets/…` — `/var/run` is a symlink), so a blanket
`tmpfs: /run` puts a fresh empty filesystem over the same subtree the secret mounts occupy.
List the paths the Dockerfile declares as `VOLUME` instead. Either way, verify with the
`exec … cat` check under **Validate** — an empty read there is this bug.

### One UID, defined in the Dockerfile

The non-root UID is **declared once, in the Dockerfile's `USER`** (the `dockerfile` skill: a created `app` user, or distroless `nonroot` = `65532`). Everything else mirrors it — there is no second place to "decide" the UID:

```
Dockerfile  USER 65532
   ├── docker-compose   user: "65532:65532"
   └── Helm chart       runAsUser: 65532   runAsGroup: 65532   fsGroup: 65532
```

If they drift, the same image runs as different users in each environment and file ownership on the mounted volume breaks. When you change the Dockerfile user, update both the compose `user:` and the chart values in the same commit.

**Third-party images set their own UID** — you don't own their Dockerfile, so use the UID that image ships and document it: `postgres` runs as `999`, `mariadb` as a `mysql` user, linuxserver images take `PUID`/`PGID` (commonly `1000`) via env. Match *that* image's expectation, not your app's `65532`.

## Canonical example

One app (built from the `dockerfile` skill's `develop` target) plus its database — every pattern above in context:

```yaml
name: myapp

secrets:
  db_password:
    file: ./secrets/db/password

networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
    internal: true                    # no host egress — like a backend NetworkPolicy

volumes:
  db_data:

services:
  app:
    build:
      context: .
      target: develop                 # the dockerfile skill's hot-reload stage
    restart: unless-stopped
    read_only: true
    tmpfs: [/tmp]                     # + each Dockerfile VOLUME; not /run (see hardening)
    user: "65532:65532"               # = Dockerfile USER = chart runAsUser
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    networks: [frontend, backend]
    depends_on:
      db:
        condition: service_healthy
    environment:
      - DB_HOST=db
      - DB_USERNAME=myapp
      - DB_PASSWORD_FILE=/var/run/secrets/db/password  # *_FILE, not a literal
    secrets:
      - source: db_password
        target: /var/run/secrets/db/password
    volumes:
      - .:/app                        # bind source for hot reload (dev-only)
    ports:
      - "8080:8080"                   # publish only the user-facing port
    healthcheck:
      # Use a probe binary that exists in the image — `curl` is absent from
      # golang:alpine, distroless, and most slim bases. `wget -q --spider`
      # (busybox), the app's own `/healthz` subcommand, or a tiny Go/Node
      # one-liner all work; verify with `docker compose exec app <cmd>` first.
      test: ["CMD", "wget", "-qO-", "http://localhost:8080/healthz"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s

  db:
    image: postgres:17
    restart: unless-stopped
    read_only: true
    tmpfs: [/tmp, /var/run/postgresql]  # postgres writes its socket here
    user: "999:999"                   # the postgres image's own UID, not ours
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    networks: [backend]              # never published to the host
    environment:
      - POSTGRES_USER=myapp
      - POSTGRES_DB=myapp
      - POSTGRES_PASSWORD_FILE=/var/run/secrets/db/password
    secrets:
      - source: db_password
        target: /var/run/secrets/db/password
    volumes:
      - db_data:/var/lib/postgresql/data
    expose:
      - 5432                          # reachable on backend net only, not the host
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U myapp"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
```

## Hot reload: bind mount vs `develop.watch`

`volumes: [.:/app]` is the simple option and it has two well-known edges, both worse under the
non-root `user:` above:

- **Ownership.** The host source is owned by your uid; the container runs as `65532`. On Linux the
  reload daemon then can't write its build output into the mounted tree. macOS/Docker Desktop
  remaps ownership and hides this — so it fails first in Linux CI. Either keep the reloader's
  scratch dir off the bind mount (`air`'s `tmp_dir` → a `tmpfs`), or `chgrp`/`chmod g+w` the paths
  it writes, or use watch-sync below.
- **Shadowing.** The mount covers everything the image built at that path — `/app/node_modules`,
  `/app/.venv`, a compiled `dist/` — with whatever the host has. The classic fix is an anonymous
  volume in front of it (`- /app/node_modules`), which then goes stale when the manifest changes.

`develop.watch` avoids both by *copying* changed files in rather than mounting over the directory,
and re-running the build when a manifest changes:

```yaml
    develop:
      watch:
        - action: sync                # copy changed source into the running container
          path: ./src
          target: /app/src
          ignore: [node_modules/]
        - action: rebuild             # dependency change → rebuild the image
          path: package.json
```

Run with `docker compose up --watch`. Prefer it for Node/Python projects (where shadowing bites
hardest) and for anything that must run non-root on Linux; the plain bind mount is fine for Go and
Rust, where the reloader writes to its own scratch dir.

## `expose` vs `ports`

- `expose:` — reachable by other services on the same network only (the ClusterIP default). Use for databases, internal APIs.
- `ports: ["host:container"]` — published to the host (NodePort/Ingress). Publish **only** what a human or external client actually hits. A database with `ports:` is a foot-gun.

## Validate

**Pull the secrets first.** A top-level `secrets: file:` is resolved when the file is *parsed*, so
on a fresh clone `docker compose config` fails with `no such file or directory` before anything
runs. The order is always:

```bash
task secrets:pull                     # or devbox shell entry — populates ./secrets/<block>/<key>
docker compose config                 # parse + interpolate; catches schema and ${VAR} errors
docker compose up -d
docker compose ps                     # confirm State=running / healthy
docker compose logs -f app
docker compose down                   # add -v to also drop named volumes
```

Wait for `healthy` before declaring success; a container can be `running` but not ready. Then confirm the secret landed: `docker compose exec app cat /var/run/secrets/db/password` should match Vault (don't paste the value into chat).

Two failures worth checking for explicitly, because both hide on macOS and appear on Linux:

- **Permission denied reading the secret.** Compose bind-mounts the secret file preserving the
  host's ownership and mode — the long-syntax `uid`/`gid`/`mode` keys are swarm-only and are
  ignored by `docker compose`. A `0600` file owned by your uid is unreadable to `65532`. The
  `secrets` skill's `task secrets:pull` writes `0644` files inside a `0700` directory for exactly
  this reason: the directory keeps other host users out, and the daemon (root) performs the bind
  mount, so the container never traverses it. Docker Desktop's VirtioFS remaps ownership and hides
  the bug, which is why it only ever bites on a Linux host or in CI. Fix the mode, never loosen
  `user:`.
- **Permission denied writing to the bind mount** — same cause, see *Hot reload* above.

## When compose vs skaffold

| Use | When |
|---|---|
| `docker-compose` | Fast inner loop, no cluster needed; a couple of services + a DB; you want the lightest possible local run |
| `skaffold` (+ kind) | You need to exercise the actual Helm chart, k8s objects, probes, and ArgoCD-style rendering locally |

Both consume the `dockerfile` skill's `develop` stage, so the image is identical across them.

## Companion skills — offer after completing

| Skill | Offer when |
|---|---|
| `dockerfile` | No `Dockerfile`, or it lacks a `develop` stage for compose to build |
| `helm` | The service deploys to Kubernetes — port the volumes/secrets to chart values and ExternalSecret |
| `skaffold` | The team also needs a real-cluster local loop against the chart |
| `devbox` | Secret files should be populated from Vault on shell entry (`devbox` init) |

Ask as a single grouped question — not mid-task, not separately for each.
