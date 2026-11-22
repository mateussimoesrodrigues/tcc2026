import { useCallback, useEffect, useState } from "react";
import { ApiError, apiFetch } from "../../api/client";
import Skeleton from "../../components/Skeleton";
import Badge from "../../components/Badge";
import { contar, formatBRL, formatNumber, formatPercentFracao } from "../../utils/format";

/**
 * Margem defasada: produtos vendidos abaixo da margem-alvo, normalmente
 * porque o custo subiu (entrada de mercadoria) e o preço não acompanhou.
 *
 * As margens aqui são sobre o PREÇO ((preço − custo) / preço), a mesma base
 * de `ai/rules.calcular_sinais` — não markup sobre o custo. É por isso que
 * o preço sugerido é `custo / (1 − alvo)`: com markup, a tela anunciaria um
 * alvo de 35% e entregaria 26%.
 */

interface ItemMargem {
  produto_id: number;
  nome: string;
  marca: string | null;
  tamanho: string | null;
  custo: string;
  preco_normal: string;
  margem_atual: number;
  preco_sugerido: string;
  margem_resultante: number;
  promocao_ativa: boolean;
}

interface Resposta {
  margem_alvo: number;
  itens: ItemMargem[];
  produtos_sem_custo: number;
  total_abaixo_do_alvo: number;
}

const moeda = formatBRL;
const pct = (fracao: number) => formatPercentFracao(fracao, 1);

