// Copie este arquivo para "config.h" (mesma pasta) e preencha com os
// valores reais -- "config.h" está no .gitignore, nunca é commitado
// (tem senha de wifi e o token do display).
//
// Um "config.h" por dispositivo/prateleira: se você tem 5 displays, grava
// esse mesmo .ino em cada um, trocando só o config.h antes de cada upload
// (nome do display e token diferentes por dispositivo).

#pragma once

// Rede wifi da loja (2.4GHz -- o ESP32 não conecta em 5GHz).
#define WIFI_SSID "nome-da-rede"
#define WIFI_PASSWORD "senha-da-rede"

// URL base da API (Render). Sem barra no final.
// Local (mesma rede que o PC rodando uvicorn): "http://192.168.0.X:8000"
// Produção: "https://SEU-SERVICO.onrender.com"
#define API_BASE_URL "https://SEU-SERVICO.onrender.com"

// Token deste display específico -- copiado da tela "Displays" do painel
// do funcionário (ou de POST /displays) na hora de cadastrar o
// dispositivo. Cada display tem o seu; não reutilizar entre dispositivos.
#define DISPLAY_TOKEN "cole-aqui-o-token-gerado-pelo-backend"

// Nome só para aparecer nos logs Serial deste dispositivo (não é enviado
// à API -- o nome "de verdade" é o cadastrado no painel).
#define DISPLAY_LABEL "prateleira-1"
