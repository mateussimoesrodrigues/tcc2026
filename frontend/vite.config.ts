import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
// Icones da PWA em public/: favicon-192.png e favicon-512.png (purpose "any")
// e favicon-maskable-512.png (fundo cheio, sem cantos transparentes, pra
// plataforma poder recortar na forma dela). Os tres sao renderizacoes do
// proprio public/favicon.svg da marca.
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      // Estaticos de public/ que o service worker tambem guarda (o padrao
      // so inclui js/css/html), pra o icone existir com o app offline.
      includeAssets: ['favicon.svg', 'favicon.ico', 'favicon-180.png'],
      manifest: {
        name: 'Precix.AI',
        lang: 'pt-BR',
        short_name: 'Precix.AI',
        description: 'Precificação inteligente para varejo físico: margens, estoque e promoções com IA.',
        theme_color: '#0F766E',
        // Grafite da marca: e o fundo do icone, entao a tela de abertura
        // da PWA nao mostra uma moldura branca em volta dele.
        background_color: '#0B1220',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: 'favicon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: 'favicon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: 'favicon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
    }),
  ],
})
