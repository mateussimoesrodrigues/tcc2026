import { useEffect, useState } from "react";
import { apiFetch } from "../../api/client";

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

export default function HistoricoPrecos() {
  const [itens, setItens] = useState<HistoricoItem[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<HistoricoItem[]>("/historico-precos", { auth: true })
      .then(setItens)
      .catch(() => setErro("Não foi possível carregar o histórico de preços."))
      .finally(() => setCarregando(false));
  }, []);

  return (
    <div className="page page-wide">
      <h1>Histórico de preços</h1>

      {carregando && <p>Carregando...</p>}
      {erro && <p className="erro">{erro}</p>}

      {!carregando && !erro && itens.length === 0 && <p>Nenhuma alteração de preço registrada ainda.</p>}

      {!carregando && !erro && itens.length > 0 && (
        <div className="tabela-wrapper">
          <table className="tabela-estoque">
            <thead>
              <tr>
                <th>Data</th>
                <th>Produto</th>
                <th>Tipo</th>
                <th>Preço anterior</th>
                <th>Preço novo</th>
              </tr>
            </thead>
            <tbody>
              {itens.map((item) => (
                <tr key={item.id}>
                  <td>{new Date(item.criado_em).toLocaleString("pt-BR")}</td>
                  <td>{item.produto_nome}</td>
                  <td>{ROTULO_TIPO[item.tipo_alteracao]}</td>
                  <td>R$ {item.preco_anterior}</td>
                  <td>R$ {item.preco_novo}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
