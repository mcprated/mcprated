# Security Policy

## Reporting a vulnerability

If you find a security issue in MCPRated, please email **mbrz82017+mcprated-security@gmail.com** instead of opening a public issue. Include:

- A description of the issue
- Steps to reproduce
- Affected component (Worker / linter / catalog API / static site)
- Whether disclosure has happened anywhere else

Expect an acknowledgement within 72 hours and a fix or mitigation plan within 14 days for confirmed issues. We coordinate disclosure once a fix is deployed.

## Scope

In scope:
- The Worker at `https://mcp.mcprated.workers.dev` and its source under `worker/`
- The linter pipeline under `linter/`
- The catalog API at `https://mcprated.github.io/mcprated/api/v1/*`
- The released snapshot tarballs

Out of scope:
- Vulnerabilities in *cataloged* third-party MCP servers (those belong to their respective maintainers — please report directly there)
- DoS via excessive requests against the public Worker (rate-limited at the edge)
- Issues in dependencies we don't ship with the artifact (e.g., `wrangler` dev tooling)

## Supported versions

Always: the version currently deployed at `https://mcp.mcprated.workers.dev` (`main` branch HEAD on GitHub).
We do not maintain release branches.

## Hardening notes

- The Worker is read-only — no write endpoints, no auth state, no per-user data
- Outbound fetches go to a single allowlisted origin (`mcprated.github.io`)
- Catalog data is generated from public GitHub metadata only; no scraping of authenticated sources
- Daily snapshots are pinned in GitHub Releases for audit/replay

## Public disclosure

Once fixed, security issues are summarized in [`CHANGELOG.md`](CHANGELOG.md) and credited (with reporter consent).
