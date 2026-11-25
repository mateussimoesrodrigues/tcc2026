import { useEffect, useState } from "react";
import { ApiError, apiFetch } from "../../api/client";
import Badge, { type TomBadge } from "../../components/Badge";
import Icone from "../../components/Icone";
import { PromoPrice } from "../../components/Preco";
import Skeleton from "../../components/Skeleton";
import { contar, formatBRL, formatDateTime, formatPercent, formatPercentFracao } from "../../utils/format";

interface SinaisDetectados {
  dias_sem_venda: number | null;
  unidades_vendidas_periodo: number;
  janela_dias: number;
  giro_diario: number;
  dias_de_estoque_restante: number | null;
  margem: number | null;
  proxima_data_sazonal: string;
  dias_ate_data_sazonal: number;
}

interface Sugestao {
  id: number;
  produto_id: number;
  produto_nome: string;
  produto_marca: string | null;
  produto_tamanho: string | null;
  preco_normal: string;
  sinais_detectados: SinaisDetectados;
  percentual_desconto_sugerido: string;
  preco_sugerido: string;
  justificativa_ia: string;
  prioridade: "baixa" | "media" | "alta";
  modelo_ia_usado: string;
  status: "pendente" | "aprovada" | "rejeitada" | "expirada";
  criado_em: string;
}

interface ProdutoEmPromocao {
  id: number;
  nome: string;
  marca: string | null;
  tamanho: string | null;
  preco_normal: string;
  preco_promocional: string | null;
  promocao_ativa: boolean;
  promocao_expira_em: string | null;
}

interface Falha {
  produto_id: number;
  nome: string;
  motivo: string;
  // "llm" = provedor não respondeu / resposta fora do formato.
  // "guard_rail" = respondeu, mas o preço feria o piso de custo.
  categoria?: "llm" | "guard_rail";
}

interface AvaliacaoCandidato {
  produto_id: number;
  nome: string;
  status: "criada" | "ja_pendente" | "falha";
  motivo: string | null;
  categoria?: "llm" | "guard_rail";
}

// Corpo dos 422/409 de preço promocional (schemas/promocao.ErroPrecoRead).
interface ErroPreco {
  codigo: string;
  mensagem: string;
  detalhes: Record<string, unknown>;
}

function extrairErroPreco(e: unknown): ErroPreco | null {
  if (!(e instanceof ApiError) || typeof e.body !== "object" || e.body === null) return null;
  const detail = (e.body as { detail?: unknown }).detail;
  if (typeof detail !== "object" || detail === null || !("codigo" in detail)) return null;
  return detail as ErroPreco;
}

// Traduz o código estável do backend numa instrução acionável. O código
// existe justamente para a UI não depender de casar a string traduzida.
function mensagemErroPreco({ codigo, mensagem, detalhes }: ErroPreco): string {
  switch (codigo) {
    case "abaixo_do_piso":
      if (detalhes.piso == null) {
        return "Produto sem custo cadastrado — cadastre o custo em Produtos antes de promover.";
      }
      return (
        `Preço abaixo do piso de ${formatBRL(detalhes.piso as string | number)} ` +
        `(custo ${formatBRL(detalhes.custo as string | number)} + margem mínima de ${formatPercent(detalhes.margem_minima_percentual as string | number, 0)}). ` +
        `Ajuste o custo em Produtos ou rejeite a sugestão.`
      );
    case "promocao_ja_ativa":
      return detalhes.expira_em
        ? `Este produto já está em promoção até ${formatDateTime(String(detalhes.expira_em))}.`
        : "Este produto já está em promoção.";
    default:
      return mensagem;
  }
}

interface GerarResposta {
  candidatos_avaliados: number;
  sugestoes_criadas: Sugestao[];
  falhas: Falha[];
  avaliacoes: AvaliacaoCandidato[];
}

const PRIORIDADE: Record<Sugestao["prioridade"], { rotulo: string; tom: TomBadge }> = {
  alta: { rotulo: "Prioridade alta", tom: "danger" },
  media: { rotulo: "Prioridade média", tom: "warning" },
  baixa: { rotulo: "Prioridade baixa", tom: "neutral" },
};

function resumoSinais(s: SinaisDetectados): string {
  const partes: string[] = [];
  partes.push(
    s.dias_sem_venda !== null
      ? `${contar(s.dias_sem_venda, "dia", "dias")} sem venda`
      : `sem venda nos últimos ${contar(s.janela_dias, "dia", "dias")}`
  );
  if (s.dias_de_estoque_restante !== null) {
    partes.push(`estoque dura ~${contar(Math.round(s.dias_de_estoque_restante), "dia", "dias")} no ritmo atual`);
  }
  if (s.margem !== null) {
    partes.push(`margem ~${formatPercentFracao(s.margem, 0)}`);
  }
  partes.push(`${s.proxima_data_sazonal} em ${contar(s.dias_ate_data_sazonal, "dia", "dias")}`);
  return partes.join(" · ");
}

