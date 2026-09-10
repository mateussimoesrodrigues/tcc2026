/*
 * Etiqueta eletronica de prateleira -- VARIANTE DE DEMONSTRACAO (ESP32).
 *
 *   Modelo: OLED SSD1306 128x64 + MQTT PUSH + alimentacao fixa (USB/fonte).
 *
 * Feita pra banca: quando o funcionario aprova uma promocao no painel, o
 * backend PUBLICA o preco novo no topico deste display e a tela muda na
 * hora, sem esperar nenhum ciclo de polling. O preco de trocar isso e a
 * autonomia: este sketch NAO dorme (precisa manter a conexao MQTT viva),
 * entao o dispositivo tem que ficar na tomada.
 *
 * A variante de PRODUCAO continua ao lado, em
 * `firmware/esp32_display_preco_epaper_pull/` (e-paper + polling + deep
 * sleep + bateria). Nenhuma substitui a outra -- ver a comparacao em
 * `docs/displays-fisicos.md`.
 *
 * Fluxo:
 *   1. Conecta no wifi da loja.
 *   2. BOOT: uma unica chamada HTTP a POST /displays/sincronizar (mesma
 *      rota e mesmo token da variante de producao) pra ja ligar mostrando
 *      o preco atual, antes de qualquer mensagem MQTT chegar.
 *   3. Conecta no broker MQTT (TLS) e se inscreve em
 *      `loja/displays/{display_id}/preco` -- o `display_id` vem da
 *      resposta do passo 2, entao nao precisa ser configurado a mao.
 *   4. Toda mensagem que chegar nesse topico e o MESMO JSON do sync: um
 *      unico parser (`aplicarEstado`) serve pros dois caminhos.
 *   5. Loop mantem wifi e MQTT vivos, reconectando com backoff se cair.
 *
 * Dependencias (Arduino IDE > Sketch > Include Library > Manage Libraries):
 *   - ArduinoJson (Benoit Blanchon), v7.x
 *   - PubSubClient (Nick O'Leary), v2.8
 *   - U8g2 (oliver), v2.35+
 *   (WiFi, WiFiClientSecure e HTTPClient ja vem com o core do ESP32)
 *
 * Ligacao do OLED (I2C), ver README.md desta pasta:
 *   VCC -> 3V3   GND -> GND   SDA -> GPIO21   SCL -> GPIO22
 */

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <PubSubClient.h>
#include <U8g2lib.h>
#include <Wire.h>

#include "config.h"  // copie de config.example.h e preencha (nao commitar)

// --- Ajustes -------------------------------------------------------------

#define HTTP_TIMEOUT_MS 15000
#define I2C_SDA 21
#define I2C_SCL 22
#define OLED_ENDERECO_I2C 0x3C

// PubSubClient tem buffer padrao de 256 bytes, pequeno demais pro nosso
// JSON (nome de produto + precos + timestamps passa disso). Sem aumentar,
// a mensagem chega TRUNCADA e o parse falha silenciosamente -- foi o
// primeiro problema a aparecer na bancada.
#define MQTT_BUFFER_BYTES 1024

// Backoff de reconexao ao broker: nao adianta martelar de 100ms.
#define MQTT_RETRY_MS 5000
#define WIFI_RETRY_MS 10000

// --- Display -------------------------------------------------------------
// Construtor "F" = full framebuffer (1KB de RAM). Cabe folgado no ESP32 e
// permite montar a tela inteira antes de mandar pro OLED, sem flicker.
U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, /* reset=*/ U8X8_PIN_NONE);

// --- Rede ----------------------------------------------------------------
WiFiClientSecure clienteTlsMqtt;
WiFiClient clienteSimplesMqtt;
PubSubClient mqtt;

