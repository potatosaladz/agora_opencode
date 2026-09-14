# ADR-008: MinIO for object storage

**Status:** accepted · **Date:** 2026-09-04 · **Phase:** 1
**Requirements:** FR-401, FR-303, NFR-003, NFR-012

## Context

Uploaded documents, parsed text, raw provider responses, simulation artefacts and audit exports are
large, immutable and content-addressable. Storing them as `bytea` in the system-of-record database
would bloat backups, slow the ledger and make WAL archiving absurd.

## Decision

MinIO (S3-compatible) holds all binary payloads, keyed by `sha256` digest under a workspace prefix.
Postgres stores metadata, hashes and locators only. Bucket versioning is on, so objects are never
overwritten; retraction changes database status, not bytes.

## Consequences

**Positive.** Content addressing makes a digest a resolvable location
([REPRODUCIBILITY.md §5](../REPRODUCIBILITY.md)). Database backups stay small. Keys carry the
workspace id, so storage isolation matches RLS isolation ([SECURITY.md §3](../SECURITY.md)).

**Negative.** One more stateful service and a second place a backup can fail — hence the hourly
mirror in [DOCKER_SWARM.md §9](../DOCKER_SWARM.md). Cross-store consistency needs care: an object
written before its row commits is an orphan, so uploads are idempotent by digest and orphans are
swept nightly.

**Neutral.** Any S3 endpoint is a configuration change, including a cloud bucket.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Postgres large objects | backup and vacuum cost on the service that must never be slow |
| Cloud S3 only | the MVP must run on one Swarm without cloud credentials |
| Local filesystem volumes | no versioning, no tenancy prefixes, breaks under multi-node placement |

## Links

[ARCHITECTURE.md §2](../ARCHITECTURE.md) · [DATA_MODEL.md §8](../DATA_MODEL.md) ·
[ADR-020](ADR-020-stateful-ha-boundary.md)
