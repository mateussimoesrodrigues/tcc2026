import { useEffect, useState } from "react";
import { apiFetch } from "../../api/client";
import GraficoBarras from "../components/GraficoBarras";
import GraficoLinha from "../components/GraficoLinha";

interface MetricasPorModelo {
  modelo: string;
  total: number;
  aprovadas: number;
  rejeitadas: number;
  pendentes: number;
  taxa_aprovacao: number | null;
  desconto_medio_sugerido: string | null;
}

interface MetricasSugestoes {
  total: number;
  aprovadas: number;
  rejeitadas: number;
  pendentes: number;
  expiradas: number;
  taxa_aprovacao: number | null;
  taxa_rejeicao: number | null;
  desconto_medio_sugerido: string | null;
  desconto_medio_aprovado: string | null;
  desconto_medio_rejeitado: string | null;
  desconto_medio_aplicado: string | null;
  tempo_medio_decisao_minutos: number | null;
  tempo_mediano_decisao_minutos: number | null;
  por_modelo: MetricasPorModelo[];
}

interface PromocaoEfeito {
  sugestao_id: number | null;
  produto_id: number;
  produto_nome: string;
  produto_marca: string | null;
  preco_anterior: string;
  preco_promocional: string;
  desconto_percentual: string;
  inicio_em: string;
  fim_em: string | null;
  em_andamento: boolean;
  duracao_dias: number;
  unidades_antes: number;
  unidades_depois: number;
  unidades_dia_antes: number;
  unidades_dia_depois: number;
  variacao_unidades_percentual: number | null;
  variacao_receita_percentual: number | null;
  margem_unitaria_promocional: string | null;
  observacao: string;
}

interface PontoSerie {
  periodo: string;
  receita: string;
  unidades: number;
  pedidos: number;
  margem_bruta: string;
  margem_percentual: number | null;
  receita_sem_custo_cadastrado: string;
}

interface ProdutoParado {
  produto_id: number;
  nome: string;
  marca: string | null;
  estoque: number;
  dias_sem_venda: number | null;
  preco_normal: string;
  valor_parado: string;
  custo_estimado: boolean;
  promocao_ativa: boolean;
  tem_sugestao_pendente: boolean;
}

interface Resumo {
  gerado_em: string;
  janela_dias: number;
  dados_simulados: boolean;
  receita_periodo: string;
  margem_periodo: string;
  unidades_periodo: number;
  pedidos_periodo: number;
  ticket_medio: string | null;
  pedidos_nao_confirmados: number;
  sugestoes: MetricasSugestoes;
  serie: PontoSerie[];
  promocoes: PromocaoEfeito[];
  produtos_parados: ProdutoParado[];
}

