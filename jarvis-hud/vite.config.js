import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Porta fixa do HUD (5173 costuma estar ocupada por outros projetos); a API libera só esta origem no CORS.
export default defineConfig({
  plugins: [react()],
  server: { port: 5299, strictPort: true },
})
