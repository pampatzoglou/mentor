# .dockerignore template

The `.dockerignore` applies to the entire build context. Since stages use explicit `COPY` commands (never `COPY . .`), the `.dockerignore` serves two purposes:
1. **Speed** — exclude large generated directories that slow context transfer.
2. **Security** — prevent secrets from entering the context even accidentally.

```dockerignore
# Version control
.git
.gitignore

# IDE and editor state
.vscode
.idea
*.swp
*.swo
.DS_Store

# Environment files and local secret material — never let these into the context
.env
.env.*
*.env
.envrc
secrets/                  # the `secrets` skill's local Vault pull lands here
*.pem
*.key
!.env.example
!.env.sample

# Generated build artifacts (the Dockerfile rebuilds these)
# Go
bin/
# Node
node_modules/
dist/
.next/
out/
# Python
__pycache__/
*.pyc
*.pyo
.venv/
venv/
dist/
*.egg-info/
# Rust
target/
# Java
target/
*.jar
*.war
build/

# Local dev tooling (not needed inside the image)
devbox.json
devbox.lock
.devbox/
Taskfile.yaml
Taskfile.yml
skaffold.yaml
docker-compose*.yaml
.github/

# Test output and coverage
coverage/
*.coverprofile
htmlcov/
.pytest_cache/
.nyc_output/

# Docs
docs/
*.md
!README.md
```

**The block above is a menu, not a file to paste.** It lists every language's artifacts; the `.dockerignore` you emit keeps only the sections that apply to *this* project. A Go service has no `node_modules/` or `.venv/` to exclude, so those lines are noise that makes the real entries harder to review.

**Keep the file lean.** Only exclude things that exist in directories being COPY-ed or that are large enough to matter for context transfer time. Don't exclude directories the Dockerfile never copies — that's redundant noise.
