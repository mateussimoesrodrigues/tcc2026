/*
 * Etiqueta eletronica de prateleira -- firmware de referencia (ESP32).
 *
 * O que este sketch ja faz (nao depende de qual display fisico voce
 * escolher):
 *   1. Conecta no wifi da loja.
 *   2. Manda POST /displays/sincronizar pra API (autenticado por
 *      DISPLAY_TOKEN, ver config.h) com telemetria (bateria/sinal/mac).
 *   3. Recebe de volta o preco vigente do produto vinculado a este
 *      display (ou "sem produto" se ainda nao foi vinculado no painel).
 *   4. So redesenha a tela se o preco mudou desde o ultimo ciclo (evita
 *      refresh desnecessario -- importante em e-paper, que e lento/tem
 *      vida util de ciclos limitada).
 *   5. Dorme (deep sleep) ate o proximo ciclo, no intervalo que a propria
 *      API manda (`proximo_sync_em_segundos` -- configuravel no backend
 *      sem reflashear nada, ver DISPLAY_SYNC_INTERVALO_SEGUNDOS).
 *
 * O que FALTA e depende do display fisico que voce comprar:
 *   -> a funcao `desenharEtiqueta()` la embaixo. Por enquanto ela so
 *      imprime no Serial. Trocar pela chamada da biblioteca do seu
 *      display (GxEPD2 pra e-paper, TFT_eSPI pra TFT/ILI9341, U8g2 pra
 *      OLED monocromatico, etc.) -- exemplos comentados dentro da funcao.
 *
 * Ver docs/displays-fisicos.md (raiz do repo) pra arquitetura completa,
 * contrato da API, opcoes de hardware e checklist de montagem.
 *
 * Dependencias (Arduino IDE > Sketch > Include Library > Manage Libraries):
 *   - ArduinoJson (Benoit Blanchon), v7.x
 *   (WiFi, WiFiClientSecure, HTTPClient ja vem com o core do ESP32)
 *
 * Placa: qualquer dev board ESP32 (ex.: ESP32-DevKitC, ESP32-WROOM-32).
 * Arduino IDE > Tools > Board > procurar "ESP32" (instalar o pacote
 * "esp32 by Espressif Systems" no Boards Manager se ainda nao tiver).
 */

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

#include "config.h"  // copie de config.example.h e preencha (nao commitar)

// --- Ajustes -----------------------------------------------------------

// true  = ESP32 dorme entre sincronizacoes (recomendado p/ display a
//         bateria, ex.: e-paper -- economiza bateria de verdade).
// false = fica ligado e so espera com delay() (útil pra bancada/demo,
//         mantém o Serial Monitor sem cortes e não precisa de bateria).
#define USE_DEEP_SLEEP true

// Pino ADC ligado a um divisor de tensao na bateria (2x resistor, ex.:
// 100k+100k do + da bateria ate o GND, meio no pino). Deixe como -1 se o
// display nao for a bateria (ex.: prototipo de bancada via USB).
#define BATTERY_ADC_PIN -1
#define BATTERY_ADC_VMAX 4.2f  // tensao da bateria cheia (LiPo 1S)
#define BATTERY_ADC_VMIN 3.0f  // tensao considerada "vazia"

// Timeout de cada chamada HTTP, em ms.
#define HTTP_TIMEOUT_MS 15000