// --- Estado --------------------------------------------------------------
int displayId = -1;                 // preenchido pelo sync do boot
char topicoPreco[96] = "";
unsigned long ultimaTentativaMqtt = 0;
unsigned long ultimaTentativaWifi = 0;

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf("\n[%s] iniciando (variante OLED + MQTT)\n", DISPLAY_LABEL);

  iniciarDisplay();
  desenharMensagem("Conectando", "wifi...");

  conectarWifi();

  // Estado inicial via HTTP: o display ja liga mostrando o preco certo,
  // sem depender de o broker ter mensagem retida nem de esperar a proxima
  // aprovacao de promocao.
  StaticJsonDocument<1024> estado;
  if (sincronizarHttp(estado)) {
    displayId = estado["display_id"] | -1;
    snprintf(topicoPreco, sizeof(topicoPreco), "%s/%d/preco", MQTT_TOPIC_PREFIX, displayId);
    Serial.printf("Topico deste display: %s\n", topicoPreco);
    aplicarEstado(estado);
  } else {
    desenharMensagem("Sem conexao", "com a API");
    Serial.println("Sync do boot falhou -- vou tentar MQTT mesmo assim se o topico for conhecido.");
  }

  configurarMqtt();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    if (millis() - ultimaTentativaWifi > WIFI_RETRY_MS) {
      ultimaTentativaWifi = millis();
      Serial.println("Wifi caiu -- reconectando.");
      conectarWifi();
    }
    return;  // sem wifi nao ha o que fazer com o MQTT
  }

  if (!mqtt.connected()) {
    if (millis() - ultimaTentativaMqtt > MQTT_RETRY_MS) {
      ultimaTentativaMqtt = millis();
      conectarMqtt();
    }
  } else {
    mqtt.loop();  // mantem o keepalive e entrega os callbacks
  }
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
    Serial.println("Wifi FALHOU -- o loop tenta de novo.");
  }
}

// --- Sync HTTP (so no boot) ----------------------------------------------

// Mesma rota e mesmo token da variante de producao. Retorna false se a
// chamada falhou -- nesse caso o display fica esperando o MQTT.
bool sincronizarHttp(StaticJsonDocument<1024>& resposta) {
  if (WiFi.status() != WL_CONNECTED) return false;

  WiFiClientSecure client;
  // Mesmo trade-off consciente da variante de producao: sem validacao da
  // cadeia TLS. Uma etiqueta so le um preco publico e manda telemetria de
  // sinal -- nao ha credencial nem pagamento em jogo. Ver o comentario
  // equivalente em esp32_display_preco_epaper_pull.ino.
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
  corpo["rssi_dbm"] = WiFi.RSSI();
  corpo["mac"] = WiFi.macAddress();
  // Sem bateria_pct de proposito: esta variante e alimentada por fonte.

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
    Serial.println("Token invalido/desativado -- confira o cadastro no painel.");
  } else {
    Serial.printf("Corpo da resposta: %s\n", http.getString().c_str());
  }

  http.end();
  return ok;
}

// --- MQTT ----------------------------------------------------------------

void configurarMqtt() {
#if MQTT_USE_TLS
  // Mesmo trade-off do HTTP acima. Brokers gerenciados (HiveMQ Cloud etc.)
  // exigem TLS na 8883; validar a cadeia exigiria embutir e manter o CA
  // root no firmware.
  clienteTlsMqtt.setInsecure();
  mqtt.setClient(clienteTlsMqtt);
#else
  mqtt.setClient(clienteSimplesMqtt);
#endif

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(MQTT_BUFFER_BYTES);
  mqtt.setKeepAlive(60);
  mqtt.setCallback(aoReceberMensagem);
}

