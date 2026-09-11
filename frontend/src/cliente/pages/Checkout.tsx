import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../../api/client";
import { useCart, type Pedido } from "../../context/CartContext";

interface ItemEstoqueInsuficiente {
  produto_id: number;
  nome: string;
  solicitado: number;
  disponivel: number;
}

type Estado =
  | { fase: "processando" }
  | { fase: "sucesso"; pedido: Pedido }
  | { fase: "estoque_insuficiente"; itens: ItemEstoqueInsuficiente[] }
  | { fase: "erro"; mensagem: string };

export default function Checkout() {
  const { itens, total, finalizarCompra, recarregar } = useCart();
  const navigate = useNavigate();
  const [estado, setEstado] = useState<Estado>({ fase: "processando" });

  useEffect(() => {
    if (itens.length === 0) {
      navigate("/cliente/carrinho", { replace: true });
      return;
    }

    let cancelado = false;
    finalizarCompra()
      .then((pedido) => {
        if (!cancelado) setEstado({ fase: "sucesso", pedido });
      })
      .catch((err) => {
        if (cancelado) return;
        if (err instanceof ApiError && err.status === 409) {
          const corpo = err.body as { detail?: { itens?: ItemEstoqueInsuficiente[] } };
          setEstado({ fase: "estoque_insuficiente", itens: corpo.detail?.itens ?? [] });
        } else {
          setEstado({ fase: "erro", mensagem: "Não foi possível finalizar a compra." });
        }
      });

    return () => {
      cancelado = true;
    };
    // executa uma unica vez, ao montar (o carrinho so existe nesse momento)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (estado.fase === "processando") {
    return (
      <div className="page">
        <h1>Finalizar compra</h1>
        <p>Confirmando pedido...</p>
      </div>
    );
  }

  if (estado.fase === "sucesso") {
    return (
      <div className="page">
        <h1>Pedido confirmado</h1>
        <div className="checkout-numero">{estado.pedido.numero_pedido}</div>
        <p>Total: R$ {estado.pedido.valor_total}</p>
        <p>
          Leve este número até o caixa físico para conferência e pagamento. Ele expira em{" "}
          {new Date(estado.pedido.expira_em).toLocaleTimeString()}.
        </p>
        <button type="button" onClick={() => navigate("/cliente")}>Escanear novo produto</button>
      </div>
    );
  }

  if (estado.fase === "estoque_insuficiente") {
    return (
      <div className="page">
        <h1>Finalizar compra</h1>
        <p className="erro">Alguns itens não têm estoque suficiente no momento:</p>
        <ul>
          {estado.itens.map((item) => (
            <li key={item.produto_id}>
              {item.nome}: pedido {item.solicitado}, disponível {item.disponivel}
            </li>
          ))}
        </ul>
        <p>Ajuste as quantidades no carrinho e tente novamente.</p>
        <button
          type="button"
          onClick={() => {
            recarregar();
            navigate("/cliente/carrinho");
          }}
        >
          Voltar ao carrinho
        </button>
      </div>
    );
  }

  return (
    <div className="page">
      <h1>Finalizar compra</h1>
      <p className="erro">{estado.mensagem}</p>
      <p>Total do carrinho: R$ {total}</p>
      <button type="button" onClick={() => navigate("/cliente/carrinho")}>Voltar ao carrinho</button>
    </div>
  );
}
