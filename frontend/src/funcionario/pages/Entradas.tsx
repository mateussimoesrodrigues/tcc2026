import { useEffect, useState, type FormEvent } from "react";
import { ApiError, apiFetch } from "../../api/client";
import Skeleton from "../../components/Skeleton";
import Badge from "../../components/Badge";
import Icone from "../../components/Icone";
import { contar, formatBRL, formatDateTime, formatNumber } from "../../utils/format";

/**
 * Entrada de mercadoria e sugestão de reposição na mesma tela, em três
 * modos.
 *
 * Reposição e entrada moram juntas de propósito: a ação natural depois de
 * ver "isso acaba em 5 dias" é registrar a compra, que é exatamente o
 * formulário ao lado. O botão "Comprar" leva o produto, a quantidade
 * sugerida e o último custo já preenchidos para o modo "nova" — senão a
 * lista de reposição seria um relatório sem saída.
 */

interface ProdutoResumo {
  id: number;
  nome: string;
  marca: string | null;
  tamanho: string | null;
  custo: string | null;
  estoque: { quantidade: number } | null;
}

interface ItemEntrada {
  produto_id: string;
  quantidade: string;
  custo_unitario: string;
}

interface EntradaRecente {
  id: number;
  produto_id: number;
  produto_nome: string;
  quantidade: number;
  custo_unitario: string | null;
  observacao: string | null;
  criado_em: string;
}

interface ItemResultado {
  produto_id: number;
  nome: string;
  quantidade: number;
  custo_anterior: string | null;
  custo_resultante: string;
  estoque_anterior: number;
  estoque_resultante: number;
  subtotal: string;
}

interface Resultado {
  itens: ItemResultado[];
  valor_total: string;
}

interface ItemReposicao {
  produto_id: number;
  nome: string;
  marca: string | null;
  estoque: number;
  giro_diario: number;
  dias_de_estoque_restante: number;
  situacao: "risco" | "ruptura";
  quantidade_sugerida: number;
  custo: string | null;
  custo_estimado_compra: string;
  custo_estimado: boolean;
  promocao_ativa: boolean;
}

interface Reposicao {
  dias_alerta: number;
  dias_cobertura: number;
  itens: ItemReposicao[];
  custo_total_estimado: string;
  produtos_sem_custo: number;
}

const ITEM_VAZIO: ItemEntrada = { produto_id: "", quantidade: "1", custo_unitario: "" };

// Entradas geradas pelo seed trazem "Estoque inicial DERIVADO (estimativa) - ...":
// na tela basta "Estoque inicial". O dado no banco nao e alterado.
function rotuloNota(observacao: string | null): string {
  if (!observacao) return "—";
  return /^estoque inicial/i.test(observacao.trim()) ? "Estoque inicial" : observacao;
}

const moeda = formatBRL;
const dataHora = formatDateTime;

