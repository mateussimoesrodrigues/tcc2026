"""Harness de avaliacao do LLM do motor de promocoes.

Produz a evidencia experimental do TCC. Diferente do resto das metricas do
sistema (que rodam sobre o dataset simulado do seed), o que sai daqui e
**dado real e reproduzivel**: sao chamadas de verdade aos provedores, com
as respostas medidas. Nao depende da loja ter operacao real.

O que mede:

- **Consistencia**: o mesmo produto, K vezes, no mesmo modelo -- qual a
  variacao do desconto sugerido? Um LLM com temperatura 0.3 deveria ser
  razoavelmente estavel; quantificar isso responde "da pra confiar numa
  resposta so?".
- **Taxa de resposta invalida**, por classe de erro (JSON malformado,
  campo ausente, faixa invalida, incoerencia entre percentual e preco,
  preco abaixo do piso de custo).
- **Latencia** (media, p50, p95) por provedor.
- **Groq x Gemini** nas mesmas entradas.
- **LLM x baseline deterministico**: o LLM ganha de uma regra simples?
  Se nao ganhar, isso tambem e um resultado -- e honesto reportar.
- **Efeito de informar o teto no prompt** (`--informar-piso` /
  `--sem-informar-piso`): reduz resposta invalida? E um A/B proprio.

E script, nao teste: assim `pytest` nunca gasta quota de free tier.

Uso:
    cd backend
    ./venv/Scripts/python.exe -m scripts.avaliar_llm --dry-run          # sem rede
    ./venv/Scripts/python.exe -m scripts.avaliar_llm --produtos 10 --repeticoes 5
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx

from app.ai import llm_provider, rules
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.produto import Produto
from app.services import price_service
from app.services.exceptions import (
    LLMIndisponivelError,
    PrecoPromocionalInvalidoError,
    RespostaLLMInvalidaError,
)

PASTA_PADRAO = Path(__file__).resolve().parent / "resultados"
ARQUIVO_CACHE = "cache.jsonl"

PROVEDORES = ("groq", "gemini")


# ---------------------------------------------------------------------------
# Configuracao da execucao
# ---------------------------------------------------------------------------
@dataclass
class Config:
    produtos: int = 10
    repeticoes: int = 5
    provedores: tuple[str, ...] = PROVEDORES
    temperatura: float = 0.3
    seed: int = 42
    saida: Path = PASTA_PADRAO
    limite_chamadas: int = 200
    intervalo_ms: int = 500
    usar_cache: bool = True
    dry_run: bool = False
    baseline_apenas: bool = False
    informar_piso: bool | None = None  # None = usa o valor do .env


@dataclass
class ExecucaoLLM:
    """Uma chamada. Vira uma linha do CSV."""

    timestamp: str
    produto_id: int
    produto_nome: str
    provedor: str
    modelo: str
    temperatura: float
    repeticao: int
    informar_piso: bool
    sucesso: bool
    classe_erro: str | None = None
    erro: str | None = None
    percentual: float | None = None
    preco: float | None = None
    prioridade: str | None = None
    latencia_ms: float = 0.0
    coerente: bool | None = None
    respeita_piso: bool | None = None
    desconto_baseline: float = 0.0
    desconto_maximo_permitido: float = 0.0
    justificativa_chars: int = 0
    origem: str = "rede"  # "rede" | "cache" | "stub"


# ---------------------------------------------------------------------------
# Baseline deterministico -- o braco de comparacao
# ---------------------------------------------------------------------------
def baseline_deterministico(sinais: rules.SinaisProduto, produto: Produto) -> Decimal:
    """Regra simples e explicavel, sem IA nenhuma. Existe pra responder a
    pergunta que a banca vai fazer: o LLM entrega algo que um `if` nao
    entregaria? A regra usa os mesmos sinais que vao no prompt."""
    dias = sinais.dias_sem_venda
    if dias is None or dias >= 60:
        base = 25
    elif dias >= 45:
        base = 20
    elif dias >= 30:
        base = 15
    else:
        base = 10

    if sinais.dias_de_estoque_restante is not None and sinais.dias_de_estoque_restante > 120:
        base += 5
    if sinais.dias_ate_data_sazonal <= 15:
        base += 5

    teto = price_service.desconto_maximo_permitido(produto)
    return min(Decimal(base), teto)


# ---------------------------------------------------------------------------
# Amostragem
# ---------------------------------------------------------------------------
def amostrar_produtos(db, quantidade: int, seed: int) -> list[tuple[Produto, rules.SinaisProduto]]:
    """Amostra deterministica dos candidatos: ordena por id antes de
    sortear, pra a mesma seed dar sempre a mesma amostra."""
    candidatos = sorted(rules.gerar_candidatos(db), key=lambda s: s.produto_id)
    if not candidatos:
        return []
    rng = random.Random(seed)
    escolhidos = rng.sample(candidatos, min(quantidade, len(candidatos)))
    escolhidos.sort(key=lambda s: s.produto_id)
    return [(db.get(Produto, s.produto_id), s) for s in escolhidos]


# ---------------------------------------------------------------------------
# Execucao de uma chamada
# ---------------------------------------------------------------------------
def _classificar_erro(e: Exception) -> str:
    if isinstance(e, httpx.TimeoutException):
        return "timeout"
    if isinstance(e, httpx.HTTPError):
        return "http"
    if isinstance(e, LLMIndisponivelError):
        return "sem_chave"
    if isinstance(e, PrecoPromocionalInvalidoError):
        return "abaixo_do_piso"
    if isinstance(e, RespostaLLMInvalidaError):
        mensagem = str(e)
        if "nao e JSON valido" in mensagem:
            return "json_malformado"
        if "Campo ausente" in mensagem:
            return "campo_ausente"
        if "fora da faixa" in mensagem:
            return "faixa_invalida"
        if "Incoerencia" in mensagem:
            return "incoerencia_pct_preco"
        if "Justificativa vazia" in mensagem:
            return "justificativa_vazia"
        if "invalido" in mensagem:
            return "preco_invalido"
        return "resposta_invalida"
    return type(e).__name__


def _stub_resposta(sinais: rules.SinaisProduto, rng: random.Random) -> dict:
    """Provedor falso do --dry-run: valida o pipeline inteiro (montagem do
    prompt, parsing, validacao, CSV) sem rede nem quota."""
    percentual = round(rng.uniform(8, 32), 1)
    preco = round(sinais.preco_normal * (1 - percentual / 100), 2)
    return {
        "percentual_desconto_sugerido": percentual,
        "preco_sugerido": preco,
        "justificativa": "Resposta sintetica do modo --dry-run, sem chamada de rede.",
        "prioridade": rng.choice(["baixa", "media", "alta"]),
    }


def _chave_cache(provedor: str, sinais: rules.SinaisProduto, cfg: Config, repeticao: int) -> str:
    bruto = json.dumps(
        {
            "provedor": provedor,
            "prompt_sistema": hashlib.sha256(llm_provider.PROMPT_SISTEMA.encode()).hexdigest()[:16],
            "prompt_usuario": llm_provider._montar_prompt_usuario(sinais),
            "temperatura": cfg.temperatura,
            "repeticao": repeticao,
        },
        sort_keys=True,
    )
    return hashlib.sha256(bruto.encode()).hexdigest()


def executar_uma(
    provedor: str,
    produto: Produto,
    sinais: rules.SinaisProduto,
    cfg: Config,
    repeticao: int,
    client: httpx.Client | None,
    rng: random.Random,
    cache: dict[str, dict],
) -> ExecucaoLLM:
    settings = get_settings()
    modelo = llm_provider.GROQ_MODELO if provedor == "groq" else llm_provider.GEMINI_MODELO
    baseline = baseline_deterministico(sinais, produto)
    teto = price_service.desconto_maximo_permitido(produto)

    execucao = ExecucaoLLM(
        timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
        produto_id=produto.id,
        produto_nome=produto.nome,
        provedor=provedor,
        modelo=f"{provedor}/{modelo}",
        temperatura=cfg.temperatura,
        repeticao=repeticao,
        informar_piso=settings.informar_piso_no_prompt,
        sucesso=False,
        desconto_baseline=float(baseline),
        desconto_maximo_permitido=float(teto),
    )

    chave = _chave_cache(provedor, sinais, cfg, repeticao)
    inicio = time.perf_counter()
    try:
        if cfg.dry_run:
            dados = _stub_resposta(sinais, rng)
            execucao.origem = "stub"
        elif cfg.usar_cache and chave in cache:
            dados = cache[chave]
            execucao.origem = "cache"
        else:
            if provedor == "groq":
                dados = llm_provider._chamar_groq(client, sinais, settings.groq_api_key)
            else:
                dados = llm_provider._chamar_gemini(client, sinais, settings.gemini_api_key)
            cache[chave] = dados

        sugestao = llm_provider._validar_resposta(
            dados, execucao.modelo, preco_normal=Decimal(str(sinais.preco_normal))
        )
        execucao.coerente = True

        # O guard-rail nao invalida a resposta aqui -- e registrado como
        # um resultado a parte, pra dar pra dizer "X% das respostas do LLM
        # feriam o piso de custo".
        try:
            price_service.validar_preco_promocional(produto, sugestao.preco_sugerido)
            execucao.respeita_piso = True
        except PrecoPromocionalInvalidoError:
            execucao.respeita_piso = False

        execucao.sucesso = True
        execucao.percentual = float(sugestao.percentual_desconto)
        execucao.preco = float(sugestao.preco_sugerido)
        execucao.prioridade = sugestao.prioridade
        execucao.justificativa_chars = len(sugestao.justificativa)
    except Exception as e:  # noqa: BLE001 -- queremos classificar tudo que der errado
        execucao.classe_erro = _classificar_erro(e)
        execucao.erro = str(e)[:300]
        if execucao.classe_erro == "incoerencia_pct_preco":
            execucao.coerente = False
    finally:
        execucao.latencia_ms = round((time.perf_counter() - inicio) * 1000, 1)

    return execucao


# ---------------------------------------------------------------------------
# Estatistica
# ---------------------------------------------------------------------------
def _postos(valores: list[float]) -> list[float]:
    """Postos com media em caso de empate (necessario pro Spearman)."""
    ordenados = sorted(range(len(valores)), key=lambda i: valores[i])
    postos = [0.0] * len(valores)
    i = 0
    while i < len(ordenados):
        j = i
        while j + 1 < len(ordenados) and valores[ordenados[j + 1]] == valores[ordenados[i]]:
            j += 1
        media = (i + j) / 2 + 1
        for k in range(i, j + 1):
            postos[ordenados[k]] = media
        i = j + 1
    return postos


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Correlacao de postos. Escrita a mao pra nao arrastar scipy/numpy
    pro requirements so por causa de uma funcao."""
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    px, py = _postos(xs), _postos(ys)
    mx, my = statistics.fmean(px), statistics.fmean(py)
    num = sum((a - mx) * (b - my) for a, b in zip(px, py))
    den = (sum((a - mx) ** 2 for a in px) * sum((b - my) ** 2 for b in py)) ** 0.5
    return round(num / den, 4) if den else None


