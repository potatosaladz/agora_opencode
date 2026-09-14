# API contracts

`openapi.yaml` is the reviewed, authored OpenAPI 3.1 description consumed by the
frontend. FastAPI's runtime OpenAPI and documentation routes intentionally remain
disabled. Only implemented endpoints belong in this file.

T3-00 freezes planned Phase 3 shapes in `docs/API_CONTRACTS.md`; T3-07 adds them here only with
runtime routes and regenerated TypeScript. This separation prevents design endpoints being advertised
as executable.

From `frontend/`, run `npm run generate:api`. CI runs the same generator and fails
if `src/api/types.ts` changes. `errors.yaml` mirrors the stable backend error taxonomy.

`events/reasoning-event.json` is the strict NATS/SSE wire envelope. Transport consumers order by
`ledger_seq`, deduplicate by `event_id`, and treat payload values as resource references only.
