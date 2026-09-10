# Firmware dos displays físicos

Sketches de referência (ESP32 + Arduino) para as etiquetas eletrônicas de
prateleira. Arquitetura completa, contrato de API e comparação das
variantes: ver [`docs/displays-fisicos.md`](../docs/displays-fisicos.md)
na raiz do repo -- este README é só o "como compilar e gravar".

## Duas variantes, de propósito

| Pasta | Modelo | Para quê |
|---|---|---|
| [`esp32_display_preco_epaper_pull/`](esp32_display_preco_epaper_pull/) | e-paper + polling HTTP + deep sleep + bateria | **Produção.** É a arquitetura descrita na monografia e a mesma das etiquetas comerciais (ESL): meses de autonomia, imagem persistente. |
| [`esp32_display_preco_oled_mqtt/`](esp32_display_preco_oled_mqtt/) | OLED SSD1306 + push MQTT + alimentação fixa | **Demonstração.** Atualiza a tela em menos de um segundo quando a promoção é aprovada, ao custo de não dormir (precisa ficar na tomada). |

Nenhuma substitui a outra. A de produção existe porque é a resposta certa
para o problema real (etiqueta a bateria numa prateleira); a de
demonstração existe porque numa apresentação ao vivo o que convence é ver
a etiqueta mudar na hora, e ninguém vai medir autonomia de bateria na
banca. O backend atende as duas ao mesmo tempo: publica no MQTT **e**
continua respondendo o polling HTTP.

Cada pasta tem seu próprio README com ligação de hardware, bibliotecas e
diagnóstico. Comece por lá.

## O que já funciona vs. o que falta

- **Variante OLED + MQTT**: completa, incluindo a função de desenho
  (`desenharEtiqueta()` usando U8g2). É a que está pronta para montar.
- **Variante e-paper + polling**: toda a parte de rede está resolvida
  (wifi, autenticação, sync, deep sleep). **Falta a `desenharEtiqueta()`**
  -- ela hoje só imprime no Serial, porque o modelo de e-paper ainda não
  foi comprado. Assim que escolher, trocar pela chamada da GxEPD2
  (exemplos comentados dentro do próprio arquivo).

## Compilando (Arduino IDE)

1. Instale a [Arduino IDE](https://www.arduino.cc/en/software) (2.x).
2. `File > Preferences` -> em "Additional Boards Manager URLs" adicione:
   `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
3. `Tools > Board > Boards Manager` -> busque "esp32" (Espressif Systems) -> instalar.
4. `Sketch > Include Library > Manage Libraries` -> instale conforme a variante:
   - **as duas**: `ArduinoJson` (Benoit Blanchon, v7.x)
   - **OLED + MQTT**: `PubSubClient` (Nick O'Leary, 2.8) e `U8g2` (oliver, 2.35+)
   - **e-paper**: `GxEPD2` (+ a dependência `Adafruit GFX Library`)
5. Abra o `.ino` da variante escolhida (o arquivo tem o mesmo nome da
   pasta -- exigência da Arduino IDE).
6. Copie `config.example.h` para `config.h` (mesma pasta) e preencha.
   **Nunca commite `config.h`** (já está no `.gitignore`: tem senha de
   wifi, token do display e, na variante MQTT, credencial do broker).
7. `Tools > Board` -> selecione sua placa ESP32 (ex.: "ESP32 Dev Module").
8. Conecte o ESP32 por USB, selecione a porta em `Tools > Port`, Upload.
9. `Tools > Serial Monitor` (115200 baud) para ver os logs.

## Compilando (PlatformIO, alternativa)

`platformio.ini` para a variante OLED + MQTT:

```ini
[env:esp32dev]
platform = espressif32
board = esp32dev
framework = arduino
monitor_speed = 115200
lib_deps =
    bblanchon/ArduinoJson @ ^7
    knolleary/PubSubClient @ ^2.8
    olikraus/U8g2 @ ^2.35
```

Para a variante e-paper, troque as duas últimas por
`zinggjm/GxEPD2 @ ^1.5` depois de escolher o modelo da tela.

## Testando sem hardware nenhum

Dá para validar o backend antes de qualquer compra:

- **Sync HTTP**: crie um display pelo Swagger (`/docs`, `POST /displays`)
  e simule o dispositivo com curl batendo em `POST /displays/sincronizar`
  com o header `X-Display-Token` -- exemplos em
  `docs/displays-fisicos.md`.
- **Push MQTT**: com `MQTT_ENABLED=true` no `.env`, use `mosquitto_sub`
  assinando `loja/displays/#` e aprove uma promoção no painel -- a
  mensagem aparece no terminal. O passo a passo completo está em
  `docs/displays-fisicos.md`, seção "Testando o push sem ESP32".
- **Firmware isolado**: grave o `.ino` num ESP32 de teste (~R$20-30) sem
  display conectado -- os logs no Serial já mostram se conectou,
  autenticou e recebeu o preço.

## Um firmware por dispositivo?

O mesmo `.ino` serve para todos -- o que muda entre displays é só o
`config.h` (nome/token). Grave o mesmo sketch em cada ESP32, trocando o
`config.h` antes de cada upload. Na variante MQTT você **não** configura o
número do display: ele descobre o próprio `display_id` na resposta do sync
do boot e monta o tópico sozinho.

Se a quantidade de displays crescer, o caminho natural é migrar
`WIFI_SSID`/`DISPLAY_TOKEN` para um portal de configuração via AP
(`WiFiManager`) e não precisar recompilar por dispositivo -- fora do
escopo do MVP.
