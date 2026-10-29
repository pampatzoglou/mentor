# Example workflows

## New Dockerfile (no existing file)

1. **Check**: "No existing Dockerfile found. Will generate a new 4-stage one."
2. **Explore**: "Finding dependency manifest... found `go.mod`. Reading it for the Go version and module path."
3. **Identify**: "Go 1.23 project. Entry point is `cmd/server/main.go`. Binds to `$PORT` (default 8080). Writes temp files under `/tmp`."
4. **Build requirements**: "No external system deps called at runtime. Single static binary output to `./server`."
5. **Stage design**: "Base: `golang:1.23-alpine`. Build: full Go toolchain — `go mod download` (cached), then `go build -o /app/server`. Develop: `FROM build` + `air` for hot reload. Production: `gcr.io/distroless/static-debian12:nonroot` pinned by digest, `COPY --from=build` with `--chown=65532:65532`, `VOLUME [\"/tmp\"]`."
6. **Generate**: "Writing Dockerfile and .dockerignore."
7. **Build & test**: "Building develop target... building production target... running production container... verifying it stays up..."
8. **Iterate** (if needed): "Container exited — logs show `/tmp` not writable. Adding `VOLUME [\"/tmp\"]` and retrying."
9. **Cleanup & present**: "Validation passed. Cleanup done. Here are the files."

## Improving existing Dockerfile

1. **Check**: "Found existing Dockerfile. Reading it..."
2. **Analyse project**: Same exploration as above to understand what the Dockerfile should do.
3. **Evaluate**: "Checking against skill patterns..."
   - "❌ Two stages (builder + runtime) — missing the `build`/`develop` split for layer caching and the docker-compose/skaffold inner loop"
   - "❌ `COPY . .` in builder — should be explicit"
   - "❌ Files copied without `--chown` — owned by root in production"
   - "❌ No `VOLUME` — app writes to `/tmp` at startup"
   - "✅ Non-root USER directive already present"
   - "✅ Pinned image tags"
4. **Preserve**: "Keeping the custom CA cert installation in base — it's intentional."
5. **Improve**: "Adding `build` + `develop` stages, replacing `COPY . .`, adding `--chown`, adding `VOLUME`, digest-locking the production base."
6. **Build & test**: "Building both targets... running production container... checking logs..."
7. **Iterate** (if needed): "Production container exits — `--chown` uid doesn't match USER. Fixing and retrying."
8. **Cleanup & present**: "Validation passed. Here are the improvements."
