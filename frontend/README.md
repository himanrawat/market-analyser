# Frontend

This is the Next.js frontend for Market Analyser.

## What lives here

- dashboard
- ranked lists
- actions
- portfolio
- journal
- news
- stock detail
- settings

The frontend talks to the FastAPI backend through the adapter layer in [src/lib/api.ts](src/lib/api.ts).

## Run locally

```bash
npm install
npm run dev
```

Set `NEXT_PUBLIC_API_URL` in `frontend/.env.local` if the API is not running on `http://localhost:8000`.

## Production build

```bash
./node_modules/.bin/next build --webpack
```

## Notes

- The root project documentation is in [../README.md](../README.md).
- PRD mapping and verification notes are in [../docs/IMPLEMENTATION_STATUS.md](../docs/IMPLEMENTATION_STATUS.md).