def _percentil(valores: list[float], p: float) -> float | None:
    if not valores:
        return None
    ordenados = sorted(valores)
    indice = min(int(round(p * (len(ordenados) - 1))), len(ordenados) - 1)
    return round(ordenados[indice], 1)


def resumir_por_produto(execucoes: list[ExecucaoLLM]) -> list[dict]:
    """Consistencia: uma linha por (produto, provedor)."""
    grupos: dict[tuple[int, str], list[ExecucaoLLM]] = {}
    for e in execucoes:
        grupos.setdefault((e.produto_id, e.provedor), []).append(e)

    linhas = []
    for (produto_id, provedor), itens in sorted(grupos.items()):
        ok = [i for i in itens if i.sucesso and i.percentual is not None]
        percentuais = [i.percentual for i in ok]
        media = statistics.fmean(percentuais) if percentuais else None
        desvio = statistics.pstdev(percentuais) if len(percentuais) > 1 else 0.0
        prioridades = {i.prioridade for i in ok}
        linhas.append(
            {
                "produto_id": produto_id,
                "produto_nome": itens[0].produto_nome,
                "provedor": provedor,
                "execucoes": len(itens),
                "sucessos": len(ok),
                "desconto_medio": round(media, 2) if media is not None else None,
                "desconto_desvio": round(desvio, 2),
                # Coeficiente de variacao: desvio relativo a media, o que
                # torna produtos com descontos distintos comparaveis.
                "coef_variacao": round(desvio / media, 4) if media else None,
                "desconto_min": round(min(percentuais), 2) if percentuais else None,
                "desconto_max": round(max(percentuais), 2) if percentuais else None,
                "amplitude": round(max(percentuais) - min(percentuais), 2) if percentuais else None,
                "prioridades_distintas": len(prioridades),
                "desconto_baseline": itens[0].desconto_baseline,
                "latencia_media_ms": round(statistics.fmean([i.latencia_ms for i in itens]), 1),
            }
        )
    return linhas


