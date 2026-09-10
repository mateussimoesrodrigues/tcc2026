// Copie este arquivo para "config.h" (mesma pasta) e preencha com os
// valores reais -- "config.h" está no .gitignore, nunca é commitado
// (tem senha de wifi, token do display e credencial do broker).
//
// Um "config.h" por dispositivo: se você tem 3 displays, grava esse mesmo
// .ino em cada um trocando só o config.h antes do upload (o DISPLAY_TOKEN
// é diferente por dispositivo).

#pragma once

// --- Wifi ----------------------------------------------------------------
// Rede 2.4GHz -- o ESP32 não conecta em 5GHz.
#define WIFI_SSID "nome-da-rede"
#define WIFI_PASSWORD "senha-da-rede"

// --- Backend -------------------------------------------------------------
// URL base da API, sem barra no final. Usada UMA vez, no boot, para pegar
// o preço atual antes da primeira mensagem MQTT.
// Local (mesma rede que o PC rodando uvicorn): "http://192.168.0.X:8000"
// Produção: "https://SEU-SERVICO.onrender.com"
#define API_BASE_URL "https://SEU-SERVICO.onrender.com"

// Token deste display específico -- copiado da tela "Displays" do painel
// do funcionário (ou da resposta de POST /displays) na hora de cadastrar.
// Cada display tem o seu; não reutilizar entre dispositivos.
#define DISPLAY_TOKEN "cole-aqui-o-token-gerado-pelo-backend"

// --- Broker MQTT ---------------------------------------------------------
// Precisa ser o MESMO broker configurado no backend (MQTT_HOST/MQTT_PORT
// no .env). Opções gratuitas que servem para o TCC:
//   - HiveMQ Cloud (https://console.hivemq.cloud): gerenciado, exige TLS
//     na porta 8883 e usuário/senha. Não precisa instalar nada.
//   - mosquitto local na LAN da loja: porta 1883 sem TLS (defina
//     MQTT_USE_TLS 0 abaixo).
#define MQTT_HOST "seu-cluster.s1.eu.hivemq.cloud"
#define MQTT_PORT 8883

// 1 = TLS (obrigatório em broker gerenciado, porta 8883)
// 0 = sem TLS (mosquitto local, porta 1883)
#define MQTT_USE_TLS 1

// Deixe as duas strings vazias ("") se o broker aceitar conexão anônima
// (típico de mosquitto local sem configuração de ACL).
#define MQTT_USERNAME "usuario-do-broker"
#define MQTT_PASSWORD "senha-do-broker"

// Prefixo do tópico -- tem que bater com MQTT_TOPIC_PREFIX do backend.
// O firmware monta o tópico completo sozinho, como
// "{MQTT_TOPIC_PREFIX}/{display_id}/preco", usando o display_id que vem
// na resposta do sync do boot. Você NÃO precisa configurar o id aqui.
#define MQTT_TOPIC_PREFIX "loja/displays"

// --- Diagnóstico ---------------------------------------------------------
// Nome só para aparecer nos logs Serial deste dispositivo (não é enviado
// à API -- o nome "de verdade" é o cadastrado no painel).
#define DISPLAY_LABEL "prateleira-1-oled"
