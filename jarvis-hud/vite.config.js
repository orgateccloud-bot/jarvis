import process from 'node:process'
import { existsSync, readFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Token da API local, lido só no servidor de desenvolvimento (nunca embutido no build):
// JARVIS_TOKEN do ambiente → JARVIS_TOKEN do ../.env → arquivo ../dados/.token gerado pela API.
function devToken() {
  if (process.env.JARVIS_TOKEN) return process.env.JARVIS_TOKEN.trim()
  const env = new URL('../.env', import.meta.url)
  if (existsSync(env)) {
    const line = readFileSync(env, 'utf8').split(/\r?\n/).find(l => l.startsWith('JARVIS_TOKEN='))
    const value = line?.slice('JARVIS_TOKEN='.length).trim()
    if (value) return value
  }
  const file = new URL('../dados/.token', import.meta.url)
  return existsSync(file) ? readFileSync(file, 'utf8').trim() : ''
}

// Porta fixa do HUD (5173 costuma estar ocupada por outros projetos); a API libera só esta origem no CORS.
export default defineConfig(({ command }) => {
  const token = command === 'serve' ? devToken() : ''
  return {
    plugins: [react()],
    server: { port: 5299, strictPort: true },
    define: token ? { 'import.meta.env.VITE_JARVIS_TOKEN': JSON.stringify(token) } : {},
  }
})
