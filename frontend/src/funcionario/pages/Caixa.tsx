import { useEffect, useRef, useState } from "react";
import { ApiError, apiFetch } from "../../api/client";

interface PedidoItem {
  produto_id: number;
  nome_produto_snapshot: string;
  preco_unitario_snapshot: string;
  quantidade: number;
  subtotal: string;
}

interface PedidoDetalhe {
  id: number;
  numero_pedido: string;
  valor_total: string;
  status: "gerado" | "conferido_no_caixa" | "expirado";
  criado_em: string;
  expira_em: string;
  expirado: boolean;
  conferido_em: string | null;
  conferido_por_nome: string | null;
  itens: PedidoItem[];
}

interface ConferirResposta {
  pedido: PedidoDetalhe;
  estava_expirado: boolean;
}

const TAMANHO_NUMERO = 6;

function moeda(valor: string): string {
  return Number(valor).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function quandoLegivel(iso: string): string {
  return new Date(iso).toLocaleString("pt-BR");
}

export default function Caixa() {
  const [numero, setNumero] = useState("");
  const [pedido, setPedido] = useState<PedidoDetalhe | null>(null);
  const [buscando, setBuscando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [confirmado, setConfirmado] = useState<ConferirResposta | null>(null);
  const campoRef = useRef<HTMLInputElement>(null);

  // O caixa atende um cliente atrás do outro: o foco tem que voltar ao
  // campo sozinho depois de cada conferência, senão vira clique manual a
  // cada pedido.
  useEffect(() => {
    campoRef.current?.focus();
  }, [confirmado, pedido]);

  function limpar() {
    setNumero("");
    setPedido(null);
    setErro(null);
    setConfirmado(null);
  }

  async function buscar(e: React.FormEvent) {
    e.preventDefault();
    const alvo = numero.trim();
    if (alvo.length !== TAMANHO_NUMERO) {
      setErro(`O número do pedido tem ${TAMANHO_NUMERO} dígitos.`);
      return;
    }

    setBuscando(true);
    setErro(null);
    setPedido(null);
    setConfirmado(null);
    try {
      setPedido(await apiFetch<PedidoDetalhe>(`/pedidos/${alvo}`, { auth: true }));
    } catch (e) {
      setErro(
        e instanceof ApiError && e.status === 404
          ? "Pedido não encontrado — confira o número com o cliente."
          : "Não foi possível consultar o pedido."
      );
    } finally {
      setBuscando(false);
    }
  }

  async function confirmar() {
    if (!pedido) return;
    setConfirmando(true);
    setErro(null);
    try {
      const resposta = await apiFetch<ConferirResposta>(`/pedidos/${pedido.numero_pedido}/conferir`, {
        method: "POST",
        auth: true,
      });
      setConfirmado(resposta);
      setPedido(null);
      setNumero("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && typeof e.body === "object" && e.body !== null) {
        const detalhe = (e.body as { detail?: { detalhes?: Record<string, string | null> } }).detail;
        const quem = detalhe?.detalhes?.conferido_por_nome;
        const quando = detalhe?.detalhes?.conferido_em;
        setErro(
          `Este pedido já foi conferido${quando ? ` em ${quandoLegivel(quando)}` : ""}` +
            `${quem ? ` por ${quem}` : ""}.`
        );
      } else {
        setErro("Não foi possível confirmar a conferência.");
      }
    } finally {
      setConfirmando(false);
    }
  }

  return (
    <div className="page">
      <h1>Caixa — conferência de pedido</h1>
      <p>
        Digite o número de 6 dígitos que o cliente recebeu no checkout para ver os itens escaneados e
        confirmar a conferência.
      </p>

      <form onSubmit={buscar} className="caixa-busca">
        <input
          ref={campoRef}
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          maxLength={TAMANHO_NUMERO}
          placeholder="000000"
          value={numero}
          onChange={(e) => setNumero(e.target.value.replace(/\D/g, ""))}
          className="caixa-numero-input"
          aria-label="Número do pedido"
        />
        <button type="submit" disabled={buscando || numero.length !== TAMANHO_NUMERO}>
          {buscando ? "Buscando..." : "Buscar pedido"}
        </button>
        {(pedido || confirmado || erro) && (
          <button type="button" className="link-button" onClick={limpar}>
            Limpar
          </button>
        )}
      </form>

      {erro && <p className="erro">{erro}</p>}

      {confirmado && (
        <div className="caixa-confirmado">
          <strong>Pedido {confirmado.pedido.numero_pedido} conferido.</strong>
          <span>
            {moeda(confirmado.pedido.valor_total)} · {confirmado.pedido.itens.length} item(ns)
          </span>
          {confirmado.estava_expirado && (
            <span className="caixa-aviso-expirado">
              O prazo do pedido já tinha vencido — confira os itens com atenção extra.
            </span>
          )}
          <span className="caixa-proximo">Pronto para o próximo cliente.</span>
        </div>
      )}

      {pedido && (
        <div className="caixa-pedido">
          <div className="caixa-pedido-header">
            <span className="checkout-numero">{pedido.numero_pedido}</span>
            <span className={`badge-status badge-status-${pedido.status}`}>
              {pedido.status === "gerado" && "aguardando conferência"}
              {pedido.status === "conferido_no_caixa" && "já conferido"}
              {pedido.status === "expirado" && "prazo vencido"}
            </span>
          </div>

          <p className="caixa-detalhe">
            Gerado em {quandoLegivel(pedido.criado_em)}
            {pedido.expirado && pedido.status !== "conferido_no_caixa" && (
              <span className="caixa-aviso-expirado"> · prazo vencido, ainda pode ser conferido</span>
            )}
          </p>

          {pedido.status === "conferido_no_caixa" && (
            <p className="caixa-detalhe">
              Conferido em {pedido.conferido_em ? quandoLegivel(pedido.conferido_em) : "—"}
              {pedido.conferido_por_nome ? ` por ${pedido.conferido_por_nome}` : ""}.
            </p>
          )}

          <div className="tabela-wrapper">
            <table className="tabela-estoque">
              <thead>
                <tr>
                  <th>Produto</th>
                  <th>Qtd.</th>
                  <th>Preço un.</th>
                  <th>Subtotal</th>
                </tr>
              </thead>
              <tbody>
                {pedido.itens.map((item) => (
                  <tr key={item.produto_id}>
                    <td>{item.nome_produto_snapshot}</td>
                    <td>{item.quantidade}</td>
                    <td>{moeda(item.preco_unitario_snapshot)}</td>
                    <td>{moeda(item.subtotal)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="caixa-total">Total: {moeda(pedido.valor_total)}</p>

          {pedido.status !== "conferido_no_caixa" && (
            <button
              type="button"
              className="caixa-confirmar-btn"
              onClick={confirmar}
              disabled={confirmando}
            >
              {confirmando ? "Confirmando..." : "Confirmar conferência"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
