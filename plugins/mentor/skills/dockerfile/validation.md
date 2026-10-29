# Build, run, validate

## 4.1 Build both targets

```bash
# Develop target
docker build --target develop -t my-service:develop .

# Production target (no --target needed — last stage is the default)
docker build -t my-service:latest .
```

## 4.2 Verify production image

```bash
docker run --rm my-service:latest                          # CLI tools / one-shot
docker run -d --name test my-service:latest && sleep 5    # services
docker inspect --format='{{.State.Status}}' test
docker inspect --format='{{.State.ExitCode}}' test
docker logs test 2>&1
```

**Expected by application type:**
- Services: container still running after 5 seconds
- CLI tools / one-shot: exited with code 0

## 4.3 Verify develop image

```bash
# Confirm the image starts correctly with a bind-mounted source
docker run --rm -v $(pwd):/app my-service:develop
```

## 4.4 Lint (if hadolint is available)

```bash
hadolint Dockerfile
```

Evaluate each finding — some may be intentional. Fix or note the reason before declaring done.

## 4.5 Security scan (if trivy is available)

```bash
trivy image --severity HIGH,CRITICAL my-service:latest
```

HIGH/CRITICAL findings in the base image → consider a different image variant. Findings in application dependencies → note for the user but don't block (dependency updates are outside Dockerfile scope).

## 4.6 Iterate

Maximum 5 iterations before stopping to report state to the user.

| Symptom | Likely cause |
|---|---|
| Missing file in production | `COPY --from=build` path wrong, or artifact wasn't built in the build stage |
| Permission denied | File is owned by root; `--chown=app:app` was missing or path mismatch |
| Binary not found at runtime | System dep present in `base`/`develop` but missing in production image |
| Hot reload not working | Bind-mount path doesn't match `WORKDIR` |
| Architecture error | Hardcoded arch in a download URL or binary path |
| `/tmp` not writable | `VOLUME ["/tmp"]` missing; in k8s, add `emptyDir` mount |

## 4.7 Cleanup

Always clean up after validation, whether successful or not:

```bash
docker stop test 2>/dev/null || true
docker rm test 2>/dev/null || true
docker rmi my-service:develop my-service:latest 2>/dev/null || true
```

Only present the Dockerfile to the user after all validation steps pass and cleanup is complete.
