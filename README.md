# Sistema de Precificação Inteligente para Varejo Físico

TCC: digitalização e automação da precificação de uma loja de varejo físico
(armarinho/papelaria/artesanato). Duas áreas — cliente (scanner de QR/código
de barras → carrinho → checkout, com conferência no caixa físico) e
funcionário (caixa, login, gestão de estoque com alerta de estoque baixo,
sugestões de promoção geradas por IA aguardando aprovação, indicadores de
eficácia) — mais displays físicos de prateleira que atualizam o preço
exibido sozinhos via wifi quando uma promoção é aprovada (backend/API/painel
já prontos; hardware em andamento — ver
[`docs/displays-fisicos.md`](docs/displays-fisicos.md)).

O checkout **não** processa pagamento, e isso é uma decisão de projeto: a
loja é física e tem caixa, então o sistema gera um número curto de
conferência e é companion do caixa, não um self-checkout. Integrar um
gateway exigiria quebrar o checkout em reserva → confirmação, infra de
webhook e expiração com devolução de estoque — trabalho de integração sem
contribuição para a pergunta do trabalho, que é sobre *precificação*.

Arquitetura completa, modelagem de dados e roadmap faseado estão descritos
no plano de implementação do projeto.

## Stack

- **Backend**: Python 3.13 + FastAPI + SQLAlchemy + Alembic, banco
  PostgreSQL (Neon, serverless free tier), com fallback automático para
  SQLite local em desenvolvimento/testes quando `DATABASE_URL` não está
  configurado.
- **Frontend**: React + TypeScript + Vite, PWA (`vite-plugin-pwa`), scanner
  via `html5-qrcode`.
- **IA de promoções**: regras determinísticas (estoque parado, giro baixo,
  margem) + LLM gratuito (Groq/Gemini) como camada de raciocínio — ver
  justificativa detalhada no plano. Toda sugestão passa por **guard-rails
  de preço** (`services/price_service.py`): nenhuma promoção pode deixar o
  preço abaixo de `custo × (1 + margem mínima)`, nem passar do teto de
  desconto — nem sugerida pela IA, nem aprovada por funcionário.

## Rodando localmente

### Backend

```bash
cd backend
python -m venv venv
./venv/Scripts/activate      # Windows (PowerShell: ./venv/Scripts/Activate.ps1)
pip install -r requirements.txt
cp .env.example .env         # preencha DATABASE_URL com a connection string do Neon; sem isso usa SQLite local
alembic upgrade head
uvicorn app.main:app --reload
```

API sobe em `http://127.0.0.1:8000` (`/docs` para o Swagger, `/health`
para conferir se está de pé e qual banco está em uso).

#### Popular o banco (seed)

