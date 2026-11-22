import { useEffect, useState } from "react";
import { apiFetch } from "../../api/client";
import { PriceDelta } from "../../components/Preco";
import Skeleton from "../../components/Skeleton";
import { contar, formatBRL, formatDateTime } from "../../utils/format";

interface HistoricoItem {
  id: number;
  produto_id: number;
  produto_nome: string;
  preco_anterior: string;
  preco_novo: string;
  tipo_alteracao: "manual" | "promocao_ia_aprovada" | "fim_promocao";
  sugestao_id: number | null;
  criado_em: string;
}

const ROTULO_TIPO: Record<HistoricoItem["tipo_alteracao"], string> = {
  manual: "Manual",
  promocao_ia_aprovada: "Promoção IA aprovada",
  fim_promocao: "Fim de promoção",
};

type FiltroTipo = "todos" | "promocao" | "manual";

// "Promoção IA" cobre o ciclo da promocao: aprovacao e fim (volta ao preco de tabela).
function combinaTipo(item: HistoricoItem, filtro: FiltroTipo): boolean {
  if (filtro === "todos") return true;
  if (filtro === "manual") return item.tipo_alteracao === "manual";
  return item.tipo_alteracao !== "manual";
}

// Preco anterior == novo e a carga inicial do catalogo, nao uma mudanca.
function semVariacao(item: HistoricoItem): boolean {
  return Number(item.preco_anterior) === Number(item.preco_novo);
}

export default function HistoricoPrecos() {
  const [itens, setItens] = useState<HistoricoItem[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [tipo, setTipo] = useState<FiltroTipo>("todos");
  const [mostrarCargaInicial, setMostrarCargaInicial] = useState(false);

  useEffect(() => {
    apiFetch<HistoricoItem[]>("/historico-precos", { auth: true })
      .then(setItens)
      .catch(() => setErro("Não foi possível carregar o histórico de preços."))
      .finally(() => setCarregando(false));
  }, []);

  const ocultos = itens.filter(semVariacao).length;
  const visiveis = itens.filter(
    (item) => combinaTipo(item, tipo) && (mostrarCargaInicial || !semVariacao(item)),
  );

  return (
    <div className="page page-wide">
      <h1>Histórico de preços</h1>

      {carregando && <Skeleton />}
      {erro && <p className="erro">{erro}</p>}

      {!carregando && !erro && itens.length === 0 && <p>Nenhuma alteração de preço registrada ainda.</p>}

      {!carregando && !erro && itens.length > 0 && (
        <>
          <div className="produtos-filtros">
            <label className="filtro-campo" htmlFor="historico-tipo">
              Tipo
              <select id="historico-tipo" value={tipo} onChange={(e) => setTipo(e.target.value as FiltroTipo)}>
                <option value="todos">Todos</option>
                <option value="promocao">Promoção IA</option>
                <option value="manual">Manual</option>
              </select>
            </label>
            {ocultos > 0 && (
              <label className="checkbox-label" htmlFor="historico-carga-inicial">
                <input
                  id="historico-carga-inicial"
                  type="checkbox"
                  checked={mostrarCargaInicial}
                  onChange={(e) => setMostrarCargaInicial(e.target.checked)}
                />
                Mostrar carga inicial ({contar(ocultos, "registro", "registros")} sem variação)
              </label>
            )}
          </div>

          {visiveis.length === 0 ? (
            <p>Nenhum registro neste filtro.</p>
          ) : (
            <div className="tabela-wrapper">
              <table className="tabela-estoque">
                <thead>
                  <tr>
                    <th>Data</th>
                    <th>Produto</th>
                    <th>Tipo</th>
                    <th>Preço anterior</th>
                    <th>Preço novo</th>
                    <th>Variação</th>
                  </tr>
                </thead>
                <tbody>
                  {visiveis.map((item) => (
                    <tr key={item.id}>
                      <td>{formatDateTime(item.criado_em)}</td>
                      <td>{item.produto_nome}</td>
                      <td>{ROTULO_TIPO[item.tipo_alteracao]}</td>
                      <td>{formatBRL(item.preco_anterior)}</td>
                      <td>{formatBRL(item.preco_novo)}</td>
                      <td>
                        <PriceDelta from={item.preco_anterior} to={item.preco_novo} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