void conectarMqtt() {
  if (topicoPreco[0] == '\0') {
    // Sem display_id ainda (o sync do boot falhou): tenta o sync de novo
    // antes de assinar, senao nao ha topico pra assinar.
    StaticJsonDocument<1024> estado;
    if (sincronizarHttp(estado)) {
      displayId = estado["display_id"] | -1;
      snprintf(topicoPreco, sizeof(topicoPreco), "%s/%d/preco", MQTT_TOPIC_PREFIX, displayId);
      aplicarEstado(estado);
    } else {
      return;
    }
  }

  String clientId = String("display-") + displayId + "-" + String((uint32_t)ESP.getEfuseMac(), HEX);
  Serial.printf("Conectando no broker %s:%d como %s...\n", MQTT_HOST, MQTT_PORT, clientId.c_str());

  // Broker local (mosquitto sem ACL) costuma aceitar conexao anonima: se
  // o usuario ficou vazio no config.h, conecta sem credencial. Checagem em
  // runtime, e nao com #if defined(...), porque o config.h SEMPRE define as
  // duas macros -- so que possivelmente como string vazia.
  bool ok;
  if (strlen(MQTT_USERNAME) > 0) {
    ok = mqtt.connect(clientId.c_str(), MQTT_USERNAME, MQTT_PASSWORD);
  } else {
    ok = mqtt.connect(clientId.c_str());
  }

  if (ok) {
    Serial.println("MQTT conectado.");
    // QoS 1: a mensagem de "entrou em promocao" nao pode se perder.
    // Como o backend publica com retain, ao assinar recebemos na hora o
    // ultimo preco publicado, mesmo que a ultima aprovacao tenha sido
    // antes deste display ligar.
    mqtt.subscribe(topicoPreco, 1);
    Serial.printf("Inscrito em %s\n", topicoPreco);
  } else {
    // rc: -4 timeout, -2 falha de conexao (TLS/host), 4 credencial ruim,
    // 5 nao autorizado. Ver README desta pasta.
    Serial.printf("MQTT falhou, rc=%d -- tento de novo em %d ms\n", mqtt.state(), MQTT_RETRY_MS);
  }
}

void aoReceberMensagem(char* topico, byte* payload, unsigned int tamanho) {
  Serial.printf("MQTT <- %s (%u bytes)\n", topico, tamanho);

  StaticJsonDocument<1024> estado;
  DeserializationError err = deserializeJson(estado, payload, tamanho);
  if (err) {
    Serial.printf("JSON invalido na mensagem MQTT: %s\n", err.c_str());
    return;
  }
  // Mesmo payload do sync HTTP -- por isso um parser so.
  aplicarEstado(estado);
}

// --- Renderizacao --------------------------------------------------------

void iniciarDisplay() {
  Wire.begin(I2C_SDA, I2C_SCL);
  u8g2.setI2CAddress(OLED_ENDERECO_I2C * 2);  // U8g2 espera o endereco deslocado 1 bit
  u8g2.begin();
  u8g2.enableUTF8Print();
}

// Ponto unico de entrada da renderizacao: recebe o JSON (venha do sync
// HTTP ou do MQTT) e decide o que desenhar.
void aplicarEstado(JsonDocument& estado) {
  bool temProduto = estado["tem_produto"] | false;
  if (!temProduto) {
    desenharMensagem("Sem produto", "vinculado");
    return;
  }
  desenharEtiqueta(estado);
}

/*
 * ESTA e a "funcao de desenho especifica do display" que o README aponta
 * como a peca que faltava. Layout do SSD1306 128x64:
 *
 *   +--------------------------------+
 *   | Cola Pano Gliart            .. |  <- nome + marca (fonte pequena)
 *   | de R$ 19,95  (riscado)  +-----+|  <- preco antigo riscado + selo
 *   |                         | -25%||
 *   |  R$ 14,90                +-----+|  <- preco novo, fonte grande
 *   +--------------------------------+
 *
 * Fora de promocao, some o preco riscado e o selo, e o preco vigente fica
 * centralizado e grande.
 */
