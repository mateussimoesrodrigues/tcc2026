import { useNavigate } from "react-router-dom";
import { useCart } from "../../context/CartContext";

export default function Carrinho() {
  const { itens, total, carregando, erro, atualizarQuantidade, removerItem } = useCart();
  const navigate = useNavigate();

  if (carregando) return <div className="page">Carregando carrinho...</div>;

  return (
    <div className="page">
      <h1>Carrinho</h1>

      {erro && <p className="erro">{erro}</p>}

      {itens.length === 0 && !erro && (
        <p>
          Seu carrinho está vazio. <button type="button" className="link-button" onClick={() => navigate("/")}>Escanear um produto</button>
        </p>
      )}

      {itens.length > 0 && (
        <>
          <ul className="carrinho-lista">
            {itens.map((item) => (
              <li key={item.produto_id} className="carrinho-item">
                <div className="carrinho-item-info">
                  <strong>{item.nome}</strong>
                  {item.marca && <span className="carrinho-item-detalhe"> {item.marca}</span>}
                  {item.tamanho && <span className="carrinho-item-detalhe"> · {item.tamanho}</span>}
                  <div>R$ {item.preco_unitario_snapshot} cada</div>
                </div>
                <div className="carrinho-item-qtd">
                  <button
                    type="button"
                    onClick={() => atualizarQuantidade(item.produto_id, item.quantidade - 1)}
                    aria-label="Diminuir quantidade"
                  >
                    −
                  </button>
                  <span>{item.quantidade}</span>
                  <button
                    type="button"
                    onClick={() => atualizarQuantidade(item.produto_id, item.quantidade + 1)}
                    aria-label="Aumentar quantidade"
                  >
                    +
                  </button>
                </div>
                <div className="carrinho-item-subtotal">R$ {item.subtotal}</div>
                <button
                  type="button"
                  className="link-button carrinho-item-remover"
                  onClick={() => removerItem(item.produto_id)}
                >
                  Remover
                </button>
              </li>
            ))}
          </ul>

          <div className="carrinho-total">
            <span>Total</span>
            <strong>R$ {total}</strong>
          </div>

          <button type="button" onClick={() => navigate("/checkout")} className="carrinho-finalizar">
            Finalizar compra
          </button>
        </>
      )}
    </div>
  );
}
