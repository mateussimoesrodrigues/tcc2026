# Sistema de Precificação Inteligente para Varejo Físico

TCC: digitalização e automação da precificação de uma loja de varejo físico
(armarinho/papelaria/artesanato). Duas áreas — cliente (scanner de QR/código
de barras → carrinho → checkout sem pagamento) e funcionário (login, gestão
de estoque com alerta de estoque baixo, sugestões de promoção geradas por
IA aguardando aprovação) — mais, num momento futuro, displays físicos de
preço.

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
  justificativa detalhada no plano.

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

```bash
python -m app.seed
```

Popula (ou repopula do zero — o script limpa as tabelas antes) o catálogo
com os produtos reais da loja + itens adicionais das mesmas marcas, além
de um histórico de vendas simulado dos últimos 90 dias, usado como base
pelas regras da IA de promoções na Fase 4.

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

## Estrutura

```
backend/app/
  core/       # config, conexão com banco, segurança (JWT)
  models/     # SQLAlchemy ORM
  schemas/    # Pydantic
  routers/    # endpoints FastAPI
  services/   # regras de negócio
  ai/         # regras + integração com LLM (motor de sugestão de promoções)
  jobs/       # rotinas agendadas (geração diária de sugestões, expiração de promoções)
  alembic/    # migrations
  seed.py     # popula o catálogo + histórico de vendas simulado (rodar 1x)

frontend/src/
  cliente/       # área do cliente: scanner, carrinho, checkout
  funcionario/   # área do funcionário: login, estoque, produtos, promoções, histórico de preços
  api/           # client HTTP
  context/       # estado global (carrinho, autenticação)
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
  funcionário, e `DashboardEstoque` consumindo `/estoque` de verdade com
  destaque para estoque baixo.
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
  chama Groq (Llama 3.3 70B) via REST direto, com fallback automático pro
  Gemini 2.5 Flash, valida a resposta (JSON estrito, desconto 0-70%) e
  nunca deixa uma falha de IA travar os demais produtos;
  `services/promotion_service.py` orquestra tudo e `services/price_service.py`
  é o único lugar que de fato muda preço (transacional, sempre grava
  histórico); `POST /promocoes/gerar-agora` (sob demanda, essencial pra
  demo), `GET /promocoes`, aprovar/rejeitar, `GET /historico-precos` —
  todos exigem funcionário logado. Job diário (`jobs/scheduler.py`,
  APScheduler) fica desligado por padrão (`ENABLE_SCHEDULER=false`) pra
  não bater na API real durante testes; liga só em produção. Testado
  end-to-end contra o Neon com o LLM mockado (60 testes automatizados) e
  também contra a API real do backend rodando — sem `GROQ_API_KEY`/
  `GEMINI_API_KEY` ainda configuradas, então a geração funciona e reporta
  a falha de IA por produto sem quebrar nada; falta só colar as chaves
  gratuitas no `.env` (ver `.env.example`) pra ver as sugestões de
  verdade sendo geradas. Frontend: telas Promoções (gerar sob demanda,
  aprovar/rejeitar com observação) e Histórico de Preços funcionais.
- **Próxima**: Fase 5 — deploy em nuvem + hardening (CORS restrito,
  variáveis de produção, CI/CD).

Roadmap completo das próximas fases no plano de implementação.
