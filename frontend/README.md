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

## Data notes

- India fundamentals are moving to a hybrid backend lane: official NSE/BSE data first, vendor fallback after that.
- The frontend does not talk to any data vendor directly and does not need source-specific logic for this change.
- As the backend starts ingesting richer official India fundamentals, the existing stock/detail/ranked screens will automatically benefit through the normalized API layer.

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
