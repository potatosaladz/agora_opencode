# Agora frontend

React 18 + strict TypeScript + Vite skeleton. TanStack Query owns server-state
caching; authored OpenAPI generates `src/api/types.ts`.

```bash
npm ci
npm run generate:api
npm run dev
```

Development server proxies `/health`, `/ready`, `/metrics`, and `/api` to
`http://127.0.0.1:18000` by default (the `BACKEND_HOST_PORT` of the Compose stack). Override with
`VITE_API_PROXY_TARGET`, or with `VITE_API_BASE_URL` when the API is on another origin. Run
`npm run lint`, `npm run typecheck`, `npm test`, `npm run format`, and
`npm run contract:check` before committing.
