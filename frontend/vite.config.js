import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// VITE_API_PORT lets multiple isolated dev instances (each with its own
// backend + data copy) run side by side without editing this shared file.
const apiPort = process.env.VITE_API_PORT || '8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: { '/api': `http://127.0.0.1:${apiPort}` },
  },
})
