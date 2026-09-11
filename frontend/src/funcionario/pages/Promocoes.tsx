import { useEffect, useState } from "react";
import { ApiError, apiFetch } from "../../api/client";

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

interface Falha {
  produto_id: number;
  nome: string;
  motivo: string;
  // "llm" = provedor não respondeu / resposta fora do formato.
  // "guard_rail" = respondeu, mas o preço feria o piso de custo.
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
        `Preço abaixo do piso de R$ ${detalhes.piso} ` +
        `(custo R$ ${detalhes.custo} + margem mínima de ${detalhes.margem_minima_percentual}%). ` +
        `Ajuste o custo em Produtos ou rejeite a sugestão.`
      );
    case "promocao_ja_ativa":
      return detalhes.expira_em
        ? `Este produto já está em promoção até ${new Date(String(detalhes.expira_em)).toLocaleString("pt-BR")}.`
        : "Este produto já está em promoção.";
    default:
      return mensagem;
  }
}

interface GerarResposta {
  candidatos_avaliados: number;
  sugestoes_criadas: Sugestao[];
  falhas: Falha[];
}

function resumoSinais(s: SinaisDetectados): string {
  const partes: string[] = [];
  partes.push(
    s.dias_sem_venda !== null
      ? `${s.dias_sem_venda} dia(s) sem venda`
      : `sem venda nos últimos ${s.janela_dias} dias`
  );
  if (s.dias_de_estoque_restante !== null) {
    partes.push(`estoque dura ~${Math.round(s.dias_de_estoque_restante)} dias no ritmo atual`);
  }
  if (s.margem !== null) {
    partes.push(`margem ~${(s.margem * 100).toFixed(0)}%`);
  }
  partes.push(`${s.proxima_data_sazonal} em ${s.dias_ate_data_sazonal}d`);
  return partes.join(" · ");
}

export default function Promocoes() {
  const [sugestoes, setSugestoes] = useState<Sugestao[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [gerando, setGerando] = useState(false);
  const [resumoGeracao, setResumoGeracao] = useState<GerarResposta | null>(null);
  const [observacoes, setObservacoes] = useState<Record<number, string>>({});
  const [horasValidade, setHorasValidade] = useState<Record<number, string>>({});
  const [avaliando, setAvaliando] = useState<number | null>(null);
  // Erro por sugestão (e não global): o guard-rail de preço recusa uma
  // sugestão específica, e a mensagem precisa aparecer no card dela.
  const [erroPorSugestao, setErroPorSugestao] = useState<Record<number, string>>({});

  function carregar() {
    setCarregando(true);
    setErro(null);
    apiFetch<Sugestao[]>("/promocoes?status_filtro=pendente", { auth: true })
      .then(setSugestoes)
      .catch(() => setErro("Não foi possível carregar as sugestões."))
      .finally(() => setCarregando(false));
  }

  useEffect(carregar, []);

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
      const horas = horasValidade[id]?.trim();
      await apiFetch(`/promocoes/${id}/${acao}`, {
        method: "POST",
        auth: true,
        body: JSON.stringify({
          observacao: observacoes[id] || undefined,
          ...(acao === "aprovar" && horas ? { horas_validade: Number(horas) } : {}),
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
          {resumoGeracao.candidatos_avaliados} candidato(s) avaliado(s), {resumoGeracao.sugestoes_criadas.length}{" "}
          sugestão(ões) nova(s)
          {resumoGeracao.falhas.length > 0 && <> — {resumoGeracao.falhas.length} não gerou sugestão</>}.
        </p>
      )}
      {resumoGeracao && resumoGeracao.falhas.length > 0 && (
        <ul className="promo-falhas">
          {resumoGeracao.falhas.map((f) => (
            <li key={f.produto_id}>
              <strong>{f.nome}</strong>
              {f.categoria === "guard_rail" ? " (barrado pelo piso de custo)" : " (IA indisponível)"}: {f.motivo}
            </li>
          ))}
        </ul>
      )}

      {erro && <p className="erro">{erro}</p>}
      {carregando && <p>Carregando...</p>}

      {!carregando && sugestoes.length === 0 && !erro && (
        <p>Nenhuma sugestão pendente no momento. Clique em "Gerar sugestões agora" para rodar o motor de IA.</p>
      )}

      <ul className="promo-lista">
        {sugestoes.map((s) => (
          <li key={s.id} className="promo-card">
            <div className="promo-card-header">
              <strong>{s.produto_nome}</strong>
              {s.produto_marca && <span className="promo-detalhe"> {s.produto_marca}</span>}
              {s.produto_tamanho && <span className="promo-detalhe"> · {s.produto_tamanho}</span>}
              <span className={`badge-prioridade badge-prioridade-${s.prioridade}`}>{s.prioridade}</span>
            </div>

            <p className="promo-sinais">{resumoSinais(s.sinais_detectados)}</p>

            <p className="promo-preco">
              R$ {s.preco_normal} → <strong>R$ {s.preco_sugerido}</strong> (
              {Number(s.percentual_desconto_sugerido).toFixed(0)}% off)
            </p>

            <p className="promo-justificativa">"{s.justificativa_ia}"</p>

            <textarea
              placeholder="Observação (opcional)"
              value={observacoes[s.id] || ""}
              onChange={(e) => setObservacoes((atual) => ({ ...atual, [s.id]: e.target.value }))}
              className="promo-observacao"
            />

            <label className="promo-validade">
              Validade (horas, opcional — padrão 14 dias)
              <input
                type="number"
                min="0"
                step="0.5"
                placeholder="ex.: 2"
                value={horasValidade[s.id] || ""}
                onChange={(e) => setHorasValidade((atual) => ({ ...atual, [s.id]: e.target.value }))}
              />
            </label>

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

            {erroPorSugestao[s.id] && <p className="promo-erro">{erroPorSugestao[s.id]}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}
