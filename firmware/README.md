# Firmware dos displays físicos

Sketch de referência (ESP32 + Arduino) para as etiquetas eletrônicas de
prateleira. Arquitetura completa, contrato de API e opções de hardware:
ver [`docs/displays-fisicos.md`](../docs/displays-fisicos.md) na raiz do
repo -- este README é só o "como compilar e gravar".

## O que já funciona vs. o que falta

`esp32_display_preco/esp32_display_preco.ino` já resolve toda a parte de
rede: conecta no wifi, autentica com a API, busca o preço vigente do
produto vinculado, decide se precisa redesenhar e dorme (deep sleep) até
o próximo ciclo. **O que falta é só a função `desenharEtiqueta()`** --
ela hoje só imprime no Serial Monitor porque ainda não sabemos qual
display físico você vai usar. Assim que escolher o modelo, é só trocar
essa função pela chamada da biblioteca correspondente (exemplos
comentados dentro do próprio arquivo, para GxEPD2/e-paper e TFT_eSPI).

## Compilando (Arduino IDE)

1. Instale a [Arduino IDE](https://www.arduino.cc/en/software) (2.x).
2. `File > Preferences` -> em "Additional Boards Manager URLs" adicione:
   `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
3. `Tools > Board > Boards Manager` -> busque "esp32" (Espressif Systems) -> instalar.
4. `Sketch > Include Library > Manage Libraries` -> instale **ArduinoJson** (Benoit Blanchon, v7.x).
   Se for usar e-paper, instale também **GxEPD2** (+ a dependência **Adafruit GFX Library**) aqui; para TFT, **TFT_eSPI**.
5. Abra `firmware/esp32_display_preco/esp32_display_preco.ino`.
6. Copie `config.example.h` para `config.h` (mesma pasta) e preencha
   wifi/URL da API/token do display (token gerado na tela "Displays" do
   painel do funcionário, ou via `POST /displays` -- ver
   `docs/displays-fisicos.md`). **Nunca commite `config.h`** (já está no
   `.gitignore` do repo).
7. `Tools > Board` -> selecione sua placa ESP32 (ex.: "ESP32 Dev Module").
8. Conecte o ESP32 por USB, selecione a porta em `Tools > Port`, clique
   em Upload.
9. `Tools > Serial Monitor` (115200 baud) para ver os logs -- primeiro
   teste sem display nenhum ligado já mostra no Serial se a
   autenticação/sincronização estão funcionando.

## Compilando (PlatformIO, alternativa)

Se preferir PlatformIO (VS Code), crie um `platformio.ini` neste
diretório com algo como:

```ini
[env:esp32dev]
platform = espressif32
board = esp32dev
framework = arduino
monitor_speed = 115200
lib_deps =
    bblanchon/ArduinoJson @ ^7
    ; zinggjm/GxEPD2 @ ^1.5   ; se for usar e-paper
```

(Não incluído por padrão porque o projeto ainda não fixou o board/display
exatos -- ajuste `board` e `lib_deps` conforme o hardware escolhido.)

## Testando sem hardware nenhum ainda

Dá para validar o backend + firmware isoladamente antes de decidir o
display:

- **Backend isolado**: crie um display pelo Swagger (`/docs`,
  `POST /displays`) e simule o dispositivo com curl/Postman batendo em
  `POST /displays/sincronizar` com o header `X-Display-Token` -- exemplos
  em `docs/displays-fisicos.md`.
- **Firmware isolado**: grave o `.ino` num ESP32 de teste (qualquer dev
  board, ~R$20-30) sem display nenhum conectado -- os logs no Serial
  Monitor já mostram se ele está conseguindo se conectar, autenticar e
  receber o preço certo. Só depois de validar isso vale comprar os
  displays em quantidade.

## Um firmware por dispositivo?

O mesmo `.ino` serve para todos -- o que muda entre displays é só o
`config.h` (nome/token). Grave o mesmo sketch em cada ESP32, trocando o
`config.h` antes de cada upload (ou, se quiser evoluir depois, migre
`WIFI_SSID`/`DISPLAY_TOKEN` para um portal de configuração via BLE/AP
(`WiFiManager`) para não precisar recompilar por dispositivo -- fora do
escopo do MVP, mas é o caminho natural se a quantidade de displays
crescer).