def resumir_por_provedor(execucoes: list[ExecucaoLLM], por_produto: list[dict]) -> list[dict]:
    linhas = []
    for provedor in sorted({e.provedor for e in execucoes}):
        itens = [e for e in execucoes if e.provedor == provedor]
        ok = [i for i in itens if i.sucesso]
        latencias = [i.latencia_ms for i in itens]
        cvs = [linha["coef_variacao"] for linha in por_produto
               if linha["provedor"] == provedor and linha["coef_variacao"] is not None]

        pareados = [(i.desconto_baseline, i.percentual) for i in ok if i.percentual is not None]
        erro_medio = (
            round(statistics.fmean([abs(b - p) for b, p in pareados]), 2) if pareados else None
        )
        mais_agressivo = (
            round(sum(1 for b, p in pareados if p > b) / len(pareados) * 100, 1) if pareados else None
        )

        erros: dict[str, int] = {}
        for i in itens:
            if i.classe_erro:
                erros[i.classe_erro] = erros.get(i.classe_erro, 0) + 1

        linhas.append(
            {
                "provedor": provedor,
                "modelo": itens[0].modelo,
                "execucoes": len(itens),
                "sucessos": len(ok),
                "taxa_sucesso_pct": round(len(ok) / len(itens) * 100, 1) if itens else None,
                "taxa_invalida_pct": round((len(itens) - len(ok)) / len(itens) * 100, 1) if itens else None,
                "erros_por_classe": json.dumps(erros, sort_keys=True),
                "desconto_medio": round(statistics.fmean([i.percentual for i in ok if i.percentual is not None]), 2)
                if any(i.percentual is not None for i in ok)
                else None,
                "coef_variacao_medio": round(statistics.fmean(cvs), 4) if cvs else None,
                "respeitam_piso_pct": round(
                    sum(1 for i in ok if i.respeita_piso) / len(ok) * 100, 1
                ) if ok else None,
                "erro_medio_vs_baseline_pp": erro_medio,
                "spearman_vs_baseline": spearman([b for b, _ in pareados], [p for _, p in pareados]),
                "mais_agressivo_que_baseline_pct": mais_agressivo,
                "latencia_media_ms": round(statistics.fmean(latencias), 1) if latencias else None,
                "latencia_p50_ms": _percentil(latencias, 0.50),
                "latencia_p95_ms": _percentil(latencias, 0.95),
            }
        )
    return linhas


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------
def _commit_atual() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True, cwd=Path(__file__).resolve().parent,
        ).stdout.strip()
    except Exception:
        return "desconhecido"


