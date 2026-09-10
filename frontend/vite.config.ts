import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
// Icones em public/pwa-192.png e pwa-512.png sao um placeholder gerado
// (carrinho de compras simples) -- trocar por um icone definitivo antes
// da entrega final do TCC.
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'Precificação Inteligente',
        short_name: 'Precificação',
        description: 'Escaneie produtos, monte seu carrinho e finalize a compra.',
        theme_color: '#0c1017',
        background_color: '#ffffff',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: 'pwa-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'pwa-512.png', sizes: '512x512', type: 'image/png' },
          { src: 'pwa-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
    }),
  ],
})
