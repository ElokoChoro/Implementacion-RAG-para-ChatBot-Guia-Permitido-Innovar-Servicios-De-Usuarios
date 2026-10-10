import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // El backend (uvicorn app.api:app) no expone CORS: el navegador le habla a Vite
    // y Vite le reenvía las consultas.
    proxy: {
      '/ia': process.env.RAG_API_URL ?? 'http://localhost:8000',
      // Formatos y tope de los adjuntos (src/lib/rag.ts › leerLimites)
      '/salud': process.env.RAG_API_URL ?? 'http://localhost:8000',
    },
  },
})
