# Read-only root filesystem — the writable-paths contract

Production runs with a **read-only root filesystem**. The only writable locations are the ones declared as `VOLUME` in the Dockerfile — that list is the single source of truth for "what this app needs to write," and every runtime *mounts* it identically:

| Declared in Dockerfile | docker-compose (dev) | Kubernetes (prod) |
|---|---|---|
| `VOLUME ["/tmp"]` | `tmpfs: [/tmp]` (or a named volume) | `emptyDir` mount at `/tmp` |
| `VOLUME ["/var/cache/app"]` | `tmpfs`/named volume | `emptyDir` / PVC |
| rootfs itself | `read_only: true` | `securityContext.readOnlyRootFilesystem: true` |

## What `VOLUME` does and doesn't do

`VOLUME` is a **declaration, not a mechanism** — and it is still required. Being clear about the split avoids expecting enforcement from the wrong layer:

- **It does not create the mount in Kubernetes.** The kubelet ignores Dockerfile `VOLUME` entirely; the chart must declare a matching `emptyDir` (or PVC) by hand. The `VOLUME` line is what tells the chart author which ones to write — and what a reviewer diffs the chart against.
- **It does create an anonymous volume under plain Docker.** `docker run` (and compose, for any declared path with no explicit mount) allocates one per `VOLUME`. Consequences: it is writable even under `read_only: true`, so a *declared* path never surfaces a missing compose `tmpfs:`; and the volumes accumulate — use `docker run --rm` and `docker compose down -v` during validation.
- **What it buys:** the writable-path contract travels with the image. `docker inspect --format '{{json .Config.Volumes}}' <image>` answers "what does this thing write?" without reading the source, months later, from a chart repo that doesn't contain the Dockerfile. That breadcrumb is the point — declare every writable path even though nothing reads the list automatically.
- **What actually enforces it:** `readOnlyRootFilesystem: true` in the pod `securityContext` plus explicit mounts. An *undeclared* path fails there, loudly, which is the behaviour worth having.

## Applying it

- **Enforced in production.** The chart sets `readOnlyRootFilesystem: true` (see the `helm` skill's `defaults/values.yaml`) and mounts an `emptyDir` for each declared VOLUME. A write to an undeclared path crashes the container — that's the point: it forces every writable path to be explicit and reviewed.
- **Recommended in dev.** Run `develop`/compose with `read_only: true` and the same paths mounted, so a path the app writes but nobody declared surfaces on a laptop, not in the cluster. Hot-reload tools that write belong on the bind-mounted source (kept writable); everything else stays read-only.
- **Find the paths in Step 1.7** — temp files, caches, framework scratch dirs, on-disk logs. Each becomes one `VOLUME`. Keep the set minimal: every writable mount is attack surface and state to manage. If the app can be told to write only to `/tmp`, prefer that over many scattered VOLUMEs.

The payoff: dev and prod fail the same way. If a read-only rootfs breaks something, you hit it identically on compose and in k8s — and the fix is one reviewed change in three places that a reader can check against each other, starting from the `VOLUME` line.
