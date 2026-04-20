import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// Vite config is evaluated in Node, so we read from process.env plus the
// repo-root / frontend-local .env files. `TASKFLOW_*` mirrors the backend
// settings; VITE_* is Vite's standard prefix (also exposed to the browser).
export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), ''), ...loadEnv(mode, '..', '') };
  const host = env.TASKFLOW_FRONTEND_HOST || env.VITE_HOST || 'localhost';
  const port = Number(env.TASKFLOW_FRONTEND_PORT || env.VITE_PORT || 5173);
  const apiHost = env.TASKFLOW_API_HOST_PUBLIC || env.VITE_API_HOST || 'localhost';
  const apiPort = env.TASKFLOW_API_PORT || env.VITE_API_PORT || 8000;
  const apiTarget = env.VITE_API_TARGET || `http://${apiHost}:${apiPort}`;

  return {
    plugins: [react()],
    server: {
      host, // pass `true` or `0.0.0.0` to bind LAN; env var drives it
      port,
      // Expose to LAN when requested via env. Strict false so port conflicts are fatal.
      strictPort: true,
      proxy: {
        '/api': { target: apiTarget, changeOrigin: false },
      },
    },
    preview: {
      host,
      port,
    },
  };
});
