import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')

  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      proxy: {
        '/health': env.VITE_API_PROXY || 'http://localhost:8000',
        '/chat': env.VITE_API_PROXY || 'http://localhost:8000',
        '/ingest': env.VITE_API_PROXY || 'http://localhost:8000',
      },
    },
  }
})