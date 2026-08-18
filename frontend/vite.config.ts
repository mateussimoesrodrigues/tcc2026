import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
// Configuracao completa do PWA (icones, splash, service worker offline)
// sera finalizada na Fase 3, junto com o scanner de camera. Por enquanto
// so o essencial para o navegador reconhecer o app como instalavel.
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'Precificação Inteligente',
        short_name: 'Precificação',
        description: 'Escaneie produtos, monte seu carrinho e finalize a compra.',
        theme_color: '#111111',
        background_color: '#ffffff',
        display: 'standalone',
        start_url: '/',
      },
    }),
  ],
})