void desenharEtiqueta(JsonDocument& dados) {
  const char* nome = dados["produto_nome"] | "?";
  const char* marca = dados["marca"] | "";
  const char* precoVigente = dados["preco_vigente"] | "?";
  const char* precoNormal = dados["preco_normal"] | "";
  bool promocaoAtiva = dados["promocao_ativa"] | false;
  // Percentual vem calculado do servidor -- o firmware nao faz conta de
  // preco (ver montar_estado em backend/app/services/display_service.py).
  const char* percentual = dados["percentual_desconto"] | "";

  Serial.printf("[etiqueta] %s | R$ %s%s\n", nome, precoVigente,
                promocaoAtiva ? " (promocao)" : "");

  u8g2.clearBuffer();

  // --- linha 1: nome do produto + marca -----------------------------------
  u8g2.setFont(u8g2_font_6x12_tf);
  char cabecalho[40];
  if (marca && marca[0] != '\0') {
    snprintf(cabecalho, sizeof(cabecalho), "%s %s", nome, marca);
  } else {
    snprintf(cabecalho, sizeof(cabecalho), "%s", nome);
  }
  // 128px / 6px por caractere = 21 caracteres cabem; corta o resto com "..".
  if (strlen(cabecalho) > 21) {
    cabecalho[20] = '.';
    cabecalho[21] = '.';
    cabecalho[22] = '\0';
  }
  u8g2.drawStr(0, 10, cabecalho);
  u8g2.drawHLine(0, 13, 128);

  if (promocaoAtiva) {
    // --- preco antigo, riscado -------------------------------------------
    u8g2.setFont(u8g2_font_6x12_tf);
    char antigo[24];
    snprintf(antigo, sizeof(antigo), "de R$ %s", precoNormal);
    u8g2.drawStr(0, 27, antigo);
    // O "riscado" (line-through) nao existe em fonte de bitmap: desenhamos
    // a linha por cima na metade da altura do texto.
    u8g2.drawHLine(0, 23, u8g2.getStrWidth(antigo));

    // --- selo de desconto, canto superior direito -------------------------
    if (percentual && percentual[0] != '\0') {
      char selo[12];
      // percentual chega como "25.00" -- corta os decimais pro selo.
      int inteiro = atoi(percentual);
      snprintf(selo, sizeof(selo), "-%d%%", inteiro);

      u8g2.setFont(u8g2_font_7x14B_tf);
      int larguraSelo = u8g2.getStrWidth(selo) + 8;
      int xSelo = 128 - larguraSelo;
      u8g2.drawRBox(xSelo, 18, larguraSelo, 17, 3);
      // Texto em "negativo" (fundo preto, letra branca).
      u8g2.setDrawColor(0);
      u8g2.drawStr(xSelo + 4, 31, selo);
      u8g2.setDrawColor(1);
    }

    // --- preco novo, grande ----------------------------------------------
    u8g2.setFont(u8g2_font_logisoso20_tf);
    char novo[24];
    snprintf(novo, sizeof(novo), "R$ %s", precoVigente);
    u8g2.drawStr(0, 60, novo);
  } else {
    // --- sem promocao: so o preco, centralizado --------------------------
    u8g2.setFont(u8g2_font_logisoso24_tf);
    char preco[24];
    snprintf(preco, sizeof(preco), "R$ %s", precoVigente);
    int x = (128 - u8g2.getStrWidth(preco)) / 2;
    if (x < 0) x = 0;
    u8g2.drawStr(x, 48, preco);
  }

  u8g2.sendBuffer();
}

// Telas de estado (sem produto, sem rede) -- mesma fonte, texto centralizado.
void desenharMensagem(const char* linha1, const char* linha2) {
  Serial.printf("[etiqueta] %s %s\n", linha1, linha2);

  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_7x14B_tf);

  int x1 = (128 - u8g2.getStrWidth(linha1)) / 2;
  u8g2.drawStr(x1 < 0 ? 0 : x1, 28, linha1);

  if (linha2 && linha2[0] != '\0') {
    int x2 = (128 - u8g2.getStrWidth(linha2)) / 2;
    u8g2.drawStr(x2 < 0 ? 0 : x2, 46, linha2);
  }

  u8g2.sendBuffer();
}