O seed **deriva** o catálogo e as vendas do dataset público
[Online Retail II (UCI)](https://archive.ics.uci.edu/dataset/502/online+retail+ii)
— o histórico de um atacadista de presentes do Reino Unido (dez/2009 a
dez/2011). Baixe o CSV você mesmo; o script **não baixa nada** e, se o
arquivo não existir, para sem tocar no banco.

```bash
python -m app.seed                          # lê o CSV de CAMINHO_CSV (topo de app/seed.py)
python -m app.seed --csv "D:/dados/online_retail_II.csv" --seed 7
python -m app.seed --conferir               # só lê o banco e resume o que o seed deixou lá
```

> ⚠️ **O seed SUBSTITUI o conteúdo do banco** (produtos, estoque, pedidos,
> histórico de preços, sugestões, displays, categorias e funcionários). O
> aviso é impresso antes de apagar, junto com o banco de destino. Toda a
> leitura e derivação roda em memória *antes*: CSV ausente ou erro na
> derivação não apagam nada.

Parâmetros editáveis no topo de `app/seed.py`: `CAMINHO_CSV`, `N_PRODUTOS=100`,
`JANELA_DIAS=180`, `FAIXA_MARGEM=(0.40, 0.50)`, `SEED=42`,
`FATOR_NORMALIZACAO=10.0` e o dicionário `CATEGORIAS_PALAVRAS_CHAVE`.

**Porte da loja (`FATOR_PORTE=30`).** O dataset é de um atacado; o seed reduz a
demanda (cada unidade vendida sobrevive com probabilidade `1/FATOR_PORTE`, de
forma determinística) para a escala de uma loja pequena: ~40 pedidos e ~R$ 2 mil
por dia. Maior = loja menor. O fator vale só no seed; a simulação diária lê o
ritmo do histórico do banco e herda a escala. Ao mudá-lo, rode o seed de novo.

**Metodologia** (mesma semente + mesmo CSV = mesmo resultado, o que permite
citar os parâmetros na monografia):

1. **Limpeza.** Remove cancelamentos (fatura `C…`), `Quantity ≤ 0` e
   `UnitPrice ≤ 0`, descrição vazia, `StockCode` que não é produto (padrão
   aceito: 5 dígitos + até 2 letras — descarta `POST`, `DOT`, `M`,
   `BANK CHARGES`, `AMAZONFEE`, `CRUK`, `gift_*`, `DCGS*`…) e linhas com mais
   de `QTD_MAX_POR_LINHA=500` unidades. O último filtro importa: há pedidos
   digitados errado e cancelados depois (80.995 e 74.215 unidades numa linha
   só); o cancelamento sai, mas a venda original ficaria e elevaria dois
   produtos ao top 10.
2. **Catálogo.** Top 100 `StockCode` por volume total vendido no dataset
   inteiro. Produto do top que não vendeu nada na janela (descontinuado) fica
   de fora, então o catálogo pode ter 99 itens.
3. **Janela.** Últimos 180 dias de atividade do dataset, **deslocados para
   terminar hoje**, com o mesmo deslocamento em todas as vendas (o
   espaçamento relativo é preservado). Consequências: o dia da semana muda
   (o atacadista não vendia aos sábados, e esse vazio cai noutro dia) e a
   sazonalidade do dataset (pico de Natal, em out–nov de 2011) aparece
   deslocada em relação ao calendário sazonal do motor.
4. **Pedidos.** Um `pedido` por (produto, dia), com um `pedido_item` (quantidade
   somada e preço médio ponderado do dia) e uma saída de `movimentacao_estoque`
   — o mesmo grão de `services/daily_sales_service.py`. O recorte tem ~42 mil
   linhas de fatura; nesse grão ficam ~12 mil pedidos, que cabem no free tier
   do Neon sem perder quantidade nem receita. Todos entram como
   `conferido_no_caixa` (são vendas concluídas; é o status que a camada de
   indicadores conta). Linhas com preço fora de `[0,75×; 2,5×]` da mediana do
   produto são descartadas (outra tabela de preços; o piso fica acima do custo
   estimado mais alto, então nenhuma venda sai abaixo do custo).
5. **Preço em R$.** `preço em GBP × FATOR_NORMALIZACAO` (≈ 7 de câmbio × ≈ 1,4
   de markup atacado→varejo; é uma escala, não conversão cambial). Itens de
   atacado muito baratos recebem fator maior, só para eles, até o preço de
   tabela chegar a `PRECO_MINIMO_REAL=R$ 2,50` — o preço relativo entre as
   vendas do mesmo item é preservado. Preço de tabela = mediana na janela.
6. **Custo (estimativa).** `custo = preço / (1 + margem)`, `margem` sorteada em
   `[0,40; 0,50]` por produto. É *markup sobre o custo*; o sistema mede
   margem *sobre o preço* (`(preço − custo) / preço`), que aqui fica entre
   28,6% e 33,3% — **abaixo da meta de 35%** de `MARGEM_ALVO_PERCENTUAL`, então
   a tela de Precificação lista todo o catálogo como margem defasada.
7. **Estoque (estimativa).** O estoque de hoje sai do giro real dos últimos 90
   dias (a mesma janela das regras do motor) e de um cenário por produto:
   *baixo* (~8% dos produtos, no mínimo 5, abaixo do ponto de reposição —
   dispara o alerta), *excesso* (~25%, cobertura acima do limiar de "estoque
   alto" — vira candidato a promoção) e *saudável* (o resto). O ponto de reposição
   (`quantidade_minima`) é 7 dias de giro, porque o limite global de 5 unidades
   não faz sentido com giro de dezenas de unidades por dia. O estoque inicial é
   `estoque de hoje + tudo que foi vendido na janela` (uma entrada, com custo
   e observação "DERIVADO"), então o saldo das movimentações fecha exatamente.
8. **Categoria (derivada).** Palavras-chave no nome **original em inglês**, na
   ordem de `CATEGORIAS_PALAVRAS_CHAVE` (a primeira que casa vence); sem match,
   `Diversos`. O código de barras do produto é o `StockCode` (tipo `CODE128`).
   **Nome em português.** O nome gravado em `produto.nome` (e no snapshot dos
   itens de pedido) é uma tradução manual por `StockCode`, em
   `app/seed_traducoes.py` (glossário no topo do arquivo). `StockCode` sem
   tradução cadastrada mantém o nome original em inglês, então outro CSV ou
   `--produtos` maior que 99 não quebram o seed.
9. **Histórico de preços.** Um registro inicial por produto (preço de tabela).
   A evolução real do preço fica nos `preco_unitario_snapshot` dos itens.

> ⚠️ **Estes dados não são a operação da loja.** O que é **real** (do
> dataset): quais produtos mais vendem, e a quantidade e o preço praticado
> por produto e dia (preço em GBP, escalado para R$). O que é **derivado**
> (estimativa deste script): custo, estoque, quantidade mínima, categoria,
> os nomes em português (tradução manual), as datas (janela deslocada) e a
> escala de preço. As quantidades
> são de **atacado** (mediana de 8 unidades por linha de fatura), muito acima
> do que uma loja de armarinho vende. Não há promoções nem sugestões
> históricas: nada disso existe no dataset, e o seed antigo as simulava com
> uma elasticidade inventada — o que contradiria vender como "real". Elas
> passam a nascer do motor (botão "Gerar sugestões agora") a partir dos
> sinais reais. A origem é rotulada em `origem_dados =
> "online_retail_ii_derivado"` (impresso ao fim do script, `ORIGEM_DADOS` no
> `.env` e `/analytics/resumo`), no prefixo `OR` do `numero_pedido` e na
> observação das entradas de estoque. A tela de Indicadores **não exibe mais
> o banner** de dado simulado (a classe CSS `.aviso-simulado` ficou sem uso
> desde o commit `eb74d50`); o campo `origem_dados` da API está disponível
> para reativá-lo.
>
> A simulação de vendas e compras roda sob demanda em `POST /simulacao/executar`
> (ver "Simulação do dia a dia da loja" mais abaixo); sem chamá-la, só há dado do
> dataset. A versão anterior do seed (catálogo da planilha da loja + 90 dias
> simulados) está no histórico do git.

#### Preço de mercado de referência

Antes de chamar o LLM, cada candidato a promoção recebe uma referência de
mercado (`app/ai/market_price.py`): mediana, mínimo, máximo e número de
amostras dos primeiros `PRECO_MERCADO_N_RESULTADOS` resultados, descartando
preços mais de 3× acima ou abaixo da mediana. O prompt recebe a faixa e a
posição do preço atual (preço atual / mediana). É só âncora: os guard-rails
não mudam, e o piso continua sendo custo + margem mínima.

- **Fontes:** Mercado Livre (`/sites/MLB/search`, exige OAuth:
  `ML_CLIENT_ID`/`ML_CLIENT_SECRET`; há relatos de 403 mesmo com token) e,
  como alternativa, Google Shopping via [Serper](https://serper.dev)
  (`SERPER_API_KEY`).
- **Lojas:** os nomes das lojas dos preços usados na faixa são guardados e
  exibidos nos detalhes da sugestão (sem links).
- **Registro no banco:** a tabela `preco_mercado` guarda a última consulta de
  cada produto. Ela vale 7 dias (`ok`) ou 2 dias (`nao_encontrado`) antes de
  uma nova busca. Sem nenhuma fonte utilizável, nada é gravado.
- **Sem referência:** a sugestão é gerada como antes e aparece na tela com o
  selo "Sem referência de mercado". `PRECO_MERCADO_HABILITADO=false` desliga
  a busca e o selo.
- **Limitação:** a busca é textual (marca + nome) e não confere se o anúncio
  é o mesmo produto, na mesma quantidade (unidade × kit). A faixa e o número
  de amostras ficam visíveis nos detalhes da sugestão para o funcionário
  julgar.

#### Avaliação do LLM (evidência experimental)

```bash
python -m scripts.avaliar_llm --dry-run              # valida o pipeline, sem rede nem quota
python -m scripts.avaliar_llm --produtos 10 --repeticoes 5
```

Roda os mesmos produtos N vezes em cada provedor e mede **consistência**
(desvio e coeficiente de variação do desconto sugerido), **taxa de
resposta inválida** por classe de erro, **latência** (média/p50/p95),
**Groq × Gemini** nas mesmas entradas e **LLM × baseline determinístico**
(erro médio em pontos percentuais e correlação de Spearman). Também mede
quantas respostas do LLM o guard-rail de custo barrou.

É script, não teste: assim `pytest` nunca gasta quota do free tier. Os
resultados saem em CSV + um JSON de metadados (commit, modelos, hash do
prompt, semente) em `backend/scripts/resultados/` — o hash do prompt
importa porque, se o prompt mudar, coletas antigas deixam de ser
comparáveis. `--limite-chamadas`, `--intervalo-ms` e o cache em disco
protegem a quota.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env         # ajuste VITE_API_URL se o backend não estiver em localhost:8000
npm run dev
```

App sobe em `http://localhost:5173`. Para testar o scanner de câmera num
celular, é preciso HTTPS (usar um túnel tipo `ngrok` em dev, ou o ambiente
de deploy).

### Rotas do frontend

O **console do funcionário é a aplicação principal** e mora na raiz: abrir o
site cai em `/` (tela de Produtos) ou em `/login`, quando não há sessão
aberta. As telas são `/caixa`, `/entradas`, `/precificacao`, `/promocoes`,
`/indicadores`, `/historico-precos` e `/displays`.

A **área do cliente** (scanner → carrinho → checkout) fica sob **`/cliente`**
e não é linkada de lugar nenhum do console — só chega quem digita o
endereço. Em desenvolvimento: <http://localhost:5173/cliente>; em produção,
o domínio do Vercel + `/cliente`.

Endereços antigos com o prefixo `/funcionario/...` continuam funcionando:
são redirecionados para o equivalente na raiz (`/funcionario/caixa` → `/caixa`).

## Deploy

Backend no **Render** (tier gratuito), frontend no **Vercel** (SPA
estática, tier gratuito). Os dois têm integração nativa com GitHub —
conectar o repo uma vez no dashboard já configura deploy automático a
cada push na `main`; não precisa de workflow de CD customizado nem de
token salvo como secret do GitHub.

O CI (`.github/workflows/ci.yml`) roda `pytest` (backend, contra SQLite —
não toca no Neon de produção) e o build do frontend em todo push/PR, sem
precisar de nenhum segredo configurado.

> **Tier gratuito do Render "dorme"** depois de ~15min sem requisições —
> a próxima chamada acorda o serviço com alguns segundos de atraso (cold
> start). Isso não afeta o botão "Gerar sugestões agora" (só demora um
> pouco mais na primeira chamada depois de um período parado), que é o
> único caminho de geração de sugestões. Torna pouco confiável apenas o
> job de limpeza (`ENABLE_SCHEDULER=true`, que expira promoções vencidas
> e pedidos abandonados) — por isso o `render.yaml` já deixa
> `ENABLE_SCHEDULER=false`; a expiração também roda sob demanda em
> `POST /promocoes/expirar-agora` e antes de cada geração. Se preferir um
> backend que não dorme, `backend/Procfile` e `railway.toml` (Railway,
> pago) continuam no repo como alternativa.

### Simulação do dia a dia da loja (endpoint)

`POST /simulacao/executar` simula **vendas e compras de mercadoria** de um dia,
para ser chamado por um agendador externo (Agendador de Tarefas do Windows,
GitHub Actions, cron…). Não usa login de funcionário: envie a chave de
`SIMULATION_API_KEY` no header `X-Simulation-Key`. Sem a variável, o endpoint
fica desligado (503); com `DADOS_SIMULADOS=false` ele é bloqueado (403), para
nunca inventar vendas num banco real.

```bash
curl -X POST "https://SEU-BACKEND/simulacao/executar" -H "X-Simulation-Key: SUA_CHAVE"
# parâmetros opcionais: ?dia=2026-11-20  ?dias=7 (retroativo, máx. 31)  ?semente=1 (repetível)
```

Agende no fim do expediente (ex.: 23h): os horários das vendas se espalham pelo
dia todo. Cada dia roda uma única vez (`simulacao_venda_execucao`), então repetir
a chamada não duplica nada. A resposta traz, por dia, pedidos, unidades, receita,
compras, rupturas e os produtos em alta e em baixa.

Nenhum dia sai igual ao anterior (`services/store_simulation_service.py`):

- **Vendas:** o ritmo de cada produto vem do histórico do banco e é multiplicado por
  dia da semana, dia de pagamento, uma onda lenta de ~5 semanas (períodos de alta e
  de baixa da loja), sorteio de dias fracos/fortes e ruído. Cada produto tem o
  próprio momento: em blocos de ~3 semanas ele **encalha** (~25% do normal, a
  oportunidade de promoção para a IA) ou **bomba** (~2×). Promoção ativa aumenta a
  demanda. As unidades viram cestas de 1 a 6 itens, com picos no almoço e no fim da tarde.
- **Compras:** o comprador só enxerga o histórico. Visita o fornecedor sobretudo às
  terças e quintas, repõe quando a cobertura cai abaixo de 6–14 dias, às vezes
  esquece ou o fornecedor falha (ruptura) e às vezes compra demais (capital parado).
  O custo varia a cada compra e o custo médio é recalculado como na entrada real.
  As entradas ficam marcadas com `[simulacao]` na observação.

Para criar dados históricos uma única vez, sem habilitar outro job, execute:

```bash
cd backend
python -m scripts.simular_historico_vendas --dias 15
```

Esse comando preenche os 15 dias anteriores ao dia atual, incluindo vendas e
promoções simuladas. Ele também é idempotente e pode ser repetido com
segurança.

**Backend (Render)**:
1. [dashboard.render.com](https://dashboard.render.com) → New → Blueprint → conectar este repositório. O Render lê o `render.yaml` da raiz e já configura build/start/healthcheck sozinho (aponta pra `backend/`, tier free).
2. Nas variáveis marcadas para preencher na hora: `DATABASE_URL` (a mesma connection string do Neon), `JWT_SECRET_KEY` (gerar uma nova — **não reaproveitar** a de dev: `python -c "import secrets; print(secrets.token_hex(32))"`), `CORS_ORIGINS` (a URL do Vercel — pode deixar `http://localhost:5173` por enquanto e voltar aqui depois), `GROQ_API_KEY`/`GEMINI_API_KEY`.
3. Depois do primeiro deploy, rodar as migrations contra o Postgres de produção (uma vez, localmente, apontando `DATABASE_URL` pro Neon): `alembic upgrade head`.
4. Anotar a URL pública gerada (ex.: `https://precificacao-inteligente-api.onrender.com`) — é o `VITE_API_URL` do frontend.

**Frontend (Vercel)**:
1. [vercel.com](https://vercel.com) → Add New Project → importar o mesmo repositório, root directory `frontend`.
2. Framework preset: Vite (auto-detectado). `frontend/vercel.json` já cuida do rewrite de rotas do React Router (sem isso, dar refresh em `/login` daria 404).
3. Environment Variable: `VITE_API_URL` = URL do backend no Render (passo anterior).
4. Deploy. Depois, voltar no Render e atualizar `CORS_ORIGINS` com a URL real do Vercel.

## Estrutura

```
backend/app/
  core/       # config, conexão com banco, segurança (JWT)
  models/     # SQLAlchemy ORM
  schemas/    # Pydantic
  routers/    # endpoints FastAPI
  services/   # regras de negócio (price_service = único lugar que muda preço)
  ai/         # regras + integração com LLM (motor de sugestão de promoções)
  jobs/       # rotina agendada de limpeza (expiração de promoções e pedidos)
  alembic/    # migrations
  seed.py     # catálogo + 90 dias de operação SIMULADA (rodar 1x)
backend/scripts/
  avaliar_llm.py   # harness de avaliação do LLM (consistência, Groq×Gemini, vs baseline)
  resultados/      # CSVs + metadados das coletas — evidência da monografia

frontend/src/
  cliente/       # área do cliente: scanner, carrinho, checkout (sob /cliente)
  funcionario/   # área do funcionário: caixa, produtos+estoque, promoções,
                 #   indicadores, histórico de preços, displays (na raiz)
  api/           # client HTTP
  context/       # estado global (carrinho, autenticação)

.github/workflows/ci.yml   # pytest + build do frontend em todo push/PR
backend/Procfile, railway.toml, .python-version   # deploy no Railway
frontend/vercel.json                              # deploy no Vercel (rewrite de rotas)

docs/displays-fisicos.md   # arquitetura/handoff dos displays físicos de prateleira
firmware/                  # firmware de referência (ESP32) -- ver firmware/README.md
  esp32_display_preco_epaper_pull/   # produção: e-paper + polling + deep sleep
  esp32_display_preco_oled_mqtt/     # demonstração: OLED + push MQTT
```

## Status

- **Fase 0 (fundação)**: concluída — skeleton de backend e frontend.
- **Fase 1 (catálogo/estoque)**: concluída — modelos `categoria`, `produto`,
  `produto_codigo`, `estoque`, `movimentacao_estoque`; migrations aplicadas
  no Postgres (Neon); CRUD completo de produtos e categorias, endpoint de
  lookup por código de barras/QR (reaproveita o preço se o código já
  estiver cadastrado, senão exige o preço no cadastro), listagem de
  estoque com alerta de estoque baixo e ajuste manual; seed único rodado
  (56 produtos, histórico de ~90 dias de vendas simuladas); testes
  automatizados cobrindo os fluxos principais.
- **Fase 2 (autenticação + dashboard)**: concluída — modelo `funcionario`
  (admin/operador); login via JWT (`POST /auth/login`); rotas de produtos
  e estoque agora exigem funcionário logado; `POST /auth/funcionarios`
  (só admin) cria novos funcionários; seed cria um admin padrão
  (`admin@loja.com` / `admin123` — **troque em produção**). No frontend:
  `AuthContext`, tela de login real, `ProtectedRoute` protegendo a área do
  funcionário, e a tela `Produtos` (rota índice do console) listando
  catálogo e estoque na mesma tabela, com destaque para estoque baixo e
  ajuste manual em linha.
- **Fase 3 (área do cliente)**: concluída — modelos `sessao_carrinho`,
  `carrinho_item`, `pedido`, `pedido_item` (migration aplicada no Neon);
  cliente identificado por UUID anônimo (`X-Cart-Session`, sem login);
  `POST /carrinho/sessoes`, `GET/POST/PUT/DELETE /carrinho...` (upsert de
  item, preço travado no momento do scan), `GET /catalogo/codigo/{codigo}`
  (público, sem estoque/custo) e `POST /checkout` (valida estoque de todo
  o carrinho antes de decrementar qualquer coisa — tudo ou nada —, gera
  número curto de conferência para o caixa físico e grava
  `movimentacao_estoque`). No frontend: `CartContext`, `ScannerCamera`
  (`html5-qrcode`, cobre Android e iOS), páginas Scanner/Carrinho/Checkout
  funcionais, PWA instalável com ícones (placeholder). Testado
  end-to-end contra o Postgres real (Neon).
- **Fase 4 (motor de promoções por IA)**: implementada — modelos
  `promocao_sugestao`, `historico_preco` (migration aplicada no Neon);
  `ai/rules.py` calcula sinais determinísticos por produto (dias sem
  venda, giro, dias de estoque restante, margem, sazonalidade simples) a
  partir do histórico real de `movimentacao_estoque`; `ai/llm_provider.py`
  chama Groq (`openai/gpt-oss-120b` — Llama 3.3 70B, escolha original do
  plano, foi descontinuado pela Groq) via REST direto, com fallback
  automático pro Gemini 2.5 Flash, valida a resposta (JSON estrito,
  desconto 0-70%) e nunca deixa uma falha de IA travar os demais
  produtos; usa `truststore` pra funcionar em máquinas Windows com
  antivírus/proxy que faz inspeção SSL. `services/promotion_service.py`
  orquestra tudo e `services/price_service.py` é o único lugar que de
  fato muda preço (transacional, sempre grava histórico);
  `POST /promocoes/gerar-agora` (único caminho de geração: roda no clique
  do funcionário, sem job por tempo gerando promoção sozinho),
  `GET /promocoes`, aprovar/rejeitar, `GET /historico-precos` — todos
  exigem funcionário logado. O `jobs/scheduler.py` (APScheduler) cuida só
  da limpeza periódica (expirar promoções vencidas e pedidos abandonados)
  e fica desligado por padrão (`ENABLE_SCHEDULER=false`); liga só em
  produção. Testado de
  ponta a ponta contra o Neon e a API real do Groq (63 testes
  automatizados com o LLM mockado + geração/aprovação/rejeição reais no
  navegador). Frontend: telas Promoções (gerar sob demanda com spinner de
  progresso, aprovar/rejeitar com observação) e Histórico de Preços
  funcionais.
- **Fase 5 (deploy + hardening)**: concluída — `.github/workflows/ci.yml`
  (pytest + build do frontend em todo push/PR, sem segredos); backend no
  Render e frontend no Vercel já conectados e publicados (ver seção
  "Deploy" acima); checagem de segurança no boot
  (`validar_configuracao_producao`) que recusa subir com
  `ENVIRONMENT=production` e `JWT_SECRET_KEY` ainda no valor padrão do
  repositório. Config alternativa pro Railway (`Procfile`, `railway.toml`,
  `.python-version`) segue no repo como opção B.
- **Fase 7 (displays físicos)**: backend/API/painel prontos e testados —
  modelo `display` (migration aplicada no Neon), `POST /displays/sincronizar`
  (dispositivo se autentica sozinho via token próprio, sem login de
  funcionário) e painel `/displays` (criar, vincular a produto,
  ver bateria/última sincronização, regenerar token).
  **Duas variantes de firmware, que coexistem de propósito**:
  - `firmware/esp32_display_preco_epaper_pull/` — **produção**: e-paper +
    polling HTTP + deep sleep + bateria. É a arquitetura das etiquetas
    comerciais (ESL), com meses de autonomia. Toda a parte de rede pronta;
    falta a função de desenho do modelo de e-paper que for comprado.
  - `firmware/esp32_display_preco_oled_mqtt/` — **demonstração**: OLED
    SSD1306 + push MQTT + alimentação fixa. Aprovou a promoção no painel, a
    etiqueta muda em menos de um segundo. **Completo**, incluindo a função
    de desenho. O backend publica em `loja/displays/{id}/preco`
    (`MQTT_ENABLED`, desligado por padrão — dev e CI rodam sem broker), e o
    push é best-effort: broker fora do ar nunca derruba a aprovação.

  Nenhuma substitui a outra: dormir para durar meses e ficar acordado para
  receber push são incompatíveis, e o trade-off está documentado como
  resultado do trabalho. **Hardware ainda não comprado** — comparação das
  variantes, contrato do tópico MQTT e roadmap de compra/montagem em
  [`docs/displays-fisicos.md`](docs/displays-fisicos.md).
- **Fase 6 (avaliação + fechamento do ciclo)**: implementada — cinco
  frentes, sem nenhuma dependência nova:
  - **Guard-rails de preço** (`price_service.validar_preco_promocional`):
    piso de `custo × (1 + margem mínima)`, teto de desconto, recusa de
    promoção sobre promoção e checagem de coerência entre o percentual e o
    preço que o LLM devolve no mesmo JSON. Sugestão que fere o piso é
    barrada antes de virar registro (aparece em `falhas` com categoria
    `guard_rail`, o que é uma métrica em si); na aprovação devolve 422 e a
    sugestão **continua pendente**. `promotion_service.aprovar` passou a
    ser uma transação única — antes o preço mudava num commit e o status
    da sugestão em outro.
  - **Conferência no caixa**: `GET /pedidos/{numero}`,
    `POST /pedidos/{numero}/conferir`, `GET /pedidos`,
    `POST /pedidos/expirar-agora` + tela `/caixa`. O enum já
    tinha `CONFERIDO_NO_CAIXA` e nenhum código escrevia nele; agora esse é
    o evento que marca a venda como concretizada. Pedido vencido ainda
    pode ser conferido (cliente pega fila) e expirar **não** devolve
    estoque — a mercadoria já saiu da prateleira.
  - **Seed simulado** (ver aviso acima): 56 produtos, ~885 pedidos, ~3.600
    unidades, 18 promoções históricas (2 ainda vigentes).
  - **Camada de indicadores**: `/analytics/*` + tela
    `/indicadores` com taxa de aprovação da IA, desconto
    sugerido × aplicado, tempo até decisão, Groq × Gemini, efeito de cada
    promoção (antes/depois normalizado por dia) e capital parado. Gráficos
    em SVG inline, sem biblioteca de charts. Só entram pedidos conferidos
    no caixa.
  - **Harness de avaliação do LLM** (`scripts/avaliar_llm.py`): a
    evidência experimental que **não** depende de dado simulado.
  162 testes automatizados (eram 72).
- **Próxima**: polimento para a banca (testes em iOS/Android reais,
  roteiro de demo, redação da justificativa técnica da IA) — em paralelo
  com a Fase 7 (comprar/montar o primeiro protótipo de display).

Roadmap completo das próximas fases no plano de implementação.
