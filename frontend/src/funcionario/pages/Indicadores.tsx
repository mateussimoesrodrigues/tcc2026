import { useEffect, useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import { BarrasSemana, GraficoArea, Rosca } from "../components/GraficosPainel";
import "./Indicadores.css";

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

interface ItemReposicao {
  produto_id: number;
  nome: string;
  marca: string | null;
  estoque: number;
  giro_diario: number;
  dias_de_estoque_restante: number;
  situacao: string;
  quantidade_sugerida: number;
  promocao_ativa: boolean;
}

interface Reposicao {
  dias_alerta: number;
  itens: ItemReposicao[];
  custo_total_estimado: string;
  produtos_sem_custo: number;
}

const PRESETS = [7, 15, 30, 90];
const DIAS_SEMANA = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];

function moeda(valor: string | number): string {
  return Number(valor).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function moedaCompacta(valor: number): string {
  if (valor === 0) return "R$ 0";
  return valor.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    notation: "compact",
    maximumFractionDigits: 1,
  });
}

function pct(valor: number | null | undefined, casas = 1): string {
  return valor == null ? "—" : `${valor.toFixed(casas).replace(".", ",")}%`;
}

function dataLocal(valor: Date): string {
  const ano = valor.getFullYear();
  const mes = String(valor.getMonth() + 1).padStart(2, "0");
  const dia = String(valor.getDate()).padStart(2, "0");
  return `${ano}-${mes}-${dia}`;
}

function paraData(data: string): Date {
  const [ano, mes, dia] = data.split("-").map(Number);
  return new Date(ano, mes - 1, dia);
}

function deslocarData(data: string, dias: number): string {
  const resultado = paraData(data);
  resultado.setDate(resultado.getDate() + dias);
  return dataLocal(resultado);
}

function saudacao(): string {
  const hora = new Date().getHours();
  return hora < 12 ? "Bom dia" : hora < 18 ? "Boa tarde" : "Boa noite";
}

function Cartao({
  titulo,
  subtitulo,
  acao,
  className = "",
  children,
}: {
  titulo: string;
  subtitulo?: string;
  acao?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`ind-card ${className}`}>
      <header className="ind-card-topo">
        <div>
          <h2>{titulo}</h2>
          {subtitulo && <p>{subtitulo}</p>}
        </div>
        {acao}
      </header>
      {children}
    </section>
  );
}

function Vazio({ children }: { children: ReactNode }) {
  return <p className="ind-vazio">{children}</p>;
}

function Kpi({
  rotulo,
  valor,
  apoio,
  icone,
}: {
  rotulo: string;
  valor: string;
  apoio: string;
  icone: ReactNode;
}) {
  return (
    <div className="ind-card ind-kpi">
      <span className="ind-kpi-icone">
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          {icone}
        </svg>
      </span>
      <span className="ind-kpi-rotulo">{rotulo}</span>
      <strong className="ind-kpi-valor">{valor}</strong>
      <span className="ind-kpi-apoio">{apoio}</span>
    </div>
  );
}

function IconeIA() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z" />
      <path d="M18.5 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z" />
    </svg>
  );
}

