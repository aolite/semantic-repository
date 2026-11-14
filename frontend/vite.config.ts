/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    // Valores ficticios solo para las pruebas: no apuntan a ningún servicio real.
    env: {
      VITE_API_BASE_URL: 'http://api.test',
      VITE_BASE_URI: 'http://uri.test/itot/',
    },
  },
})
