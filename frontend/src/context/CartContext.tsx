import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { ApiError, apiFetch, getCartSessionId, setCartSessionId } from "../api/client";

export interface CarrinhoItem {
  produto_id: number;
  nome: string;
  marca: string | null;
  tamanho: string | null;
  quantidade: number;
  preco_unitario_snapshot: string;
  subtotal: string;
}

export interface Pedido {
  numero_pedido: string;
  valor_total: string;
  expira_em: string;
}

interface CarrinhoResposta {
  itens: CarrinhoItem[];
  total: string;
}

interface CartContextValue {
  itens: CarrinhoItem[];
  total: string;
  carregando: boolean;
  erro: string | null;
  adicionarItem: (produtoId: number, quantidade?: number) => Promise<void>;
  atualizarQuantidade: (produtoId: number, quantidade: number) => Promise<void>;
  removerItem: (produtoId: number) => Promise<void>;
  recarregar: () => Promise<void>;
  finalizarCompra: () => Promise<Pedido>;
}

const CartContext = createContext<CartContextValue | undefined>(undefined);

export function CartProvider({ children }: { children: ReactNode }) {
  const [itens, setItens] = useState<CarrinhoItem[]>([]);
  const [total, setTotal] = useState("0.00");
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const aplicarResposta = useCallback((resposta: CarrinhoResposta) => {
    setItens(resposta.itens);
    setTotal(resposta.total);
  }, []);

  const abrirNovaSessao = useCallback(async () => {
    const sessao = await apiFetch<{ sessao_id: string }>("/carrinho/sessoes", { method: "POST" });
    setCartSessionId(sessao.sessao_id);
  }, []);

  // A sessao salva no localStorage pode ter expirado ou ja ter sido
  // finalizada por um checkout anterior -- nesses casos o backend responde
  // 404. Em vez de travar numa tela de erro permanente, abre uma sessao
  // nova (carrinho vazio) e tenta a operacao de novo.
  const comRecuperacaoDeSessao = useCallback(
    async <T,>(fn: () => Promise<T>): Promise<T> => {
      if (!getCartSessionId()) await abrirNovaSessao();
      try {
        return await fn();
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          await abrirNovaSessao();
          return await fn();
        }
        throw err;
      }
    },
    [abrirNovaSessao]
  );

  const recarregar = useCallback(async () => {
    await comRecuperacaoDeSessao(async () => {
      const resposta = await apiFetch<CarrinhoResposta>("/carrinho", { cartSession: true });
      aplicarResposta(resposta);
    });
  }, [aplicarResposta, comRecuperacaoDeSessao]);

  useEffect(() => {
    async function inicializar() {
      setCarregando(true);
      setErro(null);
      try {
        await recarregar();
      } catch {
        setErro("Não foi possível abrir o carrinho.");
      } finally {
        setCarregando(false);
      }
    }
    inicializar();
    // roda so uma vez, na montagem do provider (area do cliente inteira)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function adicionarItem(produtoId: number, quantidade = 1) {
    await comRecuperacaoDeSessao(async () => {
      const resposta = await apiFetch<CarrinhoResposta>("/carrinho/itens", {
        method: "POST",
        cartSession: true,
        body: JSON.stringify({ produto_id: produtoId, quantidade }),
      });
      aplicarResposta(resposta);
    });
  }

  async function atualizarQuantidade(produtoId: number, quantidade: number) {
    await comRecuperacaoDeSessao(async () => {
      const resposta = await apiFetch<CarrinhoResposta>(`/carrinho/itens/${produtoId}`, {
        method: "PUT",
        cartSession: true,
        body: JSON.stringify({ quantidade }),
      });
      aplicarResposta(resposta);
    });
  }

  async function removerItem(produtoId: number) {
    await comRecuperacaoDeSessao(async () => {
      const resposta = await apiFetch<CarrinhoResposta>(`/carrinho/itens/${produtoId}`, {
        method: "DELETE",
        cartSession: true,
      });
      aplicarResposta(resposta);
    });
  }

  async function finalizarCompra(): Promise<Pedido> {
    const pedido = await apiFetch<Pedido>("/checkout", { method: "POST", cartSession: true });
    setItens([]);
    setTotal("0.00");
    return pedido;
  }

  return (
    <CartContext.Provider
      value={{ itens, total, carregando, erro, adicionarItem, atualizarQuantidade, removerItem, recarregar, finalizarCompra }}
    >
      {children}
    </CartContext.Provider>
  );
}

export function useCart(): CartContextValue {
  const ctx = useContext(CartContext);
  if (!ctx) throw new Error("useCart precisa ser usado dentro de <CartProvider>");
  return ctx;
}