export default function Promocoes() {
  const [sugestoes, setSugestoes] = useState<Sugestao[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [gerando, setGerando] = useState(false);
  const [resumoGeracao, setResumoGeracao] = useState<GerarResposta | null>(null);
  const [observacoes, setObservacoes] = useState<Record<number, string>>({});
  // A validade e digitada em DIAS; a API espera horas (convertido em avaliar()).
  const [diasValidade, setDiasValidade] = useState<Record<number, string>>({});
  const [abertas, setAbertas] = useState<Record<number, boolean>>({});
  const [avaliando, setAvaliando] = useState<number | null>(null);
  // Erro por sugestão (e não global): o guard-rail de preço recusa uma
  // sugestão específica, e a mensagem precisa aparecer no card dela.
  const [erroPorSugestao, setErroPorSugestao] = useState<Record<number, string>>({});

  const [ativas, setAtivas] = useState<ProdutoEmPromocao[]>([]);
  const [finalizando, setFinalizando] = useState<number | null>(null);
  const [erroAtivas, setErroAtivas] = useState<string | null>(null);

  function carregarAtivas() {
    apiFetch<ProdutoEmPromocao[]>("/produtos", { auth: true })
      .then((produtos) => setAtivas(produtos.filter((p) => p.promocao_ativa)))
      .catch(() => setErroAtivas("Não foi possível carregar as promoções ativas."));
  }

  function carregar() {
    setCarregando(true);
    setErro(null);
    apiFetch<Sugestao[]>("/promocoes?status_filtro=pendente", { auth: true })
      .then(setSugestoes)
      .catch(() => setErro("Não foi possível carregar as sugestões."))
      .finally(() => setCarregando(false));
    carregarAtivas();
  }

  useEffect(carregar, []);

  async function finalizarPromocao(produtoId: number) {
    setFinalizando(produtoId);
    setErroAtivas(null);
    try {
      await apiFetch(`/promocoes/produtos/${produtoId}/finalizar`, { method: "POST", auth: true });
      setAtivas((atual) => atual.filter((p) => p.id !== produtoId));
    } catch {
      setErroAtivas("Não foi possível finalizar a promoção.");
    } finally {
      setFinalizando(null);
    }
  }

  // Unico gatilho de geracao no sistema: nao ha job por tempo criando
  // sugestoes sozinho (ver backend/app/jobs/scheduler.py). O endpoint
  // expira as promocoes vencidas antes de gerar, entao um clique deixa a
  // tela inteira em dia.
  async function gerarAgora() {
    setGerando(true);
    setErro(null);
    setResumoGeracao(null);
    try {
      const resposta = await apiFetch<GerarResposta>("/promocoes/gerar-agora", { method: "POST", auth: true });
      setResumoGeracao(resposta);
      carregar();
    } catch {
      setErro("Não foi possível gerar sugestões agora.");
    } finally {
      setGerando(false);
    }
  }

  async function avaliar(id: number, acao: "aprovar" | "rejeitar") {
    setAvaliando(id);
    setErroPorSugestao((atual) => {
      const { [id]: _descartado, ...resto } = atual;
      return resto;
    });
    try {
      const dias = diasValidade[id]?.trim();
      await apiFetch(`/promocoes/${id}/${acao}`, {
        method: "POST",
        auth: true,
        body: JSON.stringify({
          observacao: observacoes[id] || undefined,
          ...(acao === "aprovar" && dias ? { horas_validade: Number(dias) * 24 } : {}),
        }),
      });
      // Só some da lista quando deu certo de verdade -- antes o card era
      // removido otimisticamente e o funcionário perdia a sugestão de vista
      // mesmo quando a aprovação falhava.
      setSugestoes((atual) => atual.filter((s) => s.id !== id));
    } catch (e) {
      const erroPreco = extrairErroPreco(e);
      setErroPorSugestao((atual) => ({
        ...atual,
        [id]: erroPreco
          ? mensagemErroPreco(erroPreco)
          : `Não foi possível ${acao === "aprovar" ? "aprovar" : "rejeitar"} a sugestão.`,
      }));
    } finally {
      setAvaliando(null);
    }
  }

  return (
    <div className="page page-wide">
      <h1>Sugestões de promoção (IA)</h1>
      <br></br>

      <button type="button" onClick={gerarAgora} disabled={gerando} className="promo-gerar-btn">
        {gerando && <span className="spinner" aria-hidden="true" />}
        {gerando ? "Gerando..." : "Gerar sugestões agora"}
      </button>

      {gerando && (
        <p className="promo-gerando-aviso">
          A IA está analisando cada produto parado individualmente — isso pode levar até um minuto.
        </p>
      )}

      {resumoGeracao && (
        <p className="promo-resumo-geracao">
          {contar(resumoGeracao.candidatos_avaliados, "candidato analisado", "candidatos analisados")},{" "}
          {contar(resumoGeracao.sugestoes_criadas.length, "sugestão nova", "sugestões novas")}
          {resumoGeracao.falhas.length > 0 && <> — {contar(resumoGeracao.falhas.length, "não gerou sugestão", "não geraram sugestão")}</>}.
        </p>
      )}
      {resumoGeracao && resumoGeracao.avaliacoes.length > 0 && (
        <ul className="promo-falhas">
          {resumoGeracao.avaliacoes.map((avaliacao) => (
            <li key={avaliacao.produto_id}>
              <strong>{avaliacao.nome}</strong>: {avaliacao.status === "criada" ? "sugestão criada" : ""}
              {avaliacao.status === "ja_pendente" ? "já possuía uma sugestão pendente" : ""}
              {avaliacao.status === "falha" && (
                <>
                  {avaliacao.categoria === "guard_rail" ? "barrado pelo piso de custo" : "IA indisponível"}: {avaliacao.motivo}
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      {erro && <p className="erro">{erro}</p>}
      {carregando && <Skeleton />}

      {!carregando && sugestoes.length === 0 && !erro && (
        <p>Nenhuma sugestão pendente no momento. Clique em "Gerar sugestões agora" para rodar o motor de IA.</p>
      )}

      <ul className="promo-lista">
        {sugestoes.map((s) => {
          const aberta = abertas[s.id] === true;
          const prioridade = PRIORIDADE[s.prioridade];
          const detalhe = [s.produto_marca, s.produto_tamanho].filter(Boolean).join(" · ");
          return (
            <li key={s.id} className="promo-item">
              <div className="promo-linha">
                <button
                  type="button"
                  className="promo-toggle"
                  aria-expanded={aberta}
                  aria-controls={`promo-detalhes-${s.id}`}
                  onClick={() => setAbertas((atual) => ({ ...atual, [s.id]: !aberta }))}
                >
                  <Icone nome="chevron" className={aberta ? "girado" : undefined} />
                  <span className="promo-nome">
                    <strong>{s.produto_nome}</strong>
                    {detalhe && <small>{detalhe}</small>}
                  </span>
                </button>

                <div className="promo-preco-col">
                  <PromoPrice original={s.preco_normal} promo={s.preco_sugerido} />
                  <Badge tone="promo">−{formatPercent(s.percentual_desconto_sugerido, 0)}</Badge>
                </div>

                <p className="promo-motivo">{s.justificativa_ia}</p>

                <Badge tone={prioridade.tom}>{prioridade.rotulo}</Badge>

                <div className="promo-acoes">
                  <button type="button" onClick={() => avaliar(s.id, "aprovar")} disabled={avaliando === s.id}>
                    Aprovar
                  </button>
                  <button
                    type="button"
                    className="promo-rejeitar"
                    onClick={() => avaliar(s.id, "rejeitar")}
                    disabled={avaliando === s.id}
                  >
                    Rejeitar
                  </button>
                </div>
              </div>

              {aberta && (
                <div id={`promo-detalhes-${s.id}`} className="promo-detalhes">
                  <p className="promo-sinais">{resumoSinais(s.sinais_detectados)}</p>
                  <p className="promo-justificativa">"{s.justificativa_ia}"</p>

                  <label className="promo-observacao-campo">
                    Observação (opcional)
                    <textarea
                      value={observacoes[s.id] || ""}
                      onChange={(e) => setObservacoes((atual) => ({ ...atual, [s.id]: e.target.value }))}
                      className="promo-observacao"
                    />
                  </label>

                  <label className="promo-validade">
                    Validade em dias (opcional — padrão 1 dia)
                    <input
                      type="number"
                      min="0"
                      step="0.5"
                      placeholder="ex.: 3"
                      value={diasValidade[s.id] || ""}
                      onChange={(e) => setDiasValidade((atual) => ({ ...atual, [s.id]: e.target.value }))}
                    />
                  </label>
                </div>
              )}

              {erroPorSugestao[s.id] && <p className="promo-erro">{erroPorSugestao[s.id]}</p>}
            </li>
          );
        })}
      </ul>

      <h2>Promoções ativas</h2>
      {erroAtivas && <p className="erro">{erroAtivas}</p>}
      {ativas.length === 0 && !erroAtivas && <p>Nenhum produto em promoção no momento.</p>}
      <ul className="promo-lista">
        {ativas.map((p) => {
          const detalhe = [p.marca, p.tamanho].filter(Boolean).join(" · ");
          return (
            <li key={p.id} className="promo-item">
              <div className="promo-linha">
                <span className="promo-nome">
                  <strong>{p.nome}</strong>
                  {detalhe && <small>{detalhe}</small>}
                </span>
                <div className="promo-preco-col">
                  {p.preco_promocional && <PromoPrice original={p.preco_normal} promo={p.preco_promocional} />}
                </div>
                <p className="promo-motivo">
                  {p.promocao_expira_em ? `Até ${formatDateTime(p.promocao_expira_em)}` : "Sem data de término"}
                </p>
                <div className="promo-acoes">
                  <button
                    type="button"
                    className="promo-rejeitar"
                    onClick={() => finalizarPromocao(p.id)}
                    disabled={finalizando === p.id}
                  >
                    Finalizar promoção
                  </button>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