export default function Indicadores() {
  const { funcionario } = useAuth();
  const [dados, setDados] = useState<Resumo | null>(null);
  const [reposicao, setReposicao] = useState<Reposicao | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [erroFiltro, setErroFiltro] = useState<string | null>(null);
  const hoje = dataLocal(new Date());
  const [dataDesde, setDataDesde] = useState(() => deslocarData(hoje, -14));
  const [dataAte, setDataAte] = useState(hoje);
  const [filtroDesde, setFiltroDesde] = useState(() => deslocarData(hoje, -14));
  const [filtroAte, setFiltroAte] = useState(hoje);

  useEffect(() => {
    let ativo = true;
    setCarregando(true);
    setErro(null);
    apiFetch<Resumo>(`/analytics/resumo?data_desde=${filtroDesde}&data_ate=${filtroAte}`, { auth: true })
      .then((r) => ativo && setDados(r))
      .catch(() => ativo && setErro("Não foi possível carregar os indicadores."))
      .finally(() => ativo && setCarregando(false));
    return () => {
      ativo = false;
    };
  }, [filtroDesde, filtroAte]);

  // Reposicao independe do periodo (olha o ritmo recente de venda e o estoque
  // de hoje) e e opcional: se falhar, so o cartao dela mostra o aviso.
  const [erroReposicao, setErroReposicao] = useState(false);
  useEffect(() => {
    apiFetch<Reposicao>("/analytics/reposicao", { auth: true })
      .then(setReposicao)
      .catch(() => setErroReposicao(true));
  }, []);

  function aplicar(desde: string, ate: string) {
    if (desde > ate) {
      setErroFiltro("A data inicial não pode ser maior que a final.");
      return;
    }
    setErroFiltro(null);
    setDataDesde(desde);
    setDataAte(ate);
    setFiltroDesde(desde);
    setFiltroAte(ate);
  }

  const serieCompleta = useMemo(() => {
    if (!dados) return [];
    const porDia = new Map(dados.serie.map((p) => [p.periodo, p]));
    const pontos: PontoSerie[] = [];
    for (let dia = filtroDesde; dia <= filtroAte; dia = deslocarData(dia, 1)) {
      pontos.push(
        porDia.get(dia) ?? {
          periodo: dia,
          receita: "0",
          unidades: 0,
          pedidos: 0,
          margem_bruta: "0",
          margem_percentual: null,
          receita_sem_custo_cadastrado: "0",
        },
      );
    }
    return pontos;
  }, [dados, filtroDesde, filtroAte]);

  // Receita media por dia da semana (dias sem venda contam como zero, senao a
  // media so olharia os dias bons). Serve pra decidir escala e reposicao.
  const porDiaSemana = useMemo(() => {
    const soma = Array(7).fill(0);
    const ocorrencias = Array(7).fill(0);
    for (const p of serieCompleta) {
      const d = paraData(p.periodo).getDay();
      soma[d] += Number(p.receita);
      ocorrencias[d] += 1;
    }
    // Comeca na segunda: a semana de loja.
    return [1, 2, 3, 4, 5, 6, 0].map((d) => ({
      rotulo: DIAS_SEMANA[d],
      valor: ocorrencias[d] ? soma[d] / ocorrencias[d] : 0,
    }));
  }, [serieCompleta]);

  if (!dados) {
    return (
      <div className="page ind">
        {erro ? <p className="erro">{erro}</p> : <p className="ind-carregando">Carregando indicadores...</p>}
      </div>
    );
  }

  const { sugestoes, serie, produtos_parados: parados } = dados;

  const receitaTotal = Number(dados.receita_periodo);
  const margemTotal = Number(dados.margem_periodo);
  const margemPct = receitaTotal > 0 ? (margemTotal / receitaTotal) * 100 : null;
  const receitaSemCusto = serie.reduce((soma, p) => soma + Number(p.receita_sem_custo_cadastrado), 0);
  const fracaoSemCusto = receitaTotal > 0 ? (receitaSemCusto / receitaTotal) * 100 : 0;
  const melhorDia = porDiaSemana.reduce((a, b) => (b.valor > a.valor ? b : a), porDiaSemana[0]);

  const itensRepor = (reposicao?.itens ?? []).slice(0, 6);
  const totalParado = parados.reduce((s, p) => s + Number(p.valor_parado), 0);
  const topParados = parados.slice(0, 6);
  const maiorParado = Math.max(...topParados.map((p) => Number(p.valor_parado)), 1);

  const maiorDesconto = Math.max(
    Number(sugestoes.desconto_medio_sugerido ?? 0),
    Number(sugestoes.desconto_medio_aplicado ?? 0),
    Number(sugestoes.desconto_medio_rejeitado ?? 0),
    1,
  );
  const barrasDesconto = [
    { rotulo: "Sugerido pela IA", valor: sugestoes.desconto_medio_sugerido, cor: "var(--serie)" },
    { rotulo: "Aplicado de fato", valor: sugestoes.desconto_medio_aplicado, cor: "var(--promo)" },
    { rotulo: "Nas rejeitadas", valor: sugestoes.desconto_medio_rejeitado, cor: "var(--neutral)" },
  ];

  return (
    <div className={`page ind${carregando ? " ind-atualizando" : ""}`}>
      <div className="ind-cabecalho">
        <div>
          <h1>
            {saudacao()}
            {funcionario ? `, ${funcionario.nome.trim().split(/\s+/)[0]}` : ""}
          </h1>
          <p>
            Resumo da loja de {paraData(filtroDesde).toLocaleDateString("pt-BR")} a{" "}
            {paraData(filtroAte).toLocaleDateString("pt-BR")}.
          </p>
        </div>

        <form
          className="ind-filtros"
          onSubmit={(evento: FormEvent<HTMLFormElement>) => {
            evento.preventDefault();
            aplicar(dataDesde, dataAte);
          }}
        >
          <div className="ind-presets" role="group" aria-label="Períodos rápidos">
            {PRESETS.map((dias) => {
              const ativo = filtroAte === hoje && filtroDesde === deslocarData(hoje, -(dias - 1));
              return (
                <button
                  key={dias}
                  type="button"
                  className={ativo ? "ativo" : undefined}
                  aria-pressed={ativo}
                  onClick={() => aplicar(deslocarData(hoje, -(dias - 1)), hoje)}
                >
                  {dias}d
                </button>
              );
            })}
          </div>
          <label>
            <span>De</span>
            <input type="date" value={dataDesde} max={dataAte} onChange={(e) => setDataDesde(e.target.value)} />
          </label>
          <label>
            <span>Até</span>
            <input type="date" value={dataAte} min={dataDesde} onChange={(e) => setDataAte(e.target.value)} />
          </label>
          <button type="submit" className="ind-aplicar">
            Aplicar
          </button>
        </form>
      </div>
      {erroFiltro && <p className="erro ind-erro">{erroFiltro}</p>}
      {erro && <p className="erro ind-erro">{erro}</p>}

      <div className="ind-grade-painel">
        {/* --- Receita ------------------------------------------------- */}
        <Cartao
          className="ind-hero span-8"
          titulo="Receita por dia"
          subtitulo="Dias sem venda aparecem como zero."
          acao={
            <div className="ind-hero-total">
              <strong>{moeda(receitaTotal)}</strong>
              <span>
                margem {moeda(margemTotal)}
                {margemPct !== null && ` · ${pct(margemPct, 0)}`}
              </span>
            </div>
          }
        >
          <div className="ind-legenda">
            <span>
              <i style={{ background: "var(--serie)" }} /> Receita
            </span>
            <span>
              <i className="tracejado" /> Margem bruta
            </span>
          </div>
          <GraficoArea
            pontos={serieCompleta.map((p) => ({
              rotulo: p.periodo,
              valor: Number(p.receita),
              extra: Number(p.margem_bruta),
            }))}
            formatar={moeda}
            formatarEixo={moedaCompacta}
            nomeValor="Receita"
            nomeExtra="Margem"
          />
        </Cartao>

        {/* --- IA: decisoes -------------------------------------------- */}
        <Cartao
          className="ind-ia span-4"
          titulo="Sugestões da IA"
          subtitulo="O que a equipe decidiu"
          acao={
            <span className="ind-selo-ia">
              <IconeIA /> IA
            </span>
          }
        >
          {sugestoes.total === 0 ? (
            <Vazio>Nenhuma sugestão gerada ainda. Gere sugestões em Promoções.</Vazio>
          ) : (
            <div className="ind-ia-corpo">
              <Rosca
                centro={String(sugestoes.total)}
                legendaCentro="sugestões"
                fatias={[
                  { rotulo: "Aprovadas", valor: sugestoes.aprovadas, cor: "var(--serie)" },
                  { rotulo: "Rejeitadas", valor: sugestoes.rejeitadas, cor: "var(--danger)" },
                  { rotulo: "Pendentes", valor: sugestoes.pendentes, cor: "var(--promo)" },
                  { rotulo: "Expiradas", valor: sugestoes.expiradas, cor: "var(--border-strong)" },
                ]}
              />
              <ul className="ind-ia-legenda">
                <li>
                  <i style={{ background: "var(--serie)" }} />
                  Aprovadas <strong>{sugestoes.aprovadas}</strong>
                </li>
                <li>
                  <i style={{ background: "var(--danger)" }} />
                  Rejeitadas <strong>{sugestoes.rejeitadas}</strong>
                </li>
                <li>
                  <i style={{ background: "var(--promo)" }} />
                  Pendentes <strong>{sugestoes.pendentes}</strong>
                </li>
                <li>
                  <i style={{ background: "var(--border-strong)" }} />
                  Expiradas <strong>{sugestoes.expiradas}</strong>
                </li>
              </ul>
            </div>
          )}
          {sugestoes.total > 0 && (
            <div className="ind-taxa">
              <span>
                Taxa de aprovação
                <small>
                  só entre as {sugestoes.aprovadas + sugestoes.rejeitadas} já decididas
                </small>
              </span>
              <strong>{pct(sugestoes.taxa_aprovacao, 0)}</strong>
            </div>
          )}
          {sugestoes.pendentes > 0 && (
            <Link to="/promocoes" className="ind-chamada">
              {sugestoes.pendentes} sugest{sugestoes.pendentes === 1 ? "ão aguarda" : "ões aguardam"} decisão →
            </Link>
          )}
        </Cartao>

        {/* --- KPIs ---------------------------------------------------- */}
        <div className="span-12 ind-kpis">
          <Kpi
            rotulo="Margem bruta"
            valor={pct(margemPct)}
            apoio={`${moeda(margemTotal)} no período`}
            icone={<path d="M19 5L5 19M7.5 7.5h.01M16.5 16.5h.01" />}
          />
          <Kpi
            rotulo="Ticket médio"
            valor={dados.ticket_medio ? moeda(dados.ticket_medio) : "—"}
            apoio="por pedido"
            icone={<path d="M6 3h12v18l-3-2-3 2-3-2-3 2zM9.5 8h5M9.5 12h5" />}
          />
          <Kpi
            rotulo="Pedidos"
            valor={String(dados.pedidos_periodo)}
            apoio="no período"
            icone={<path d="M5 12.5l4.5 4.5L19 7.5" />}
          />
          <Kpi
            rotulo="Unidades vendidas"
            valor={String(dados.unidades_periodo)}
            apoio={`melhor dia: ${melhorDia.valor > 0 ? melhorDia.rotulo : "—"}`}
            icone={<path d="M3.5 7.5L12 3l8.5 4.5v9L12 21l-8.5-4.5zM3.5 7.5L12 12l8.5-4.5M12 12v9" />}
          />
        </div>
        {fracaoSemCusto > 0.5 && (
          <p className="ind-aviso span-12">
            {fracaoSemCusto.toFixed(0)}% da receita vem de produtos sem custo cadastrado — a margem está
            superestimada.
          </p>
        )}

        {/* --- Reposicao ----------------------------------------------- */}
        <Cartao
          className="span-7"
          titulo="Precisa repor"
          subtitulo={
            reposicao
              ? `Estoque que acaba em até ${reposicao.dias_alerta} dias no ritmo atual`
              : "Estoque que vai acabar no ritmo atual"
          }
          acao={
            <Link to="/entradas" className="ind-link">
              Ver tudo
            </Link>
          }
        >
          {erroReposicao ? (
            <Vazio>Não foi possível calcular a reposição agora.</Vazio>
          ) : !reposicao ? (
            <Vazio>Calculando...</Vazio>
          ) : itensRepor.length === 0 ? (
            <Vazio>Nenhum produto em risco de ruptura. 🎉</Vazio>
          ) : (
            <>
              <ul className="ind-lista">
                {itensRepor.map((i) => {
                  const ruptura = i.situacao === "ruptura";
                  const fracao = Math.min(i.dias_de_estoque_restante / reposicao.dias_alerta, 1);
                  return (
                    <li key={i.produto_id}>
                      <div className="ind-lista-linha">
                        <span className="ind-lista-nome">
                          {i.nome}
                          {i.marca && <small> · {i.marca}</small>}
                          {i.promocao_ativa && <span className="badge-em-andamento">em promoção</span>}
                        </span>
                        <span className={`ind-chip ${ruptura ? "perigo" : "alerta"}`}>
                          {ruptura ? "Sem estoque" : `${Math.max(Math.floor(i.dias_de_estoque_restante), 0)} dias`}
                        </span>
                      </div>
                      <div className="ind-trilho">
                        <div
                          className={`ind-preenche ${ruptura ? "perigo" : "alerta"}`}
                          style={{ width: ruptura ? "100%" : `${Math.max(fracao * 100, 4)}%` }}
                        />
                      </div>
                      <small className="ind-lista-detalhe">
                        {i.estoque} em estoque · vende {i.giro_diario.toFixed(1).replace(".", ",")}/dia · sugestão:
                        comprar {i.quantidade_sugerida}
                      </small>
                    </li>
                  );
                })}
              </ul>
              <p className="ind-rodape">
                {reposicao.itens.length} produto{reposicao.itens.length === 1 ? "" : "s"} · compra estimada{" "}
                <strong>{moeda(reposicao.custo_total_estimado)}</strong>
              </p>
            </>
          )}
        </Cartao>

        {/* --- Capital parado ------------------------------------------ */}
        <Cartao
          className="span-5"
          titulo="Capital parado"
          subtitulo="Produtos com estoque e sem giro, ordenados por valor"
          acao={
            totalParado > 0 ? (
              <div className="ind-hero-total">
                <strong>{moeda(totalParado)}</strong>
                <span>{parados.length} produtos</span>
              </div>
            ) : undefined
          }
        >
          {topParados.length === 0 ? (
            <Vazio>Nenhum produto parado no momento.</Vazio>
          ) : (
            <ul className="ind-lista">
              {topParados.map((p) => (
                <li key={p.produto_id}>
                  <div className="ind-lista-linha">
                    <span className="ind-lista-nome">
                      {p.nome}
                      {p.marca && <small> · {p.marca}</small>}
                      {p.promocao_ativa && <span className="badge-em-andamento">em promoção</span>}
                      {p.tem_sugestao_pendente && (
                        <span className="badge-em-andamento badge-pendente">sugestão pendente</span>
                      )}
                    </span>
                    <strong title={p.custo_estimado ? "Custo não cadastrado: estimado como metade do preço" : undefined}>
                      {moeda(p.valor_parado)}
                      {p.custo_estimado && "*"}
                    </strong>
                  </div>
                  <div className="ind-trilho">
                    <div
                      className="ind-preenche neutro"
                      style={{ width: `${Math.max((Number(p.valor_parado) / maiorParado) * 100, 3)}%` }}
                    />
                  </div>
                  <small className="ind-lista-detalhe">
                    {p.estoque} em estoque ·{" "}
                    {p.dias_sem_venda == null ? "nunca vendeu" : `sem venda há ${p.dias_sem_venda} dias`}
                  </small>
                </li>
              ))}
            </ul>
          )}
          {parados.some((p) => p.custo_estimado) && (
            <p className="ind-rodape">* custo não cadastrado — valor estimado como metade do preço.</p>
          )}
        </Cartao>

        {/* --- Dia da semana ------------------------------------------- */}
        <Cartao
          className="span-7"
          titulo="Dias mais fortes"
          subtitulo="Receita média por dia da semana no período"
        >
          {receitaTotal > 0 ? (
            <BarrasSemana dias={porDiaSemana} formatar={moedaCompacta} />
          ) : (
            <Vazio>Sem vendas no período.</Vazio>
          )}
        </Cartao>

        {/* --- IA: desconto e modelos ---------------------------------- */}
        <Cartao
          className="ind-ia span-5"
          titulo="Descontos da IA"
          subtitulo="Média sugerida, aplicada e rejeitada"
          acao={
            <span className="ind-selo-ia">
              <IconeIA /> IA
            </span>
          }
        >
          {sugestoes.total === 0 ? (
            <Vazio>Sem sugestões para analisar.</Vazio>
          ) : (
            <>
              <ul className="ind-lista compacta">
                {barrasDesconto.map((b) => (
                  <li key={b.rotulo}>
                    <div className="ind-lista-linha">
                      <span className="ind-lista-nome">{b.rotulo}</span>
                      <strong>{b.valor ? `${Number(b.valor).toFixed(1).replace(".", ",")}%` : "—"}</strong>
                    </div>
                    <div className="ind-trilho">
                      <div
                        className="ind-preenche"
                        style={{
                          width: `${b.valor ? (Number(b.valor) / maiorDesconto) * 100 : 0}%`,
                          background: b.cor,
                        }}
                      />
                    </div>
                  </li>
                ))}
              </ul>

            </>
          )}
        </Cartao>
      </div>
    </div>
  );
}