export default function Precificacao() {
  const [alvo, setAlvo] = useState(35);
  const [dados, setDados] = useState<Resposta | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [aplicando, setAplicando] = useState<number | null>(null);
  const [erroPorProduto, setErroPorProduto] = useState<Record<number, string>>({});
  // Bumpado depois de aplicar um preço, para refazer a consulta sem
  // precisar de um `carregar` fora do efeito.
  const [versao, setVersao] = useState(0);

  // Digitar "45" no campo de alvo dispara duas buscas (4 e depois 45). Sem
  // o descarte abaixo, a resposta de "4" pode chegar depois da de "45" e
  // sobrescrever a tela com o resultado errado -- foi o que aconteceu na
  // primeira verificação desta tela.
  useEffect(() => {
    let descartado = false;

    setCarregando(true);
    setErro(null);
    apiFetch<Resposta>(`/precos/margem-defasada?margem_alvo=${alvo}`, { auth: true })
      .then((resposta) => {
        if (!descartado) setDados(resposta);
      })
      .catch(() => {
        if (!descartado) setErro("Não foi possível carregar as margens.");
      })
      .finally(() => {
        if (!descartado) setCarregando(false);
      });

    return () => {
      descartado = true;
    };
  }, [alvo, versao]);

  const recarregar = useCallback(() => setVersao((v) => v + 1), []);

  async function aplicar(item: ItemMargem) {
    setAplicando(item.produto_id);
    setErroPorProduto((atuais) => {
      const { [item.produto_id]: _, ...resto } = atuais;
      return resto;
    });
    try {
      await apiFetch(`/precos/${item.produto_id}/reprecificar`, {
        method: "POST",
        auth: true,
        body: JSON.stringify({ preco_novo: item.preco_sugerido }),
      });
      recarregar();
    } catch (err) {
      const mensagem =
        err instanceof ApiError && err.status === 409
          ? "Produto em promoção. Encerre a promoção antes de mudar o preço de tabela."
          : "Não foi possível aplicar o preço.";
      setErroPorProduto((atuais) => ({ ...atuais, [item.produto_id]: mensagem }));
    } finally {
      setAplicando(null);
    }
  }

  return (
    <div className="page page-wide">
      <h1>Margens e preços</h1>
      <p>
        Produtos cuja margem caiu abaixo do alvo. O preço sugerido devolve a margem, arredondado
        para terminar em <code>,90</code> e nunca abaixo do piso de custo.
      </p>

      <div className="margem-alvo-controle">
        <label>
          Margem-alvo (% sobre o preço)
          <input
            type="number"
            min="1"
            max="90"
            step="1"
            value={alvo}
            onChange={(e) => setAlvo(Number(e.target.value) || 1)}
          />
        </label>
      </div>

      {erro && <p className="erro">{erro}</p>}
      {carregando && <Skeleton />}

      {dados && !carregando && (
        <>
          <div className="kpi-grid">
            <div className="kpi">
              <span className="kpi-rotulo">Abaixo do alvo</span>
              <span className="kpi-valor">{formatNumber(dados.total_abaixo_do_alvo)}</span>
              <span className="kpi-apoio">produtos ativos com margem menor que {alvo}%</span>
            </div>
            <div className="kpi">
              <span className="kpi-rotulo">Vendidos no prejuízo</span>
              <span className="kpi-valor">{formatNumber(dados.itens.filter((i) => i.margem_atual < 0).length)}</span>
              <span className="kpi-apoio">preço de tabela abaixo do custo</span>
            </div>
            <div className="kpi">
              <span className="kpi-rotulo">Sem custo cadastrado</span>
              <span className="kpi-valor">{formatNumber(dados.produtos_sem_custo)}</span>
              <span className="kpi-apoio">ficam fora deste diagnóstico</span>
            </div>
          </div>

          {dados.itens.length === 0 ? (
            <p className="grafico-vazio">Nenhum produto abaixo da margem-alvo.</p>
          ) : (
            <div className="tabela-wrapper">
              <table className="tabela-estoque">
                <thead>
                  <tr>
                    <th>Produto</th>
                    <th>Custo</th>
                    <th>Preço atual</th>
                    <th>Margem</th>
                    <th>Preço sugerido</th>
                    <th>Margem depois</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {dados.itens.map((item) => (
                    <tr
                      key={item.produto_id}
                      className={item.margem_atual < 0 ? "linha-baixa" : undefined}
                    >
                      <td>
                        {item.nome}
                        {item.marca && <span className="promo-detalhe"> {item.marca}</span>}
                        {item.promocao_ativa && <Badge tone="promo">Promoção</Badge>}
                        {erroPorProduto[item.produto_id] && (
                          <p className="promo-erro">{erroPorProduto[item.produto_id]}</p>
                        )}
                      </td>
                      <td className="celula-mono">{moeda(item.custo)}</td>
                      <td className="celula-mono">{moeda(item.preco_normal)}</td>
                      <td
                        className={
                          item.margem_atual < 0 ? "variacao-negativa" : "celula-mono"
                        }
                      >
                        {pct(item.margem_atual)}
                      </td>
                      <td className="celula-mono preco-sugerido">{moeda(item.preco_sugerido)}</td>
                      <td className="variacao-positiva">{pct(item.margem_resultante)}</td>
                      <td>
                        <button
                          type="button"
                          className="link-button"
                          onClick={() => aplicar(item)}
                          disabled={item.promocao_ativa || aplicando === item.produto_id}
                          title={
                            item.promocao_ativa
                              ? "Produto em promoção: encerre a promoção antes de mudar o preço de tabela."
                              : undefined
                          }
                        >
                          {aplicando === item.produto_id ? "Aplicando..." : "Aplicar"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <p className="indicadores-nota">
            Aplicar o preço grava a alteração no histórico de preços com o autor. Produto em
            promoção fica bloqueado: mudar o preço de tabela sob uma promoção alteraria o desconto
            anunciado e distorceria a medição do efeito dela.
            {dados.produtos_sem_custo > 0 && (
              <>
                {" "}
                {contar(dados.produtos_sem_custo, "produto sem custo cadastrado não aparece", "produtos sem custo cadastrado não aparecem")} aqui —
                registrar a entrada de mercadoria com o custo pago resolve.
              </>
            )}
          </p>
        </>
      )}
    </div>
  );
}
