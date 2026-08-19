import { useEffect, useState } from "react";
import { apiFetch } from "../../api/client";

interface LinhaEstoque {
  produto_id: number;
  nome: string;
  marca: string | null;
  tamanho: string | null;
  quantidade: number;
  quantidade_minima: number | null;
  limite_aplicado: number;
  estoque_baixo: boolean;
}

export default function DashboardEstoque() {
  const [linhas, setLinhas] = useState<LinhaEstoque[]>([]);
  const [somenteBaixo, setSomenteBaixo] = useState(false);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    setCarregando(true);
    setErro(null);
    apiFetch<LinhaEstoque[]>(`/estoque${somenteBaixo ? "?somente_baixo=true" : ""}`, { auth: true })
      .then(setLinhas)
      .catch(() => setErro("Não foi possível carregar o estoque."))
      .finally(() => setCarregando(false));
  }, [somenteBaixo]);

  const totalBaixo = linhas.filter((l) => l.estoque_baixo).length;

  return (
    <div className="page">
      <h1>Dashboard de estoque</h1>

      <p className={totalBaixo > 0 ? "alerta" : ""}>
        {totalBaixo > 0
          ? `⚠ ${totalBaixo} produto(s) com estoque baixo.`
          : "Nenhum produto com estoque baixo no momento."}
      </p>

      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={somenteBaixo}
          onChange={(e) => setSomenteBaixo(e.target.checked)}
        />
        Mostrar só estoque baixo
      </label>

      {carregando && <p>Carregando...</p>}
      {erro && <p className="erro">{erro}</p>}

      {!carregando && !erro && (
        <div className="tabela-wrapper">
          <table className="tabela-estoque">
            <thead>
              <tr>
                <th>Produto</th>
                <th>Marca</th>
                <th>Tamanho</th>
                <th>Qtd.</th>
                <th>Limite</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {linhas.map((linha) => (
                <tr key={linha.produto_id} className={linha.estoque_baixo ? "linha-baixa" : ""}>
                  <td>{linha.nome}</td>
                  <td>{linha.marca ?? "-"}</td>
                  <td>{linha.tamanho ?? "-"}</td>
                  <td>{linha.quantidade}</td>
                  <td>{linha.limite_aplicado}</td>
                  <td>{linha.estoque_baixo ? "⚠ baixo" : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