// --- Estado persistido entre ciclos de deep sleep -----------------------
// RTC_DATA_ATTR sobrevive ao deep sleep (fica na RTC memory), mas eh
// resetado se o ESP32 perder energia de vez (bateria removida) -- nesse
// caso o primeiro ciclo depois de religar sempre redesenha, o que é o
// comportamento certo (não tem como saber o que estava desenhado antes).
RTC_DATA_ATTR char ultimoPrecoDesenhado[16] = "";
RTC_DATA_ATTR bool primeiraExecucao = true;

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf("\n[%s] acordando...\n", DISPLAY_LABEL);

  conectarWifi();

  StaticJsonDocument<768> resposta;
  bool ok = sincronizar(resposta);

  int proximoSyncSegundos = 300;  // fallback se a API nao respondeu

  if (ok) {
    proximoSyncSegundos = resposta["proximo_sync_em_segundos"] | 300;
    bool temProduto = resposta["tem_produto"] | false;

    if (!temProduto) {
      Serial.println("Display sem produto vinculado ainda (configure no painel do funcionario).");
      desenharSemProduto();
    } else {
      const char* precoVigente = resposta["preco_vigente"] | "";
      bool precoMudou = primeiraExecucao || strcmp(precoVigente, ultimoPrecoDesenhado) != 0;

      if (precoMudou) {
        Serial.printf("Preco mudou (%s -> %s), redesenhando.\n", ultimoPrecoDesenhado, precoVigente);
        desenharEtiqueta(resposta);
        strncpy(ultimoPrecoDesenhado, precoVigente, sizeof(ultimoPrecoDesenhado) - 1);
      } else {
        Serial.println("Preco sem mudanca -- sem redesenho.");
      }
    }
    primeiraExecucao = false;
  } else {
    Serial.println("Sync falhou -- mantem o que ja esta na tela, tenta de novo no proximo ciclo.");
  }

  WiFi.disconnect(true);
  dormirOuEsperar(proximoSyncSegundos);
}

void loop() {
  // Vazio de proposito: com USE_DEEP_SLEEP=true o ESP32 reinicia (volta
  // pro setup()) a cada ciclo. Com USE_DEEP_SLEEP=false, dormirOuEsperar()
  // ja faz o delay() e devolve pra ca so pra loop() rodar de novo sem
  // fazer nada -- o trabalho real e todo feito no setup().
}

// --- Wifi ----------------------------------------------------------------

void conectarWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.printf("Conectando em \"%s\"", WIFI_SSID);
  unsigned long inicio = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - inicio < 20000) {
    delay(400);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("Wifi ok, IP %s, RSSI %d dBm\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
  } else {
    Serial.println("Wifi FALHOU -- segue sem rede, tenta de novo no proximo ciclo.");
  }
}

// --- Sincronizacao com a API ---------------------------------------------

int lerBateriaPct() {
  if (BATTERY_ADC_PIN < 0) return -1;  // sem leitura de bateria configurada

  int leitura = analogRead(BATTERY_ADC_PIN);
  float tensao = (leitura / 4095.0f) * 3.3f * 2.0f;  // *2 porque o divisor eh 50/50
  float pct = (tensao - BATTERY_ADC_VMIN) / (BATTERY_ADC_VMAX - BATTERY_ADC_VMIN) * 100.0f;
  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;
  return (int)pct;
}

// Preenche `resposta` com o JSON devolvido pela API. Retorna false se a
// chamada falhou (sem wifi, timeout, erro HTTP) -- nesse caso o
// dispositivo simplesmente mantem o preco que ja estava na tela.
bool sincronizar(StaticJsonDocument<768>& resposta) {
  if (WiFi.status() != WL_CONNECTED) return false;

  WiFiClientSecure client;
  // TRADE-OFF DE SEGURANCA: pula a validacao do certificado TLS do
  // servidor. Em microcontrolador embarcado, validar a cadeia de
  // certificados de verdade exige guardar/atualizar o CA root da API
  // (ex.: Let's Encrypt, usado pelo Render) manualmente no firmware, o
  // que da trabalho de manter. Pra uma etiqueta de preco (nao lida com
  // senha/pagamento -- so le um preco publico e manda telemetria de
  // bateria/sinal), o risco de um MITM na rede local da loja e aceitavel
  // pro escopo do TCC. Se quiser fechar isso depois, troque por
  // `client.setCACert(...)` com o CA root certo.
  client.setInsecure();

  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  String url = String(API_BASE_URL) + "/displays/sincronizar";

  if (!http.begin(client, url)) {
    Serial.println("http.begin falhou (URL invalida?)");
    return false;
  }

  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Display-Token", DISPLAY_TOKEN);

  StaticJsonDocument<256> corpo;
  int bateria = lerBateriaPct();
  if (bateria >= 0) corpo["bateria_pct"] = bateria;
  corpo["rssi_dbm"] = WiFi.RSSI();
  corpo["mac"] = WiFi.macAddress();

  String corpoStr;
  serializeJson(corpo, corpoStr);

  int status = http.POST(corpoStr);
  Serial.printf("POST /displays/sincronizar -> HTTP %d\n", status);

  bool ok = false;
  if (status == 200) {
    DeserializationError err = deserializeJson(resposta, http.getStream());
    ok = !err;
    if (err) Serial.printf("JSON invalido: %s\n", err.c_str());
  } else if (status == 401) {
    Serial.println("Token invalido/desativado -- confira o cadastro do display no painel.");
  } else {
    Serial.printf("Corpo da resposta: %s\n", http.getString().c_str());
  }

  http.end();
  return ok;
}

