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
  `/funcionario/displays`): cadastrar um display, vincular a um produto,
  ver bateria/última sincronização, gerar novo token, desativar.
- **Firmware de referência** (`firmware/esp32_display_preco/`): sketch
  Arduino para ESP32 que já resolve toda a parte de rede (conectar wifi,
  autenticar, buscar preço, decidir se redesenha, dormir até o próximo
  ciclo). Só falta a função que desenha na tela específica que for
  escolhida -- ver `firmware/README.md`.
- **63+9 testes automatizados** cobrindo o backend, incluindo
  `backend/tests/test_displays.py` (criação, vínculo com produto,
  sincronização, token inválido, regeneração de token, desativação).

Ou seja: dá para testar o fluxo inteiro **sem nenhum hardware ainda**,
simulando o dispositivo com curl/Postman (ver seção 5).

## 3. Arquitetura / fluxo

```
Funcionário aprova promoção (painel web)
        │
        ▼
price_service muda produto.preco_promocional / promocao_ativa (backend)
        │
        │  (o display NÃO é avisado na hora -- ver seção 5, "por que polling")
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

Não existe um "hub" ou gateway central: cada display fala direto com a
API na nuvem pela própria rede wifi da loja. Mais simples de montar e
depurar do que uma topologia com coordenador central -- ver seção 5 para
o porquê disso importar na escolha wifi vs. BLE.

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
  "produto_atualizado_em": "2026-08-21T18:32:04",
  "proximo_sync_em_segundos": 300
}
```

Se o display ainda não tem produto vinculado, `tem_produto` vem `false`
e os demais campos de produto vêm nulos. `401` se o token for inválido
ou o display estiver desativado.

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

- **Polling autenticado por token, não MQTT/push.** Um display a bateria
  (e-paper) passa a maior parte do tempo em deep sleep -- não dá para
  manter uma conexão MQTT aberta (isso exigiria ficar acordado o tempo
  todo, matando a bateria em horas). O padrão do setor para etiquetas
  eletrônicas de prateleira ("ESL") é exatamente esse: o dispositivo
  acorda, pergunta "mudou alguma coisa?", volta a dormir. O intervalo
  (`proximo_sync_em_segundos`) é decidido pelo **servidor**, não fixo no
  firmware -- dá para apertar para 30s numa demo e alongar para 15-30min
  em produção (economizar bateria) só mudando uma env var
  (`DISPLAY_SYNC_INTERVALO_SEGUNDOS`), sem reflashear nada.
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
| **OLED monocromático pequeno** (SSD1306, biblioteca U8g2) | Barato, simples | Tela pequena (tipicamente 0.96"-1.3"), pouco legível de longe | Só para testes de bancada, não substitui uma etiqueta de prateleira de verdade |

**Sugestão de caminho**: comprar 1 kit ESP32 + e-paper pequeno primeiro,
validar o fluxo ponta a ponta (o firmware já dá pra testar sem tela
nenhuma, só olhando o Serial Monitor -- ver `firmware/README.md`), e só
depois decidir quantidade final e, possivelmente, caixas/moldura física
para proteger o display na prateleira.

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
- A comunicação é HTTPS (o backend no Render já serve TLS). O firmware
  de referência usa `client.setInsecure()` no `WiFiClientSecure` --
  pula a validação da cadeia de certificado. Trade-off documentado no
  próprio código (`firmware/esp32_display_preco/esp32_display_preco.ino`,
  função `sincronizar`): validar certificado de verdade num
  microcontrolador exige manter o CA root manualmente atualizado no
  firmware, trabalho extra para um endpoint que só expõe preço público
  de produto (não lida com senha/pagamento). Se quiser fechar isso,
  trocar por `client.setCACert(...)`.
- O token do dispositivo nunca é reexibido pela API depois de criado
  (nem pelo painel web) -- só existe na resposta do `POST` de
  criação/regeneração, igual a uma API key de serviço.

## 8. Roadmap sugerido

1. Validar o backend isolado (curl, seção 4) -- já dá pra fazer agora,
   sem esperar hardware chegar.
2. Comprar **1** ESP32 de teste, gravar o firmware sem display nenhum
   conectado, confirmar nos logs que ele autentica e recebe o preço
   certo.
3. Escolher e comprar **1** display (recomendação: e-paper pequeno),
   implementar `desenharEtiqueta()` para esse modelo específico.
4. Validar o ciclo completo: aprovar uma promoção no painel → o display
   de teste atualiza sozinho no próximo ciclo (dá pra apertar
   `DISPLAY_SYNC_INTERVALO_SEGUNDOS` pra uns 30s durante esse teste, e
   voltar pro padrão depois).
5. Só então decidir quantidade final de displays para a loja e montar o
   resto.

## 9. O que se espera de ajuda a partir daqui

Se você (Claude, numa sessão nova) está lendo isto para ajudar na parte
física: o código e a API já estão prontos e testados (backend + painel
web + firmware de referência, ver seções 2 e 4). O que normalmente falta
resolver daqui pra frente:

- Recomendação de modelo específico de e-paper (tamanho, onde comprar no
  Brasil, biblioteca certa) dado o orçamento/quantidade que o usuário
  tiver em mente.
- Preencher `desenharEtiqueta()` em
  `firmware/esp32_display_preco/esp32_display_preco.ino` para o modelo
  escolhido (layout da etiqueta: nome do produto, preço, indicação visual
  de promoção).
- Dúvidas de fiação/montagem (ligar o e-paper ao ESP32 via SPI, divisor
  de tensão para leitura de bateria, case/proteção física).
- Troubleshooting de wifi/HTTPS específico do hardware comprado.