def salvar(execucoes, por_produto, por_provedor, cfg: Config) -> dict[str, Path]:
    cfg.saida.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")

    caminhos = {
        "execucoes": cfg.saida / f"execucoes_{carimbo}.csv",
        "por_produto": cfg.saida / f"resumo_produto_{carimbo}.csv",
        "por_provedor": cfg.saida / f"resumo_provedor_{carimbo}.csv",
        "metadados": cfg.saida / f"metadados_{carimbo}.json",
    }

    def escrever(caminho: Path, linhas: list[dict]) -> None:
        if not linhas:
            caminho.write_text("", encoding="utf-8")
            return
        with caminho.open("w", newline="", encoding="utf-8") as f:
            escritor = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
            escritor.writeheader()
            escritor.writerows(linhas)

    escrever(caminhos["execucoes"], [asdict(e) for e in execucoes])
    escrever(caminhos["por_produto"], por_produto)
    escrever(caminhos["por_provedor"], por_provedor)

    settings = get_settings()
    caminhos["metadados"].write_text(
        json.dumps(
            {
                "gerado_em": datetime.now(UTC).isoformat(timespec="seconds"),
                "commit": _commit_atual(),
                # Hash do prompt: se o prompt mudar, os resultados nao sao
                # mais comparaveis com os de coletas anteriores.
                "hash_prompt_sistema": hashlib.sha256(llm_provider.PROMPT_SISTEMA.encode()).hexdigest()[:16],
                "modelos": {"groq": llm_provider.GROQ_MODELO, "gemini": llm_provider.GEMINI_MODELO},
                "temperatura": cfg.temperatura,
                "produtos": cfg.produtos,
                "repeticoes": cfg.repeticoes,
                "provedores": list(cfg.provedores),
                "seed": cfg.seed,
                "dry_run": cfg.dry_run,
                "informar_piso_no_prompt": settings.informar_piso_no_prompt,
                "margem_minima_percentual": settings.margem_minima_percentual,
                "desconto_maximo_percentual": settings.desconto_maximo_percentual,
                "total_chamadas": len(execucoes),
                # NUNCA gravar as chaves de API aqui -- so se estao presentes.
                "groq_key_presente": bool(settings.groq_api_key),
                "gemini_key_presente": bool(settings.gemini_api_key),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return caminhos


def _carregar_cache(pasta: Path) -> dict[str, dict]:
    caminho = pasta / ARQUIVO_CACHE
    if not caminho.exists():
        return {}
    cache = {}
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if not linha.strip():
            continue
        try:
            registro = json.loads(linha)
            cache[registro["chave"]] = registro["resposta"]
        except (json.JSONDecodeError, KeyError):
            continue
    return cache


def _gravar_cache(pasta: Path, cache: dict[str, dict]) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    with (pasta / ARQUIVO_CACHE).open("w", encoding="utf-8") as f:
        for chave, resposta in cache.items():
            f.write(json.dumps({"chave": chave, "resposta": resposta}, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Orquestracao
# ---------------------------------------------------------------------------
def rodar_avaliacao(db, cfg: Config) -> list[ExecucaoLLM]:
    amostra = amostrar_produtos(db, cfg.produtos, cfg.seed)
    if not amostra:
        print("Nenhum produto candidato -- rode o seed antes (python -m app.seed).")
        return []

    total = len(amostra) * len(cfg.provedores) * cfg.repeticoes
    print(f"Amostra: {len(amostra)} produto(s) x {len(cfg.provedores)} provedor(es) "
          f"x {cfg.repeticoes} repeticao(oes) = {total} chamadas")
    if total > cfg.limite_chamadas:
        print(f"ABORTADO: {total} chamadas passa do limite de {cfg.limite_chamadas}. "
              f"Use --limite-chamadas pra elevar conscientemente.")
        return []

    cache = _carregar_cache(cfg.saida) if cfg.usar_cache and not cfg.dry_run else {}
    rng = random.Random(cfg.seed)
    execucoes: list[ExecucaoLLM] = []

    client = None if cfg.dry_run else httpx.Client(timeout=llm_provider.TIMEOUT_SEGUNDOS)
    try:
        for indice, (produto, sinais) in enumerate(amostra, start=1):
            for provedor in cfg.provedores:
                for repeticao in range(1, cfg.repeticoes + 1):
                    execucao = executar_uma(provedor, produto, sinais, cfg, repeticao, client, rng, cache)
                    execucoes.append(execucao)
                    marca = "ok" if execucao.sucesso else f"ERRO/{execucao.classe_erro}"
                    print(f"  [{len(execucoes):>3}/{total}] {produto.nome[:26]:<27} "
                          f"{provedor:<7} #{repeticao} {marca:<24} "
                          f"{execucao.percentual if execucao.percentual is not None else '--':>5}% "
                          f"{execucao.latencia_ms:>7.0f}ms ({execucao.origem})")
                    if not cfg.dry_run and execucao.origem == "rede" and cfg.intervalo_ms:
                        time.sleep(cfg.intervalo_ms / 1000)
            del indice
    finally:
        if client is not None:
            client.close()
        if cfg.usar_cache and not cfg.dry_run:
            _gravar_cache(cfg.saida, cache)

    return execucoes


def imprimir_resumo(por_provedor: list[dict]) -> None:
    print()
    print("=" * 78)
    for linha in por_provedor:
        print(f"{linha['provedor'].upper()}  ({linha['modelo']})")
        print(f"  sucesso            : {linha['taxa_sucesso_pct']}%  "
              f"({linha['sucessos']}/{linha['execucoes']})")
        print(f"  resposta invalida  : {linha['taxa_invalida_pct']}%  {linha['erros_por_classe']}")
        print(f"  desconto medio     : {linha['desconto_medio']}%")
        print(f"  consistencia (CV)  : {linha['coef_variacao_medio']}   "
              f"(0 = identico a cada chamada)")
        print(f"  respeitam o piso   : {linha['respeitam_piso_pct']}%")
        print(f"  vs baseline        : erro medio {linha['erro_medio_vs_baseline_pp']} p.p., "
              f"spearman {linha['spearman_vs_baseline']}, "
              f"mais agressivo em {linha['mais_agressivo_que_baseline_pct']}% dos casos")
        print(f"  latencia           : media {linha['latencia_media_ms']}ms  "
              f"p50 {linha['latencia_p50_ms']}ms  p95 {linha['latencia_p95_ms']}ms")
        print("-" * 78)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--produtos", type=int, default=10)
    parser.add_argument("--repeticoes", type=int, default=5)
    parser.add_argument("--provedor", choices=[*PROVEDORES, "ambos"], default="ambos")
    parser.add_argument("--temperatura", type=float, default=0.3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--saida", type=Path, default=PASTA_PADRAO)
    parser.add_argument("--limite-chamadas", type=int, default=200,
                        help="aborta antes de estourar quota do free tier")
    parser.add_argument("--intervalo-ms", type=int, default=500, help="pausa entre chamadas de rede")
    parser.add_argument("--sem-cache", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="provedor sintetico, sem rede nem quota -- valida o pipeline")
    args = parser.parse_args(argv)

    cfg = Config(
        produtos=args.produtos,
        repeticoes=args.repeticoes,
        provedores=PROVEDORES if args.provedor == "ambos" else (args.provedor,),
        temperatura=args.temperatura,
        seed=args.seed,
        saida=args.saida,
        limite_chamadas=args.limite_chamadas,
        intervalo_ms=args.intervalo_ms,
        usar_cache=not args.sem_cache,
        dry_run=args.dry_run,
    )

    if cfg.dry_run:
        print(">>> MODO --dry-run: respostas sinteticas, nenhuma chamada de rede. <<<\n")

    db = SessionLocal()
    try:
        execucoes = rodar_avaliacao(db, cfg)
    finally:
        db.close()

    if not execucoes:
        return 1

    por_produto = resumir_por_produto(execucoes)
    por_provedor = resumir_por_provedor(execucoes, por_produto)
    imprimir_resumo(por_provedor)

    caminhos = salvar(execucoes, por_produto, por_provedor, cfg)
    print("\nArquivos gerados:")
    for nome, caminho in caminhos.items():
        print(f"  {nome:<12} {caminho}")
    if cfg.dry_run:
        print("\nLembrete: numeros do --dry-run sao sinteticos e NAO servem como resultado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
