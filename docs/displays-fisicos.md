# Displays físicos de prateleira

> **Para quem está lendo isso pela primeira vez (ex.: outra sessão do
> Claude ajudando com a parte física):** este documento é o handoff
> completo da "Fase 7" do projeto -- etiquetas eletrônicas de prateleira
> que mostram o preço vigente do produto e atualizam sozinhas quando uma
> promoção é aprovada (ou expira) no sistema. **O lado software (backend
> + painel web) já está pronto e testado.** O que falta é 100% do lado
> físico: escolher/comprar o hardware, montar um primeiro protótipo e
> preencher a função de desenho na tela no firmware. Veja a seção 9 ("O
> que se espera de ajuda a partir daqui") para o resumo do que se espera
> de ajuda aqui.

## 1. Contexto do projeto

TCC de digitalização de precificação para uma loja de varejo físico
(armarinho/papelaria/artesanato). O sistema já tem: catálogo/estoque,
login de funcionário, scanner de código de barras para o cliente
(carrinho sem pagamento) e um motor de promoções por IA que sugere
descontos e, quando o funcionário aprova, muda o preço vigente do
produto no banco. Esta última parte -- **refletir esse preço em displays
físicos na prateleira**, sem o funcionário precisar trocar etiqueta de
papel na mão -- é a peça que falta. Stack: backend Python/FastAPI +
PostgreSQL (Neon), frontend React/TypeScript, deploy em Render
(backend) + Vercel (frontend). Ver `README.md` na raiz do repo para o
panorama completo do sistema.

## 2. O que já está pronto (não precisa mexer, só usar)

- **Modelo de dados** `Display` (`backend/app/models/display.py`):
  vincula um dispositivo físico a um produto do catálogo, guarda um
  token de autenticação próprio (não é o login do funcionário) e
  telemetria (bateria, RSSI, MAC, última sincronização).
- **API REST** (`backend/app/routers/displays.py`,
  `backend/app/services/display_service.py`): rotas de gestão (criar,
  listar, editar, desativar, regenerar token -- exigem login de
  funcionário) e uma rota que o **próprio dispositivo** chama para se
  sincronizar (`POST /displays/sincronizar`, autenticada pelo token do
  display, sem precisar de login). Contrato completo na seção 4.
- **Painel web** (`frontend/src/funcionario/pages/Displays.tsx`, rota
  `/displays`): cadastrar um display, vincular a um produto,
  ver bateria/última sincronização, gerar novo token, desativar.
- **Push MQTT opcional** (`backend/app/services/mqtt_publisher.py`):
  quando uma promoção é aprovada (ou expira), o backend publica o preço
  novo no tópico do display. Desligado por padrão (`MQTT_ENABLED=false`)
  -- ver seção 3.2.
- **Dois firmwares de referência** (ver seção 3 para a comparação):
  - `firmware/esp32_display_preco_epaper_pull/` -- **produção**: e-paper
    + polling + deep sleep + bateria. Toda a parte de rede pronta; falta
    só a função de desenho do modelo de e-paper que for comprado.
  - `firmware/esp32_display_preco_oled_mqtt/` -- **demonstração**: OLED
    SSD1306 + push MQTT + alimentação fixa. **Completo**, incluindo a
    função de desenho.
- **Testes automatizados** cobrindo o backend, incluindo
  `backend/tests/test_displays.py` (criação, vínculo com produto,
  sincronização, token inválido, regeneração de token, desativação) e
  `backend/tests/test_mqtt_displays.py` (push por display vinculado,
  no-op com MQTT desligado, falha de broker não derruba a aprovação).

Ou seja: dá para testar o fluxo inteiro **sem nenhum hardware ainda**,
simulando o dispositivo com curl/Postman (ver seção 4).

## 3. Arquitetura / fluxo

Existem **duas variantes**, e elas coexistem de propósito. O backend
atende as duas ao mesmo tempo, sem configuração condicional: publica no
MQTT **e** continua respondendo o polling HTTP.

| | 3.1 Produção | 3.2 Demonstração |
|---|---|---|
| Tela | e-paper (imagem persistente) | OLED SSD1306 128x64 |
| Comunicação | polling HTTP | HTTP no boot + push MQTT |
| Energia | deep sleep, bateria (meses) | sempre ligado, USB/fonte |
| Latência da atualização | até um ciclo (padrão 5 min) | < 1 segundo |
| Firmware | `esp32_display_preco_epaper_pull/` | `esp32_display_preco_oled_mqtt/` |

**Por que as duas.** A de produção é a resposta certa para o problema
real: uma etiqueta de prateleira precisa durar meses com bateria, e isso
exige dormir -- o que é incompatível com manter uma conexão MQTT aberta.
É também o que as etiquetas eletrônicas comerciais (ESL) fazem. Mas numa
apresentação ao vivo o que convence é ver a etiqueta mudar no mesmo
instante em que a promoção é aprovada, e ninguém vai medir autonomia de
bateria na banca. Em vez de degradar a arquitetura de produção para
ganhar efeito de demonstração, mantemos as duas e documentamos o
trade-off -- que é, ele próprio, um resultado do trabalho.

### 3.1 Produção -- e-paper + polling + deep sleep

```
Funcionário aprova promoção (painel web)
        │
        ▼
price_service muda produto.preco_promocional / promocao_ativa (backend)
        │
        │  (o display NÃO é avisado na hora -- ele está dormindo)
        ▼
Display acorda sozinho a cada N segundos (padrão 300s, configurável
sem reflashear -- ver DISPLAY_SYNC_INTERVALO_SEGUNDOS)
        │
        ▼
POST /displays/sincronizar  (wifi + HTTPS, header X-Display-Token)
        │
        ▼
Backend devolve o preço vigente atual do produto vinculado
        │
        ▼
Firmware compara com o último preço desenhado; se mudou, redesenha
a tela; se não, só volta a dormir (economiza ciclos de refresh/bateria)
```

### 3.2 Demonstração -- OLED + MQTT push

```
BOOT do display
        │
        ├─ POST /displays/sincronizar (HTTP, uma única vez)
        │       └─ já liga mostrando o preço atual
        │       └─ lê `display_id` da resposta
        │
        └─ conecta no broker MQTT (TLS) e assina
           loja/displays/{display_id}/preco
                └─ recebe na hora a última mensagem retida, se houver

... display fica ocioso, conexão MQTT viva ...

Funcionário aprova promoção (painel web)
        │
        ▼
price_service muda o preço + grava histórico  ──> COMMIT
        │
        ▼
mqtt_publisher publica em loja/displays/{id}/preco   (retain=true, QoS 1)
        │
        ▼
Display recebe a mensagem e redesenha  (< 1s)
```

**Por que HTTP no boot e MQTT depois.** São papéis diferentes: o HTTP é a
fonte autoritativa do estado inicial (funciona mesmo com o broker vazio,
recém-criado ou reiniciado, e é o mesmo endpoint já testado da variante
de produção); o MQTT é o canal de mudança em tempo real. Publicamos com
`retain=true` como rede de segurança -- um display que reinicie entre
duas aprovações recebe o último preço assim que assina --, mas isso
complementa, não substitui, a chamada HTTP.

**Por que publicar depois do commit.** O push só anuncia o que já está
persistido. Se publicássemos dentro da transação, um rollback deixaria a
etiqueta física mostrando um preço que não existe no banco -- e ninguém
olha o banco para conferir o que a prateleira está anunciando.

**O push é best-effort.** A mudança de preço no banco é a fonte da
verdade. Broker fora do ar, credencial errada ou rede caída são
capturados e logados, e **nunca** derrubam a aprovação da promoção (há
teste cobrindo isso). No pior caso, a etiqueta atualiza no próximo
polling -- a variante de produção continua funcionando sem MQTT nenhum.

Não existe um "hub" ou gateway central: cada display fala direto com a
API na nuvem (e com o broker) pela própria rede wifi da loja. Mais
simples de montar e depurar do que uma topologia com coordenador central
-- ver seção 5 para o porquê disso importar na escolha wifi vs. BLE.

## 4. Contrato de API

Base URL: a mesma do resto do backend (`VITE_API_URL` em dev,
`https://SEU-SERVICO.onrender.com` em produção).

### Rotas de gestão (funcionário logado -- `Authorization: Bearer <jwt>`)

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/displays` | Cria um display. Corpo: `{"nome": "...", "produto_id": 12 \| null}`. **A resposta traz o `token` -- só aparece aqui**, copiar para o firmware. |
| `GET` | `/displays` | Lista todos (sem o token). |
| `GET` | `/displays/{id}` | Detalhe de um (sem o token). |
| `PUT` | `/displays/{id}` | Atualiza nome/`produto_id`/`ativo`. Usado para (re)vincular a outro produto. |
| `DELETE` | `/displays/{id}` | Soft delete (`ativo=false`) -- o token para de ser aceito. |
| `POST` | `/displays/{id}/token` | Gera um token novo, invalida o anterior. Resposta: `{"token": "..."}`. |

### Rota do dispositivo (sem login -- header `X-Display-Token`)

`POST /displays/sincronizar`

Corpo (tudo opcional -- funciona até com `{}`):
```json
{ "mac": "AA:BB:CC:DD:EE:FF", "bateria_pct": 87, "rssi_dbm": -62 }
```

Resposta (200):
```json
{
  "display_id": 3,
  "display_nome": "Prateleira 1",
  "tem_produto": true,
  "produto_id": 12,
  "produto_nome": "Cola Pano 90g",
  "marca": "Fabricante X",
  "tamanho": "90g",
  "preco_normal": "19.95",
  "preco_promocional": "14.90",
  "promocao_ativa": true,
  "preco_vigente": "14.90",
  "percentual_desconto": "25.31",
  "produto_atualizado_em": "2026-08-21T18:32:04",
  "gerado_em": "2026-09-01T14:07:11",
  "proximo_sync_em_segundos": 300
}
```

Se o display ainda não tem produto vinculado, `tem_produto` vem `false`
e os demais campos de produto vêm nulos. `401` se o token for inválido
ou o display estiver desativado.

Notas sobre dois campos:

- **`percentual_desconto`** é calculado no servidor, não no firmware.
  Microcontrolador não tem aritmética decimal confiável, e o selo `-25%`
  da etiqueta precisa bater exatamente com o que o painel mostra. Vem
  `null` fora de promoção.
- **Preços são strings, não números.** Passar `19.95` como float JSON
  arriscaria erro de ponto flutuante no caminho; o firmware trata preço
  como texto de qualquer forma (só desenha).

### Contrato do tópico MQTT (variante de demonstração)

**Tópico**: `{MQTT_TOPIC_PREFIX}/{display_id}/preco`
(padrão: `loja/displays/3/preco`)

O `display_id` é o `id` do registro do display -- o mesmo que vem na
resposta do sync HTTP. O firmware monta o tópico sozinho depois do boot;
não precisa ser configurado por dispositivo. O que autentica o
dispositivo continua sendo o **token** (no HTTP) e a credencial do
broker (no MQTT); o id no tópico é só endereço.

| | |
|---|---|
| **Payload** | Idêntico ao da resposta de `POST /displays/sincronizar` (os dois vêm de `display_service.montar_estado`) -- por isso o firmware tem **um único parser** |
| **QoS** | 1 (at least once) -- a mensagem de "entrou em promoção" não pode se perder; duplicata é inofensiva, o firmware só redesenha o mesmo conteúdo |
| **Retain** | `true` -- display que ligar depois recebe o último preço assim que assina |
| **Quando publica** | aprovação de promoção e expiração de promoção, sempre **depois** do commit |
| **Para quem** | todos os displays **ativos** vinculados ao produto (display desativado não recebe) |

Variáveis no `.env` do backend (todas opcionais, ver `.env.example`):
`MQTT_ENABLED` (default `false`), `MQTT_HOST`, `MQTT_PORT` (8883 TLS /
1883 sem TLS), `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_USE_TLS`,
`MQTT_TOPIC_PREFIX` (default `loja/displays`).

### Testando o push sem ESP32

Com `MQTT_ENABLED=true` no `.env` e o backend rodando, assine o tópico
num terminal e aprove uma promoção no painel:

```bash
# broker gerenciado (HiveMQ Cloud, TLS)
mosquitto_sub -h SEU-BROKER -p 8883 --capath /etc/ssl/certs \
  -u USUARIO -P SENHA -t 'loja/displays/#' -v

# broker local (mosquitto sem TLS)
mosquitto_sub -h localhost -p 1883 -t 'loja/displays/#' -v
```

A mensagem aparece no terminal no instante da aprovação. Isso valida o
lado do backend inteiro antes de existir qualquer hardware.

### Testando sem hardware

```bash
# 1. Login de funcionário (pegue o token JWT da resposta)
curl -X POST https://SEU-SERVICO.onrender.com/auth/login \
  -d "username=admin@loja.com&password=admin123"

# 2. Criar um display (guarde o "token" da resposta -- é o do dispositivo)
curl -X POST https://SEU-SERVICO.onrender.com/displays \
  -H "Authorization: Bearer <jwt>" -H "Content-Type: application/json" \
  -d '{"nome": "Teste bancada", "produto_id": 1}'

# 3. Simular o dispositivo sincronizando
curl -X POST https://SEU-SERVICO.onrender.com/displays/sincronizar \
  -H "X-Display-Token: <token-do-passo-2>" -H "Content-Type: application/json" \
  -d '{"bateria_pct": 90, "rssi_dbm": -55}'
```

## 5. Decisões de design já tomadas (e por quê)

- **Polling autenticado por token na variante de produção; MQTT só na de
  demonstração.** Um display a bateria (e-paper) passa a maior parte do
  tempo em deep sleep -- não dá para manter uma conexão MQTT aberta (isso
  exigiria ficar acordado o tempo todo, matando a bateria em horas). O
  padrão do setor para etiquetas eletrônicas de prateleira ("ESL") é
  exatamente esse: o dispositivo acorda, pergunta "mudou alguma coisa?",
  volta a dormir. O intervalo (`proximo_sync_em_segundos`) é decidido pelo
  **servidor**, não fixo no firmware -- dá para apertar para 30s numa demo
  e alongar para 15-30min em produção (economizar bateria) só mudando uma
  env var (`DISPLAY_SYNC_INTERVALO_SEGUNDOS`), sem reflashear nada.

  O push MQTT foi acrescentado **depois**, e não substitui isso: ele
  existe para a variante de bancada, que fica na tomada e por isso pode
  manter a conexão aberta. A incompatibilidade entre "dormir para durar
  meses" e "estar acordado para receber push" é real e não tem meio-termo
  -- por isso são duas variantes, e não uma opção de configuração. O
  backend suporta as duas simultaneamente porque o push é best-effort por
  cima do polling, não no lugar dele.
- **Token opaco por dispositivo, não JWT/login de funcionário.** O
  dispositivo não é uma "pessoa" -- não faz sentido pedir usuário/senha
  nem lidar com expiração de sessão num microcontrolador. O funcionário
  cria o registro do display no painel, recebe um token gerado na hora
  (`secrets.token_hex`, 48 chars) e grava esse token no firmware. Se o
  token vazar ou o dispositivo for trocado, dá para regenerar sem perder
  o vínculo/histórico do display (`POST /displays/{id}/token`).
- **Wifi, não Bluetooth, para a comunicação com o backend.** BLE não tem
  IP roteável até a internet -- um display via BLE precisaria de um "hub"
  central (outro ESP32 ou Raspberry Pi) fazendo a ponte entre BLE e wifi,
  complexidade a mais sem ganho claro para uma loja pequena com wifi
  cobrindo o salão inteiro. Fica registrado como caminho alternativo se,
  no futuro, o número de displays for grande o bastante para sobrecarregar
  o wifi da loja (aí um hub central com BLE mesh nos displays e uma única
  conexão wifi no hub faz mais sentido).
- **1 display = 1 produto**, vínculo simples via `produto_id` na tabela
  `display`. Igual ao padrão de etiqueta eletrônica comercial (uma
  etiqueta fica fisicamente colada numa posição da prateleira e mostra o
  preço do que está ali).
- **`atualizado_em` do produto como sinal de mudança.** O firmware guarda
  o último preço desenhado (em RTC memory, sobrevive ao deep sleep) e só
  redesenha se for diferente -- evita gastar ciclo de refresh de e-paper
  (lento, ~1-2s, e tem vida útil limitada de refreshs completos) quando
  nada mudou.

## 6. Hardware -- o que falta decidir

Nada comprado ainda. Pontos para decidir com ajuda (dimensione pela
quantidade de displays que a loja realmente precisa, não a maior loja
possível -- é um TCC, começar com 1-2 unidades de protótipo antes de
comprar em quantidade):

### Microcontrolador
**ESP32** é a recomendação (não ESP8266): tem wifi + BLE (mesmo não
usando BLE agora, deixa a porta aberta), mais memória/GPIO, e é o padrão
de fato para projetos hobby desse tipo. Custo aproximado: R$20-35 por
placa dev board (ex.: "ESP32-WROOM-32 DevKit") em lojas de eletrônica
online/nacionais.

### Tela
| Opção | Prós | Contras | Quando faz sentido |
|---|---|---|---|
| **E-paper** (ex.: Waveshare 2.13"/2.9", biblioteca GxEPD2) | Legível com qualquer luz (inclusive sol), **mantém a imagem sem energia nenhuma** (ideal p/ display a bateria), baixíssimo consumo entre refreshs | Refresh lento (~1-2s, "pisca" a tela toda), preto/branco (ou 3 cores em modelos mais caros), vida útil de ciclos de refresh completo limitada (dezenas de milhares -- não é problema pra uma loja pequena trocando preço algumas vezes por semana) | **Recomendado** para o produto final -- é literalmente o que etiquetas eletrônicas comerciais usam |
| **TFT colorido** (ex.: ILI9341, biblioteca TFT_eSPI) | Redesenho instantâneo, cores | Precisa ficar sempre ligado (maior consumo -- viável só com fonte USB constante, não bate bateria por muito tempo) | Bom para **protótipo/demo de bancada** (não precisa esperar o refresh na hora de mostrar funcionando pra banca) |
| **OLED monocromático pequeno** (SSD1306, biblioteca U8g2) | Barato (~R$15-25), simples, redesenho instantâneo, I2C (só 4 fios) | Tela pequena (tipicamente 0.96"-1.3"), pouco legível de longe, precisa de energia constante | **É o escolhido para o protótipo de demonstração** (variante MQTT) -- não substitui uma etiqueta de prateleira de verdade, mas mostra o fluxo completo funcionando ao vivo |

**Sugestão de caminho**: o protótipo de demonstração usa **ESP32 + OLED
SSD1306 128x64** (~R$40-60 no total), que é o que o firmware
`esp32_display_preco_oled_mqtt/` já implementa por completo -- dá para
montar e mostrar funcionando sem decidir mais nada. Para o produto final,
comprar 1 kit ESP32 + e-paper pequeno, implementar a função de desenho
para esse modelo e só depois decidir quantidade final e caixas/moldura
física para proteger o display na prateleira.

### Energia
E-paper + deep sleep permite rodar meses com uma bateria LiPo pequena
(o consumo em deep sleep de um ESP32 é da ordem de dezenas de µA; o
gasto real é durante os poucos segundos acordado por ciclo de
sincronização). Se preferir simplicidade em vez de autonomia, dá para
alimentar via USB/fonte 5V direto na prateleira (sem bateria) -- troca
autonomia por não ter que trocar/recarregar bateria nunca. O firmware já
tem um hook para reportar `bateria_pct` (`BATTERY_ADC_PIN` em
`config.h`) via divisor resistivo simples, mas é opcional.

## 7. Segurança (o que já está coberto e o que fica como trade-off consciente)

- Cada dispositivo tem um token próprio (não compartilhado), revogável
  sem afetar os outros displays.
- A comunicação é HTTPS (o backend no Render já serve TLS). Os dois
  firmwares usam `client.setInsecure()` no `WiFiClientSecure` -- pula a
  validação da cadeia de certificado. Trade-off documentado no próprio
  código (função `sincronizar` em cada variante): validar certificado de
  verdade num microcontrolador exige manter o CA root manualmente
  atualizado no firmware, trabalho extra para um endpoint que só expõe
  preço público de produto (não lida com senha/pagamento). Se quiser
  fechar isso, trocar por `client.setCACert(...)`.
- **MQTT**: a conexão com o broker também é TLS (porta 8883 nos brokers
  gerenciados), com o mesmo `setInsecure()` e o mesmo raciocínio. A
  credencial do broker fica no `config.h` de cada dispositivo (não
  commitado). O conteúdo publicado é preço de produto -- informação que
  já está impressa na prateleira e visível para qualquer cliente na loja.
  O que **não** trafega por MQTT: token do display, dados de funcionário
  ou qualquer coisa de pedido/cliente.
- **O tópico contém o `display_id`, mas ele não é segredo.** Quem
  consegue publicar no tópico é quem tem credencial do broker; um id
  sequencial no caminho do tópico não enfraquece nada. Um atacante com
  credencial de broker conseguiria, no pior caso, fazer uma etiqueta
  mostrar um preço errado -- não alterar o preço no sistema, que é a
  fonte da verdade e continua exigindo login de funcionário.
- O token do dispositivo nunca é reexibido pela API depois de criado
  (nem pelo painel web) -- só existe na resposta do `POST` de
  criação/regeneração, igual a uma API key de serviço.

## 8. Roadmap sugerido

### Caminho curto -- protótipo de demonstração (para a banca)

1. Validar o backend isolado (curl, seção 4) -- já dá pra fazer agora.
2. Criar uma conta gratuita no [HiveMQ Cloud](https://console.hivemq.cloud)
   (ou subir um `mosquitto` local), preencher as variáveis `MQTT_*` no
   `.env` e confirmar o push com `mosquitto_sub` (seção 4, "Testando o
   push sem ESP32") -- ainda sem hardware.
3. Comprar **ESP32 + OLED SSD1306 128x64** (~R$40-60 no total).
4. Gravar `firmware/esp32_display_preco_oled_mqtt/`, preencher o
   `config.h`, ligar 4 fios (I2C).
5. Aprovar uma promoção no painel → a etiqueta muda na hora. É esse o
   momento da apresentação.

### Caminho longo -- produto final (e-paper)

6. Escolher e comprar **1** e-paper pequeno, implementar
   `desenharEtiqueta()` em `esp32_display_preco_epaper_pull/` para esse
   modelo específico.
7. Validar o ciclo completo com polling: aprovar uma promoção no painel →
   o display atualiza sozinho no próximo ciclo (dá pra apertar
   `DISPLAY_SYNC_INTERVALO_SEGUNDOS` pra uns 30s durante o teste, e
   voltar pro padrão depois).
8. Medir a autonomia real com bateria antes de decidir quantidade final
   de displays para a loja.

## 9. O que se espera de ajuda a partir daqui

Se você (Claude, numa sessão nova) está lendo isto para ajudar na parte
física: o código e a API já estão prontos e testados (backend + painel
web + firmware de referência, ver seções 2 e 4). O que normalmente falta
resolver daqui pra frente:

- Recomendação de modelo específico de e-paper (tamanho, onde comprar no
  Brasil, biblioteca certa) dado o orçamento/quantidade que o usuário
  tiver em mente.
- Preencher `desenharEtiqueta()` em
  `firmware/esp32_display_preco_epaper_pull/esp32_display_preco_epaper_pull.ino`
  para o modelo escolhido (layout da etiqueta: nome do produto, preço,
  indicação visual de promoção). A variante OLED
  (`esp32_display_preco_oled_mqtt/`) já tem essa função pronta e serve de
  referência de layout.
- Dúvidas de fiação/montagem (ligar o e-paper ao ESP32 via SPI, divisor
  de tensão para leitura de bateria, case/proteção física).
- Troubleshooting de wifi/HTTPS específico do hardware comprado.
