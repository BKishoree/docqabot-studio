/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server on 5173 proxies the API to the Studio app on 127.0.0.1:8000 (DESIGN 6.3).
export default defineConfig({
  plugins: [react()],
  base: '/',
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false } },
  },
  build: { outDir: 'dist', assetsDir: 'assets', sourcemap: false },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}', 'tests/**/*.test.{ts,tsx}'],
    pool: 'threads',
    maxWorkers: 2,
    // Several 5 s findBy waits can run in one test (BUG-006); Vitest's default is 5 s.
    testTimeout: 20_000,
    css: false,
  },
})
