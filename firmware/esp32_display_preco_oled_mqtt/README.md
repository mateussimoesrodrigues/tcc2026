# Display de preço — variante OLED + MQTT (demonstração)

Etiqueta de prateleira que **atualiza na hora** quando uma promoção é
aprovada no painel. O ESP32 fica sempre ligado, inscrito num tópico MQTT;
o backend publica o preço novo e a tela muda em menos de um segundo.

> Esta é a variante de **demonstração**. A de **produção** (e-paper +
> polling + deep sleep + bateria) continua em
> [`../esp32_display_preco_epaper_pull/`](../esp32_display_preco_epaper_pull/).
> As duas coexistem de propósito — a comparação e o porquê estão em
> [`docs/displays-fisicos.md`](../../docs/displays-fisicos.md).

## Por que esta variante existe

Para a banca, o que importa é o efeito ao vivo: aprovar a promoção na tela
do notebook e ver a etiqueta física mudar na mesma hora. Autonomia de
bateria não é requisito de demonstração. Então trocamos as duas coisas que
davam autonomia (e-paper + deep sleep) pelas duas que dão reação imediata
(OLED + conexão MQTT sempre aberta), e assumimos a alimentação por fonte.

| | Produção (e-paper) | Demonstração (OLED) |
|---|---|---|
| Tela | e-paper, imagem persistente | OLED SSD1306 128x64 |
| Atualização | polling a cada N segundos | push MQTT, instantâneo |
| Energia | deep sleep, meses de bateria | sempre ligado, USB/fonte |
| Protocolo | HTTP a cada ciclo | HTTP no boot + MQTT depois |

## Hardware

- **Placa**: qualquer dev board ESP32 (ESP32-DevKitC, ESP32-WROOM-32, …).
- **Display**: OLED SSD1306 **128x64**, interface **I2C**, endereço `0x3C`
  (alguns módulos vêm em `0x3D` — se a tela ficar apagada, tente trocar
  `OLED_ENDERECO_I2C` no `.ino`).

### Ligação (I2C)

| OLED | ESP32 |
|---|---|
| `VCC` | `3V3` |
| `GND` | `GND` |
| `SDA` | `GPIO21` |
| `SCL` | `GPIO22` |

São os pinos I2C padrão do ESP32; se usar outros, ajuste `I2C_SDA` /
`I2C_SCL` no topo do `.ino`. O módulo OLED já tem resistores de pull-up
embutidos, então não precisa de nada externo.

> ⚠️ Alimente o OLED em **3V3**, não em 5V. A maioria dos módulos SSD1306
> aceita os dois, mas o nível lógico do ESP32 é 3,3V e 5V no barramento
> pode danificar o GPIO.

## Bibliotecas

Arduino IDE → *Sketch* → *Include Library* → *Manage Libraries*:

| Biblioteca | Autor | Versão |
|---|---|---|
| `ArduinoJson` | Benoit Blanchon | 7.x |
| `PubSubClient` | Nick O'Leary | 2.8 |
| `U8g2` | oliver | 2.35+ |

`WiFi`, `WiFiClientSecure` e `HTTPClient` já vêm com o core do ESP32
(*Boards Manager* → "esp32 by Espressif Systems").

## Configuração

1. Copie `config.example.h` para `config.h` na mesma pasta e preencha.
   O `config.h` está no `.gitignore` — **nunca** é commitado.
2. Cadastre o display no painel (*Funcionário → Displays → novo*), vincule
   a um produto e copie o **token** que aparece uma única vez.
3. Preencha no `config.h`: wifi, `API_BASE_URL`, `DISPLAY_TOKEN` e os
   dados do broker (`MQTT_HOST`, `MQTT_PORT`, usuário/senha).
4. `MQTT_TOPIC_PREFIX` precisa ser **igual** ao `MQTT_TOPIC_PREFIX` do
   `.env` do backend (padrão `loja/displays` nos dois lados).

Você **não** configura o número do display no firmware: ele descobre o
próprio `display_id` na resposta do sync do boot e monta o tópico sozinho.

## Como funciona

```
boot
 └─ conecta wifi
 └─ POST /displays/sincronizar  (HTTP, header X-Display-Token)
     └─ desenha o preço atual            <- já liga mostrando o certo
     └─ lê display_id da resposta
 └─ conecta no broker (TLS) e assina loja/displays/{display_id}/preco
     └─ recebe na hora a última mensagem retida, se houver

loop
 └─ mantém wifi e MQTT vivos (reconexão automática com backoff)
 └─ chegou mensagem no tópico? -> mesmo parser do sync -> redesenha
```

O JSON do MQTT é **idêntico** ao da resposta HTTP (os dois vêm de
`montar_estado` no backend), por isso existe um único parser
(`aplicarEstado`) no firmware.

## A função de desenho

`desenharEtiqueta()` é a peça específica deste display — é ela que o
README principal apontava como pendente. Layout no 128x64:

```
+--------------------------------+
| Cola Pano Gliart               |  nome + marca, fonte 6x12
|--------------------------------|
| de R$ 19,95            +------+|  preço antigo riscado
|  ‾‾‾‾‾‾‾‾‾‾‾           | -25% ||  selo de desconto em negativo
| R$ 14,90               +------+|  preço novo, fonte logisoso20
+--------------------------------+
```

Fora de promoção, some o preço riscado e o selo, e o preço vigente fica
centralizado numa fonte maior (`logisoso24`).

O percentual vem **calculado do servidor** (campo `percentual_desconto`).
O firmware não faz conta de preço: é o que garante que o selo `-25%` bata
exatamente com o que o painel mostra.

## Diagnóstico

Serial Monitor a **115200 baud**.

| Sintoma | Causa provável |
|---|---|
| Tela apagada | endereço I2C errado (tente `0x3D`) ou SDA/SCL trocados |
| `HTTP 401` no boot | token errado, ou display desativado no painel |
| `MQTT falhou, rc=-2` | host/porta errados, ou TLS exigido e `MQTT_USE_TLS 0` |
| `MQTT falhou, rc=5` | usuário/senha do broker sem permissão no tópico |
| `MQTT falhou, rc=-4` | timeout — broker inacessível pela rede |
| Conecta mas nunca redesenha | prefixo do tópico diferente do backend, ou `MQTT_ENABLED=false` no `.env` |
| JSON inválido na mensagem | payload maior que o buffer — suba `MQTT_BUFFER_BYTES` |

Para conferir se o backend está publicando, sem depender do ESP32:

```bash
mosquitto_sub -h SEU-BROKER -p 8883 --capath /etc/ssl/certs \
  -u USUARIO -P SENHA -t 'loja/displays/#' -v
```