export default function Entradas() {
  const [modo, setModo] = useState<"lista" | "nova" | "reposicao">("lista");

  const [produtos, setProdutos] = useState<ProdutoResumo[]>([]);
  const [recentes, setRecentes] = useState<EntradaRecente[]>([]);
  const [reposicao, setReposicao] = useState<Reposicao | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const [observacao, setObservacao] = useState("");
  const [itens, setItens] = useState<ItemEntrada[]>([ITEM_VAZIO]);
  const [salvando, setSalvando] = useState(false);
  const [erroForm, setErroForm] = useState<string | null>(null);
  const [resultado, setResultado] = useState<Resultado | null>(null);

  function carregar() {
    setCarregando(true);
    setErro(null);
    Promise.all([
      apiFetch<ProdutoResumo[]>("/produtos?somente_ativos=true", { auth: true }),
      apiFetch<EntradaRecente[]>("/estoque/entradas", { auth: true }),
      apiFetch<Reposicao>("/analytics/reposicao", { auth: true }),
    ])
      .then(([p, e, r]) => {
        setProdutos(p);
        setRecentes(e);
        setReposicao(r);
      })
      .catch(() => setErro("Não foi possível carregar as entradas."))
      .finally(() => setCarregando(false));
  }

  useEffect(carregar, []);

  function abrirNova(pre?: ItemEntrada) {
    setItens([pre ?? ITEM_VAZIO]);
    setObservacao("");
    setErroForm(null);
    setResultado(null);
    setModo("nova");
  }

  function comprar(item: ItemReposicao) {
    const produto = produtos.find((p) => p.id === item.produto_id);
    abrirNova({
      produto_id: String(item.produto_id),
      quantidade: String(item.quantidade_sugerida),
      // Só pré-preenche o custo se estiver cadastrado: repetir a estimativa
      // (metade do preço) como se fosse o valor pago corromperia a média
      // ponderada com um número que ninguém pagou.
      custo_unitario: produto?.custo ?? "",
    });
  }

  function atualizarItem(indice: number, campo: keyof ItemEntrada, valor: string) {
    setItens((atuais) => atuais.map((it, i) => (i === indice ? { ...it, [campo]: valor } : it)));
  }

  const total = itens.reduce((soma, it) => {
    const qtd = Number(it.quantidade);
    const custo = Number(it.custo_unitario);
    return soma + (Number.isFinite(qtd) && Number.isFinite(custo) ? qtd * custo : 0);
  }, 0);

  async function salvar(e: FormEvent) {
    e.preventDefault();
    setErroForm(null);

    const preenchidos = itens.filter((it) => it.produto_id && it.quantidade && it.custo_unitario);
    if (preenchidos.length === 0) {
      setErroForm("Preencha ao menos um item com produto, quantidade e custo.");
      return;
    }

    setSalvando(true);
    try {
      const corpo = await apiFetch<Resultado>("/estoque/entradas", {
        method: "POST",
        auth: true,
        body: JSON.stringify({
          observacao: observacao.trim() || null,
          itens: preenchidos.map((it) => ({
            produto_id: Number(it.produto_id),
            quantidade: Number(it.quantidade),
            custo_unitario: it.custo_unitario,
          })),
        }),
      });
      setResultado(corpo);
      carregar();
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setErroForm("Um dos produtos não foi encontrado. Nada foi lançado.");
      } else if (err instanceof ApiError && err.status === 422) {
        setErroForm("Quantidade precisa ser maior que zero e o custo não pode ser negativo.");
      } else {
        setErroForm("Não foi possível registrar a entrada.");
      }
    } finally {
      setSalvando(false);
    }
  }

  if (carregando) {
    return (
      <div className="page page-wide">
        <Skeleton />
      </div>
    );
  }

  // --- confirmação -------------------------------------------------------
  if (modo === "nova" && resultado) {
    return (
      <div className="page page-wide">
        <h1>Entrada registrada</h1>
        <p>
          Total da nota: <strong>{moeda(resultado.valor_total)}</strong>
        </p>

        <div className="tabela-wrapper">
          <table className="tabela-estoque">
            <thead>
              <tr>
                <th>Produto</th>
                <th>Qtd.</th>
                <th>Estoque</th>
                <th>Custo antes</th>
                <th>Custo agora</th>
              </tr>
            </thead>
            <tbody>
              {resultado.itens.map((item) => (
                <tr key={item.produto_id}>
                  <td>{item.nome}</td>
                  <td className="celula-mono">+{formatNumber(item.quantidade)}</td>
                  <td className="celula-mono">
                    {formatNumber(item.estoque_anterior)} <Icone nome="seta" titulo="para" />{" "}
                    {formatNumber(item.estoque_resultante)}
                  </td>
                  <td className="celula-mono">{item.custo_anterior ? moeda(item.custo_anterior) : "—"}</td>
                  <td className="celula-mono">{moeda(item.custo_resultante)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="indicadores-nota">
          O custo novo é a média ponderada entre o que já estava em estoque e o que acabou de entrar
          — é ele que define o piso de preço das promoções deste produto.
        </p>

        <div className="form-acoes">
          <button type="button" onClick={() => abrirNova()}>
            Registrar outra
          </button>
          <button type="button" className="link-button" onClick={() => setModo("lista")}>
            Voltar
          </button>
        </div>
      </div>
    );
  }

  // --- formulário --------------------------------------------------------
  if (modo === "nova") {
    return (
      <div className="page page-wide">
        <h1>Nova entrada</h1>
        <p>
          Registre o que chegou e quanto foi pago. O custo do produto é reancorado pela média
          ponderada com o estoque que já existia.
        </p>

        <form onSubmit={salvar} className="entrada-form">
          <label>
            Nota fiscal / fornecedor
            <input
              type="text"
              value={observacao}
              onChange={(e) => setObservacao(e.target.value)}
              placeholder="NF 1234 — Distribuidora Central"
              maxLength={255}
            />
          </label>

          <div className="entrada-itens">
            {itens.map((item, indice) => {
              const produto = produtos.find((p) => p.id === Number(item.produto_id));
              return (
                <div className="entrada-item" key={indice}>
                  <select
                    value={item.produto_id}
                    onChange={(e) => atualizarItem(indice, "produto_id", e.target.value)}
                    aria-label="Produto"
                  >
                    <option value="">Selecione o produto...</option>
                    {produtos.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.nome}
                        {p.marca ? ` — ${p.marca}` : ""}
                        {p.tamanho ? ` (${p.tamanho})` : ""}
                      </option>
                    ))}
                  </select>

                  <input
                    type="number"
                    min="1"
                    step="1"
                    value={item.quantidade}
                    onChange={(e) => atualizarItem(indice, "quantidade", e.target.value)}
                    aria-label="Quantidade"
                    placeholder="Qtd."
                  />

                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={item.custo_unitario}
                    onChange={(e) => atualizarItem(indice, "custo_unitario", e.target.value)}
                    aria-label="Custo unitário"
                    placeholder="Custo un."
                  />

                  <span className="entrada-item-subtotal">
                    {moeda(Number(item.quantidade) * Number(item.custo_unitario) || 0)}
                  </span>

                  <button
                    type="button"
                    className="link-button"
                    onClick={() => setItens((a) => a.filter((_, i) => i !== indice))}
                    disabled={itens.length === 1}
                  >
                    Remover
                  </button>

                  {produto && (
                    <span className="entrada-item-contexto">
                      em estoque: {formatNumber(produto.estoque?.quantidade ?? 0)} · custo atual:{" "}
                      {produto.custo ? moeda(produto.custo) : "não cadastrado"}
                    </span>
                  )}
                </div>
              );
            })}
          </div>

          <button type="button" className="link-button" onClick={() => setItens((a) => [...a, ITEM_VAZIO])}>
            + Adicionar item
          </button>

          <div className="entrada-total">
            <span>Total da nota</span>
            <strong>{moeda(total)}</strong>
          </div>

          {erroForm && <p className="erro">{erroForm}</p>}

          <div className="form-acoes">
            <button type="submit" disabled={salvando}>
              {salvando ? "Registrando..." : "Registrar entrada"}
            </button>
            <button type="button" className="link-button" onClick={() => setModo("lista")}>
              Cancelar
            </button>
          </div>
        </form>
      </div>
    );
  }

  // --- reposição ---------------------------------------------------------
  if (modo === "reposicao") {
    const itensReposicao = reposicao?.itens ?? [];
    return (
      <div className="page page-wide">
        <h1>Reposição sugerida</h1>
        <p>
          Produtos que acabam em até {contar(reposicao?.dias_alerta ?? 0, "dia", "dias")} no ritmo atual de
          venda, mais os que já romperam. A quantidade sugerida cobre{" "}
          {contar(reposicao?.dias_cobertura ?? 0, "dia", "dias")}.
        </p>

        {itensReposicao.length === 0 ? (
          <p className="grafico-vazio">Nenhum produto em risco de ruptura.</p>
        ) : (
          <>
            <div className="kpi-grid">
              <div className="kpi">
                <span className="kpi-rotulo">Produtos a repor</span>
                <span className="kpi-valor">{formatNumber(itensReposicao.length)}</span>
                <span className="kpi-apoio">
                  {itensReposicao.filter((i) => i.situacao === "ruptura").length} já sem estoque
                </span>
              </div>
              <div className="kpi">
                <span className="kpi-rotulo">Compra estimada</span>
                <span className="kpi-valor">{moeda(reposicao!.custo_total_estimado)}</span>
                <span className="kpi-apoio">
                  {reposicao!.produtos_sem_custo > 0
                    ? `${reposicao!.produtos_sem_custo} sem custo cadastrado (estimado)`
                    : "todos com custo cadastrado"}
                </span>
              </div>
            </div>

            <div className="tabela-wrapper">
              <table className="tabela-estoque">
                <thead>
                  <tr>
                    <th>Produto</th>
                    <th>Estoque</th>
                    <th>Giro/dia</th>
                    <th>Acaba em</th>
                    <th>Comprar</th>
                    <th>Custo estimado</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {itensReposicao.map((item) => (
                    <tr
                      key={item.produto_id}
                      className={item.situacao === "ruptura" ? "linha-baixa" : undefined}
                    >
                      <td>
                        {item.nome}
                        {item.marca && <span className="promo-detalhe"> {item.marca}</span>}
                        {item.promocao_ativa && (
                          <Badge
                            tone="promo"
                            title="Em promoção: o giro está acima do normal, então os dias restantes estão subestimados."
                          >
                            Promoção
                          </Badge>
                        )}
                      </td>
                      <td className="celula-mono">{formatNumber(item.estoque)}</td>
                      <td className="celula-mono">{formatNumber(item.giro_diario, 2)}</td>
                      <td className="celula-mono">
                        {item.situacao === "ruptura"
                          ? "sem estoque"
                          : contar(Math.round(item.dias_de_estoque_restante), "dia", "dias")}
                      </td>
                      <td className="celula-mono">{formatNumber(item.quantidade_sugerida)}</td>
                      <td className="celula-mono">
                        {moeda(item.custo_estimado_compra)}
                        {item.custo_estimado && "*"}
                      </td>
                      <td>
                        <button type="button" className="link-button" onClick={() => comprar(item)}>
                          Comprar
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {reposicao!.produtos_sem_custo > 0 && (
              <p className="indicadores-nota">
                * Custo estimado em metade do preço de venda — o produto não tem custo cadastrado.
                Registrar a entrada com o custo pago corrige isso.
              </p>
            )}
          </>
        )}

        <div className="form-acoes">
          <button type="button" className="link-button" onClick={() => setModo("lista")}>
            Voltar
          </button>
        </div>
      </div>
    );
  }

  // --- lista -------------------------------------------------------------
  const emRisco = reposicao?.itens.length ?? 0;

  return (
    <div className="page page-wide">
      <h1>Entradas de mercadoria</h1>
      <p>
        Cada recebimento registrado atualiza o estoque e o custo do produto. É o custo que define a
        margem e o piso de preço das promoções.
      </p>

      {erro && <p className="erro">{erro}</p>}

      <div className="entrada-acoes">
        <button type="button" className="produtos-novo-btn" onClick={() => abrirNova()}>
          + Nova entrada
        </button>
        <button type="button" className="link-button" onClick={() => setModo("reposicao")}>
          Ver reposição sugerida
          {emRisco > 0 && ` (${emRisco})`}
        </button>
      </div>

      {recentes.length === 0 ? (
        <p className="grafico-vazio">Nenhuma entrada registrada ainda.</p>
      ) : (
        <div className="tabela-wrapper">
          <table className="tabela-estoque">
            <thead>
              <tr>
                <th>Data</th>
                <th>Produto</th>
                <th>Qtd.</th>
                <th>Custo un.</th>
                <th>Nota / fornecedor</th>
              </tr>
            </thead>
            <tbody>
              {recentes.map((entrada) => (
                <tr key={entrada.id}>
                  <td className="celula-mono">{dataHora(entrada.criado_em)}</td>
                  <td>{entrada.produto_nome}</td>
                  <td className="celula-mono">+{formatNumber(entrada.quantidade)}</td>
                  <td className="celula-mono">
                    {entrada.custo_unitario ? moeda(entrada.custo_unitario) : "—"}
                  </td>
                  <td title={entrada.observacao ?? undefined}>{rotuloNota(entrada.observacao)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
