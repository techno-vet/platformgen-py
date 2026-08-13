# Security Policy

## Reporting a Vulnerability

**Do NOT open public GitHub issues for security vulnerabilities.**

Instead, please email your report to **security@platformgen.ai** with the following information:

- **Description**: A clear description of the vulnerability
- **Location**: Where in the codebase (file, function, line number)
- **Steps to Reproduce**: How to reproduce the vulnerability
- **Potential Impact**: What could an attacker do with this vulnerability?
- **Suggested Fix**: If you have an idea for a fix (optional)
- **Your Contact Info**: How we can reach you (optional)

### Response Timeline

We aim to:
- **Acknowledge** your report within 24 hours
- **Investigate** and provide an update within 48 hours
- **Release a fix** within 5 business days for critical vulnerabilities
- **Credit you** in the security advisory (if desired)

## Security Updates

Security updates are released as patch versions (e.g., v2.0.1) with a security notice in the release notes.

### How to Stay Updated

- **Watch Releases**: Subscribe to [releases](https://github.com/techno-vet/platformgen-py/releases) on GitHub
- **Follow Social Media**: [@platformgen on Twitter](https://twitter.com/platformgen)
- **Join Discord**: [Discord community](https://discord.gg/platformgen) for announcements

## Security Best Practices

When deploying platformgen:

### 1. API Keys & Tokens
- **Never** commit API keys, tokens, or credentials to Git
- Use environment variables or secrets management:
  ```bash
  export GH_TOKEN=your_copilot_token
  export ARTIFACTORY_TOKEN=your_token
  ```
- Store sensitive config in `~/.auger/.env` (gitignored by default)

### 2. Docker Security
- Always pull from official registries: `ghcr.io/techno-vet/platformgen-py`
- Verify image signatures when available
- Don't run as root in production: use `--user` flag
- Mount volumes read-only where possible

### 3. Kubernetes Deployments
- Use NetworkPolicies to restrict pod communication
- Enable Pod Security Standards (PSS)
- Use RBAC to limit service account permissions
- Scan images for vulnerabilities:
  ```bash
  trivy image ghcr.io/techno-vet/platformgen-py:latest
  ```

### 4. Database Security
- SQLite databases (tasks.db): Ensure file permissions are restricted:
  ```bash
  chmod 600 ~/.auger/tasks.db
  ```
- For production Postgres: Use SSL/TLS connections and strong passwords
- Regularly back up encrypted data

### 5. GitHub/GitOps Security
- Use fine-grained personal access tokens with minimal scopes
- Enable branch protection rules
- Require code review before merge
- Sign commits with GPG keys:
  ```bash
  git config user.signingkey YOUR_GPG_KEY_ID
  git commit -S -m "Secure commit"
  ```

### 6. Know Your Dependencies
We actively monitor dependencies for vulnerabilities:
- Critical issues: Fixed within 24 hours
- High issues: Fixed within 48 hours
- Medium/Low: Fixed in next release (or on-demand)

Run `pip list --outdated` to check for updates:
```bash
pip install --upgrade platformgen
```

## Common Vulnerabilities & Mitigations

### Token Exposure
**Risk**: Accidentally committing GitHub/Copilot tokens  
**Mitigation**: Use `pre-commit` hooks to scan for secrets:
```bash
pip install pre-commit
pre-commit install
```

### SSRF (Server-Side Request Forgery)
**Risk**: Ask Genny making arbitrary HTTP requests based on untrusted input  
**Mitigation**: Validate all URLs, use allowlists for external APIs

### Code Injection via Prompts
**Risk**: Malicious prompt injection to Ask Genny  
**Mitigation**: Sanitize all user inputs, limit system prompts scope

### Insecure Deserialization
**Risk**: Loading pickle/YAML from untrusted sources  
**Mitigation**: Use JSON or validated YAML schemas

## Supported Versions

| Version | Status | Security Updates |
|---------|--------|------------------|
| 2.1.x | Current | ✅ Full support |
| 2.0.x | Maintenance | ✅ Until 2026-12-31 |
| 1.x | End of Life | ⚠️ No new updates |

## Known Issues

None currently known. Please report any issues to security@platformgen.ai.

## Security Roadmap

- [ ] GPG signing for releases
- [ ] SBOM (Software Bill of Materials) for each release
- [ ] Automated security scanning in CI/CD
- [ ] Third-party security audit (2026)

---

**Thank you for helping keep platformgen secure!** 🔐
