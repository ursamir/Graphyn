import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

/** Separate from vite.config.ts so local root-owned node_modules/.vite-temp cannot block builds. */
export default defineConfig({
  plugins: [react()],
  cacheDir: '/tmp/graphyn-ui-vitest-cache',
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
