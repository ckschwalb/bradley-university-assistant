import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The backend serves the production build from frontend/build, with assets under /static
// (see backend/main.py and the Dockerfile), so the build keeps that layout.
export default defineConfig({
  plugins: [react()],
  build: { outDir: 'build', assetsDir: 'static' },
  server: {
    port: 3000, // the backend's CORS allow-list includes http://localhost:3000
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/chat': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true, // testing-library cleans up between tests through the global afterEach
    setupFiles: './src/setupTests.js',
  },
});
