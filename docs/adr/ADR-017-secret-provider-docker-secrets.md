<!-- trace: NFR-010, NFR-012 -->
# ADR-017: Docker/Swarm secrets as the secret provider

**Status:** accepted · **Date:** 2026-09-04 · **Phase:** 1
**Requirements:** NFR-010, NFR-012

## Context

The platform holds provider keys, database credentials and MCP server tokens. The failure modes are
memorable: a key in a compose file, a key in a log line, a key in a prompt. A vault is the right answer
at scale and the wrong answer for a single Swarm operated by three people, because the vault itself
becomes the thing that must be up and the thing that must be unlocked.

## Decision

Swarm secrets are the provider. A `SecretProvider` port reads from `/run/secrets/<name>`; the only
other implemented adapter is `env_file`, for local development, and it is refused at startup in
`prod`. Secrets never appear in environment values in production, in images, in logs, in trace
attributes or in prompts ([SECURITY.md §4](../SECURITY.md)).

## Consequences

**Positive.** Zero additional services. Rotation is `docker secret create` plus a service update, with
no rebuild and no downtime ([DOCKER_SWARM.md §5](../DOCKER_SWARM.md)). The port means Vault or a cloud
secret manager is an adapter, not a redesign.

**Negative.** No dynamic secrets, no per-request scoping, no automatic expiry, and the RAFT distribution
of secrets across managers is trusted implicitly. Audit of secret reads is coarse — a container either
has the mount or it does not.

**Neutral.** A redaction filter at the logging handler is a second line of defence, because the first
line is a human eventually putting a key in a log.

## Alternatives considered

| Option | Why not |
| --- | --- |
| HashiCorp Vault | correct at scale; adds a dependency in the boot path of every service, and its own unsealing problem |
| Cloud secret managers | couples the deployment to one cloud, contradicting ADR-011 |
| Environment variables | the vector for most real-world leaks; retained only for local dev |
| SOPS/age-encrypted files in git | workable, but rotation requires a commit and a redeploy |

## Links

[SECURITY.md §4](../SECURITY.md) · [DOCKER_SWARM.md §5](../DOCKER_SWARM.md) ·
[ARCHITECTURE.md §9](../ARCHITECTURE.md)