function moeda(valor: string | number): string {
  return Number(valor).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function pct(valor: number | null | undefined, casas = 1): string {
  return valor == null ? "—" : `${valor.toFixed(casas)}%`;
}

function duracaoLegivel(minutos: number | null): string {
  if (minutos == null) return "—";
  if (minutos < 60) return `${Math.round(minutos)} min`;
  const horas = minutos / 60;
  return horas < 48 ? `${horas.toFixed(1)} h` : `${(horas / 24).toFixed(1)} dias`;
}

function Kpi({ rotulo, valor, apoio }: { rotulo: string; valor: string; apoio?: string }) {
  return (
    <div className="kpi">
      <span className="kpi-rotulo">{rotulo}</span>
      <strong className="kpi-valor">{valor}</strong>
      {apoio && <span className="kpi-apoio">{apoio}</span>}
    </div>
  );
}

export default function Indicadores() {
  const [dados, setDados] = useState<Resumo | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<Resumo>("/analytics/resumo", { auth: true })
      .then(setDados)
      .catch(() => setErro("Não foi possível carregar os indicadores."))
      .finally(() => setCarregando(false));
  }, []);

  if (carregando) return <div className="page page-wide"><p>Carregando indicadores...</p></div>;
  if (erro) return <div className="page page-wide"><p className="erro">{erro}</p></div>;
  if (!dados) return null;

  const { sugestoes, serie, promocoes, produtos_parados: parados } = dados;

  const receitaSemCusto = serie.reduce((soma, p) => soma + Number(p.receita_sem_custo_cadastrado), 0);
  const receitaTotal = Number(dados.receita_periodo);
  const fracaoSemCusto = receitaTotal > 0 ? (receitaSemCusto / receitaTotal) * 100 : 0;

  // Só promoções com base de comparação entram no gráfico: sem venda antes,
  // a barra "antes" seria zero e a comparação não diria nada.
  const promocoesComparaveis = promocoes.filter((p) => p.variacao_unidades_percentual !== null).slice(0, 12);

  return (
    <div className="page page-wide">
      <h1>Indicadores</h1>




      <div className="kpi-grid">
        <Kpi
          rotulo="Taxa de aprovação da IA"
          valor={pct(sugestoes.taxa_aprovacao)}
          apoio={`${sugestoes.aprovadas} aprovadas de ${sugestoes.aprovadas + sugestoes.rejeitadas} decididas`}
        />
        <Kpi
          rotulo="Desconto sugerido → aplicado"
          valor={`${sugestoes.desconto_medio_sugerido ?? "—"}% → ${sugestoes.desconto_medio_aplicado ?? "—"}%`}
          apoio={`rejeitadas pediam ${sugestoes.desconto_medio_rejeitado ?? "—"}%`}
        />
        <Kpi
          rotulo="Tempo até a decisão"
          valor={duracaoLegivel(sugestoes.tempo_mediano_decisao_minutos)}
          apoio={`mediana · média ${duracaoLegivel(sugestoes.tempo_medio_decisao_minutos)}`}
        />
        <Kpi
          rotulo={`Receita (${dados.janela_dias} dias)`}
          valor={moeda(dados.receita_periodo)}
          apoio={`margem ${moeda(dados.margem_periodo)} · ticket ${dados.ticket_medio ? moeda(dados.ticket_medio) : "—"}`}
        />
      </div>

      <p className="indicadores-nota">
        Só entram pedidos conferidos no caixa ({dados.pedidos_periodo} no período).
        {dados.pedidos_nao_confirmados > 0 && (
          <> {dados.pedidos_nao_confirmados} pedido(s) ainda não conferido(s) ficam de fora da receita.</>
        )}
        {fracaoSemCusto > 0.5 && (
          <> {fracaoSemCusto.toFixed(0)}% da receita vem de produtos sem custo cadastrado — a margem acima
          está superestimada.</>
        )}
      </p>

      <h2>Receita por dia</h2>
      <GraficoLinha
        pontos={serie.map((p) => ({ rotulo: p.periodo, valor: Number(p.receita) }))}
        formatar={(v) => `R$${Math.round(v)}`}
      />

      <h2>Efeito das promoções</h2>
      <p className="indicadores-nota">{promocoes[0]?.observacao}</p>

      <GraficoBarras
        grupos={promocoesComparaveis.map((p) => ({
          rotulo: p.produto_nome,
          antes: p.unidades_dia_antes,
          depois: p.unidades_dia_depois,
        }))}
        titulo="Unidades vendidas por dia, antes e durante a promoção"
      />

      <div className="tabela-wrapper">
        <table className="tabela-estoque">
          <thead>
            <tr>
              <th>Produto</th>
              <th>Desconto</th>
              <th>Janela</th>
              <th>Un./dia antes</th>
              <th>Un./dia durante</th>
              <th>Variação</th>
            </tr>
          </thead>
          <tbody>
            {promocoes.map((p, i) => (
              <tr key={`${p.produto_id}-${p.inicio_em}-${i}`}>
                <td>
                  {p.produto_nome}
                  {p.produto_marca && <span className="promo-detalhe"> · {p.produto_marca}</span>}
                </td>
                <td>{Number(p.desconto_percentual).toFixed(1)}%</td>
                <td>
                  {p.duracao_dias.toFixed(0)} dias
                  {p.em_andamento && <span className="badge-em-andamento">em andamento</span>}
                </td>
                <td>{p.unidades_dia_antes.toFixed(2)}</td>
                <td>{p.unidades_dia_depois.toFixed(2)}</td>
                <td
                  className={
                    p.variacao_unidades_percentual == null
                      ? undefined
                      : p.variacao_unidades_percentual >= 0
                        ? "variacao-positiva"
                        : "variacao-negativa"
                  }
                >
                  {p.variacao_unidades_percentual == null
                    ? "sem base"
                    : `${p.variacao_unidades_percentual > 0 ? "+" : ""}${p.variacao_unidades_percentual.toFixed(0)}%`}
                </td>
              </tr>
            ))}
            {promocoes.length === 0 && (
              <tr>
                <td colSpan={6}>Nenhuma promoção aprovada ainda.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <br></br>

      <h2>Capital parado</h2>
      <div className="tabela-wrapper">
        <table className="tabela-estoque">
          <thead>
            <tr>
              <th>Produto</th>
              <th>Estoque</th>
              <th>Sem venda há</th>
              <th>Valor parado</th>
              <th>Situação</th>
            </tr>
          </thead>
          <tbody>
            {parados.map((p) => (
              <tr key={p.produto_id}>
                <td>
                  {p.nome}
                  {p.marca && <span className="promo-detalhe"> · {p.marca}</span>}
                </td>
                <td>{p.estoque}</td>
                <td>{p.dias_sem_venda == null ? "nunca vendeu" : `${p.dias_sem_venda} dias`}</td>
                <td>
                  {moeda(p.valor_parado)}
                  {p.custo_estimado && <span className="promo-detalhe" title="Custo não cadastrado: estimado como metade do preço"> *</span>}
                </td>
                <td>
                  {p.promocao_ativa && <span className="badge-em-andamento">em promoção</span>}
                  {p.tem_sugestao_pendente && <span className="badge-em-andamento">sugestão pendente</span>}
                </td>
              </tr>
            ))}
            {parados.length === 0 && (
              <tr>
                <td colSpan={5}>Nenhum produto parado no momento.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {parados.some((p) => p.custo_estimado) && (
        <p className="indicadores-nota">* custo não cadastrado — valor parado estimado como metade do preço.</p>
      )}
    </div>
  );
}
