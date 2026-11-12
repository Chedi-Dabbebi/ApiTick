import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Same-origin requests in dev: no CORS configuration needed on the API.
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
