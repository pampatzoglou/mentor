---
name: debugging
description: Systematic debugging methodology — reproduce, isolate, hypothesize, test, fix, verify. Use when a bug reproduces, a test fails, a stack trace or error message needs root-causing, or behaviour differs across environments (dev vs CI vs prod). Includes checklists for environment, concurrency, resources, data, permissions, and Nix-specific issues. For the reproduce/verify steps the built-in /run and /verify skills can drive the actual app.
---

# Debugging Skill

## Purpose
Systematic approach to identifying and fixing bugs efficiently.

## Methodology

### 1. Reproduce
- Confirm the bug exists and is reproducible
- Identify minimal reproduction steps
- Note the expected vs actual behavior
- Document the environment (OS, versions, config)

### 2. Isolate
- Binary search: comment out code sections to narrow scope
- Add logging at key decision points
- Check assumptions with assertions
- Verify input data integrity
- Test with minimal/default configuration

### 3. Hypothesize
- Form theories about the root cause
- Consider recent changes (git blame, git log)
- Review error messages and stack traces carefully
- Check for common pitfalls:
  - Off-by-one errors
  - Null/undefined references
  - Race conditions
  - Type mismatches
  - Incorrect assumptions about data format

### 4. Test
- Add targeted logging or breakpoints
- Create minimal test case
- Verify hypothesis with controlled experiments
- Check edge cases and boundary conditions
- Use debugger to inspect state

### 5. Fix
- Address root cause, not symptoms
- Ensure fix doesn't introduce new issues
- Add test to prevent regression
- Document if the issue was subtle or non-obvious
- Consider if similar bugs exist elsewhere

### 6. Verify
- Confirm original bug is fixed
- Run full test suite
- Test edge cases thoroughly
- Check for side effects
- Verify in production-like environment

## Common Issues Checklist

### Environment
- [ ] Environment differences (dev vs staging vs prod)
- [ ] Environment variables missing or incorrect
- [ ] Configuration file differences
- [ ] Dependency version mismatches
- [ ] Platform-specific behavior (Linux vs macOS vs Windows)

### Concurrency
- [ ] Race conditions or timing issues
- [ ] Deadlocks or livelocks
- [ ] Thread safety violations
- [ ] Async/await issues
- [ ] Signal handling problems

### Resources
- [ ] Memory leaks or exhaustion
- [ ] File descriptor leaks
- [ ] Connection pool exhaustion
- [ ] Disk space issues
- [ ] CPU or network saturation

### Data
- [ ] Incorrect assumptions about data format
- [ ] Encoding issues (UTF-8, ASCII, etc.)
- [ ] Timezone or locale differences
- [ ] Data corruption or inconsistency
- [ ] Missing or malformed data

### Access & Permissions
- [ ] File or directory permission issues
- [ ] Network access restrictions
- [ ] Authentication or authorization failures
- [ ] CORS or security policy violations
- [ ] Resource quotas or limits

### Code Logic
- [ ] State management issues
- [ ] Incorrect control flow
- [ ] Logic errors in conditionals
- [ ] Improper error propagation
- [ ] Missing validation or sanitization

## Tools & Techniques

### Logging
- Add structured logs with context (JSON)
- Use appropriate log levels (debug, info, warn, error)
- Include timestamps and request IDs
- Log input parameters and return values
- Avoid logging sensitive data

### Debugging Tools
- Language-specific debuggers (gdb, lldb, pdb, delve)
- Browser DevTools for web applications
- Network inspection (tcpdump, Wireshark, browser network tab)
- Profilers for performance issues
- Strace/dtrace for system calls

### Nix-Specific Debugging
- Use `nix-build` with `-K` to keep failed build directories
- Check `nix repl` for evaluating expressions
- Use `nix-shell` to reproduce build environment
- Review `nix-store --query` for dependency issues
- Check `nix log` for build output

## Prevention
- Write tests first (TDD)
- Use type systems to catch errors early
- Enable linters and static analysis
- Code reviews catch bugs before merge
- Document assumptions and invariants
- Monitor production for anomalies

## Companion skills — offer after completing

| Skill | Offer when |
|---|---|
| `platform-review` | Bug was introduced by a quality issue that a review would have caught |
| `tidy` | Debug session revealed mechanical inconsistencies (mismatched config, wrong indentation) |
| `kubernetes` | Bug is in a Kubernetes workload (probes, resources, scheduling, secrets) |
| `terraform` | Bug is in infrastructure state or provider configuration |
