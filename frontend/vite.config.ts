import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
// This file executes only in Node. Credentials never enter the client module graph.
// @ts-ignore JavaScript middleware is shared with the production server.
import { createApiHandler, loadEnvironment } from './server/api.mjs';

loadEnvironment();

export default defineConfig({
  plugins: [react(), {
    name: 'meridian-local-api',
    configureServer(server) {
      const handler = createApiHandler();
      server.middlewares.use((req, res, next) => {
        if (req.url?.startsWith('/api/')) void handler(req, res);
        else next();
      });
    },
  }],
  server: { port: 5173, strictPort: true },
});
