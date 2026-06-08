/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // Split ONLY the always-loaded, slow-changing core (React + router +
        // React Query) into its own long-cache chunk. This trims the main
        // index chunk under the 500 kB warning and means a routine app redeploy
        // doesn't bust the vendor cache. Heavy per-page libs (recharts,
        // @fullcalendar, @dnd-kit) are deliberately NOT split here — they're
        // already code-split into the lazy page chunks that use them, so forcing
        // them into an eager vendor chunk would REGRESS first-paint on every
        // other page.
        manualChunks(id: string) {
          if (
            /[\\/]node_modules[\\/](react|react-dom|react-router|react-router-dom|scheduler|use-sync-external-store|@tanstack[\\/]react-query)[\\/]/.test(
              id,
            )
          ) {
            return 'react-vendor'
          }
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
})
