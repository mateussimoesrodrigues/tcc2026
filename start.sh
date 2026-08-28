#!/usr/bin/env bash
#
# start.sh --local
#
# Sobe backend (FastAPI/uvicorn) e frontend (Vite) juntos num terminal so.
# Ctrl+C encerra os dois. Funciona no Git Bash (Windows) e em bash Linux/Mac.
#
# Uso:
#   ./start.sh --local     sobe backend + frontend em modo desenvolvimento
#   ./start.sh --help      mostra esta ajuda

set -euo pipefail

# --- localizacao: sempre opera a partir da raiz do repo, nao do cwd ---------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend"

BACKEND_HOST="127.0.0.1"
BACKEND_PORT="8000"
FRONTEND_URL="http://localhost:5173"

# --- deteccao de plataforma ------------------------------------------------
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) IS_WINDOWS=1 ;;
  *)                    IS_WINDOWS=0 ;;
esac

usage() {
  sed -n '3,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

# --- parse de argumentos -------------------------------------------------------
MODE=""
for arg in "$@"; do
  case "$arg" in
    --local)      MODE="local" ;;
    -h|--help)    usage; exit 0 ;;
    *) echo "argumento desconhecido: $arg" >&2; echo >&2; usage >&2; exit 2 ;;
  esac
done

if [ "$MODE" != "local" ]; then
  echo "erro: informe o modo. Ex.: ./start.sh --local" >&2
  echo >&2
  usage >&2
  exit 2
fi

# --- pre-checagens do backend -----------------------------------------------
if [ "$IS_WINDOWS" = "1" ]; then
  VENV_PY="$BACKEND_DIR/venv/Scripts/python.exe"
else
  VENV_PY="$BACKEND_DIR/venv/bin/python"
fi

if [ ! -x "$VENV_PY" ]; then
  echo "erro: venv do backend nao encontrada em backend/venv" >&2
  echo "  crie com:  cd backend && python -m venv venv && source venv/Scripts/activate && pip install -r requirements.txt" >&2
  exit 1
fi

if ! "$VENV_PY" -c "import uvicorn" >/dev/null 2>&1; then
  echo "erro: dependencias do backend faltando na venv" >&2
  echo "  rode:  \"$VENV_PY\" -m pip install -r backend/requirements.txt" >&2
  exit 1
fi

if [ ! -f "$BACKEND_DIR/.env" ]; then
  echo "aviso: backend/.env nao existe -- usando SQLite local e sem chaves de LLM."
  echo "       copie de backend/.env.example se precisar de Neon/Groq/Gemini."
fi

# --- pre-checagens do frontend --------------------------------------------------
if ! command -v npm >/dev/null 2>&1; then
  echo "erro: npm nao encontrado no PATH" >&2
  exit 1
fi

if [ ! -f "$FRONTEND_DIR/.env" ] && [ -f "$FRONTEND_DIR/.env.example" ]; then
  echo "frontend/.env ausente -- criando a partir de .env.example"
  cp "$FRONTEND_DIR/.env.example" "$FRONTEND_DIR/.env"
fi

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  echo "frontend/node_modules ausente -- rodando npm install (isso demora na 1a vez)..."
  ( cd "$FRONTEND_DIR" && npm install )
fi

# --- encerramento limpo dos dois processos ----------------------------------
BACKEND_BPID=""
FRONTEND_BPID=""
BACKEND_WPID=""
FRONTEND_WPID=""

winpid_de() {
  # traduz o PID interno do bash ($!) pro PID nativo do Windows, que e o
  # que o taskkill entende. Fora do Windows nao ha traducao: devolve o
  # proprio PID.
  local bpid="$1"
  [ -n "$bpid" ] || return 0
  if [ "$IS_WINDOWS" = "1" ]; then
    cat "/proc/$bpid/winpid" 2>/dev/null || true
  else
    echo "$bpid"
  fi
}

matar() {
  # $1 = PID interno do bash, $2 = winpid capturado no start. Mata a arvore
  # inteira -- uvicorn --reload e o vite sobem processos filhos que nao
  # morrem so com o sinal no processo pai.
  local bpid="$1" wpid="$2"
  [ -n "$bpid$wpid" ] || return 0
  kill "$bpid" 2>/dev/null || true
  if [ "$IS_WINDOWS" = "1" ] && [ -n "$wpid" ]; then
    taskkill //F //T //PID "$wpid" >/dev/null 2>&1 || true
  fi
}

CLEANUP_DONE=0
cleanup() {
  trap - INT TERM EXIT
  [ "$CLEANUP_DONE" = "1" ] && return 0
  CLEANUP_DONE=1
  echo
  echo "encerrando backend e frontend..."
  matar "$FRONTEND_BPID" "$FRONTEND_WPID"
  matar "$BACKEND_BPID" "$BACKEND_WPID"
}
trap cleanup INT TERM EXIT

# --- sobe os dois -----------------------------------------------------------
echo "backend  -> http://$BACKEND_HOST:$BACKEND_PORT  (docs em /docs)"
echo "frontend -> $FRONTEND_URL"
echo "Ctrl+C para encerrar os dois."
echo

(
  cd "$BACKEND_DIR"
  exec "$VENV_PY" -m uvicorn app.main:app --reload --host "$BACKEND_HOST" --port "$BACKEND_PORT"
) &
BACKEND_BPID=$!
BACKEND_WPID="$(winpid_de "$BACKEND_BPID")"

# Roda o Vite direto pelo binario local em vez de `npm run dev`: o npm nao
# repassa sinais pro processo filho, entao no Ctrl+C ele morre e deixa o
# Vite orfao. Sem o npm no meio, o taskkill //T pega a arvore toda.
(
  cd "$FRONTEND_DIR"
  if [ -x "node_modules/.bin/vite" ]; then
    exec node_modules/.bin/vite
  else
    exec npm run dev
  fi
) &
FRONTEND_BPID=$!
FRONTEND_WPID="$(winpid_de "$FRONTEND_BPID")"

# Espera ativa: o Ctrl+C interrompe o sleep e dispara o trap acima. Se um
# dos dois processos cair sozinho, o loop termina e derrubamos o outro.
while kill -0 "$BACKEND_BPID" 2>/dev/null && kill -0 "$FRONTEND_BPID" 2>/dev/null; do
  sleep 1
done

echo
echo "um dos processos encerrou -- derrubando o outro."
cleanup
exit 1
