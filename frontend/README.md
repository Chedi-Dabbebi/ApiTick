# Frontend

React 19 + TypeScript + Vite client for ApiTick.

See the [root README](../README.md) for setup, architecture and screenshots.

```powershell
npm install
npm run dev      # http://localhost:5173, proxies /api to 127.0.0.1:8000
npm run lint     # oxlint
npm run build    # tsc -b && vite build
```

All styling lives in `src/index.css` — there is no CSS framework and no
CSS-in-JS, so the whole look can be replaced in one file.
