import { useEffect, useState } from "react";
import { apiFetch } from "../../api/client";

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
  const [avaliando, setAvaliando] = useState<number | null>(null);

  function carregar() {
    setCarregando(true);
    setErro(null);
    apiFetch<Sugestao[]>("/promocoes?status_filtro=pendente", { auth: true })
      .then(setSugestoes)
      .catch(() => setErro("Não foi possível carregar as sugestões."))
      .finally(() => setCarregando(false));
  }

  useEffect(carregar, []);

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
    try {
      await apiFetch(`/promocoes/${id}/${acao}`, {
        method: "POST",
        auth: true,
        body: JSON.stringify({ observacao: observacoes[id] || undefined }),
      });
      setSugestoes((atual) => atual.filter((s) => s.id !== id));
    } catch {
      setErro(`Não foi possível ${acao === "aprovar" ? "aprovar" : "rejeitar"} a sugestão.`);
    } finally {
      setAvaliando(null);
    }
  }

  return (
    <div className="page page-wide">
      <h1>Sugestões de promoção (IA)</h1>
      <p>
        Regras determinísticas identificam produtos parados/com estoque em excesso; um LLM gratuito
        sugere o desconto e a justificativa. Nada muda o preço até você aprovar.
      </p>

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
          {resumoGeracao.falhas.length > 0 && (
            <> — {resumoGeracao.falhas.length} falharam (IA indisponível ou resposta inválida)</>
          )}
          .
        </p>
      )}
      {resumoGeracao && resumoGeracao.falhas.length > 0 && (
        <ul className="promo-falhas">
          {resumoGeracao.falhas.map((f) => (
            <li key={f.produto_id}>
              {f.nome}: {f.motivo}
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
            <p className="promo-modelo">gerado por {s.modelo_ia_usado}</p>

            <textarea
              placeholder="Observação (opcional)"
              value={observacoes[s.id] || ""}
              onChange={(e) => setObservacoes((atual) => ({ ...atual, [s.id]: e.target.value }))}
              className="promo-observacao"
            />

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
          </li>
        ))}
      </ul>
    </div>
  );
}