// --- Renderizacao (PENDENTE -- depende do display escolhido) ------------

// Chamado quando o preco (vigente) mudou desde o ultimo desenho.
// `dados` tem os campos do endpoint DisplayEstadoResponse -- ver
// backend/app/schemas/display.py ou docs/displays-fisicos.md.
void desenharEtiqueta(StaticJsonDocument<768>& dados) {
  const char* nome = dados["produto_nome"] | "?";
  const char* marca = dados["marca"] | "";
  const char* tamanho = dados["tamanho"] | "";
  const char* precoVigente = dados["preco_vigente"] | "?";
  bool promocaoAtiva = dados["promocao_ativa"] | false;
  const char* precoNormal = dados["preco_normal"] | "";

  Serial.println("==================================");
  Serial.printf("  %s %s %s\n", nome, marca, tamanho);
  if (promocaoAtiva) {
    Serial.printf("  DE R$ %s  POR R$ %s (promocao)\n", precoNormal, precoVigente);
  } else {
    Serial.printf("  R$ %s\n", precoVigente);
  }
  Serial.println("==================================");

  // TODO: troque o bloco acima (ou mantenha em paralelo pra debug) por
  // uma chamada de verdade na biblioteca do seu display. Exemplos:
  //
  // -- e-paper (biblioteca GxEPD2, ex.: Waveshare 2.13"/2.9") --
  //   display.setFullWindow();
  //   display.firstPage();
  //   do {
  //     display.fillScreen(GxEPD_WHITE);
  //     display.setTextColor(GxEPD_BLACK);
  //     display.setFont(&FreeSansBold18pt7b);
  //     display.setCursor(10, 40);
  //     display.print(nome);
  //     display.setFont(&FreeSansBold24pt7b);
  //     display.setCursor(10, 90);
  //     display.print("R$ ");
  //     display.print(precoVigente);
  //   } while (display.nextPage());
  //
  // -- TFT (biblioteca TFT_eSPI) --
  //   tft.fillScreen(TFT_WHITE);
  //   tft.setTextColor(TFT_BLACK);
  //   tft.setTextSize(2);
  //   tft.setCursor(10, 10);
  //   tft.println(nome);
  //   tft.setTextSize(4);
  //   tft.setCursor(10, 50);
  //   tft.print("R$ ");
  //   tft.println(precoVigente);
}

void desenharSemProduto() {
  Serial.println("[etiqueta] -- display sem produto vinculado --");
  // TODO: mesma ideia -- desenhar um placeholder ("sem produto") na tela
  // real quando `tem_produto=false`.
}

// --- Espera ate o proximo ciclo ------------------------------------------

void dormirOuEsperar(int segundos) {
  Serial.printf("Proximo sync em %d s.\n", segundos);

#if USE_DEEP_SLEEP
  Serial.flush();
  esp_sleep_enable_timer_wakeup((uint64_t)segundos * 1000000ULL);
  esp_deep_sleep_start();
  // Nao volta daqui -- o ESP32 reinicia e roda setup() de novo.
#else
  delay((unsigned long)segundos * 1000UL);
#endif
}
