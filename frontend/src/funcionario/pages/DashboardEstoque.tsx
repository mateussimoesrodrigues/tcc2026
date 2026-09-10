import { Fragment, useCallback, useEffect, useState, type FormEvent } from "react";
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

/**
 * O ajuste é sempre um delta (+3, −2), nunca o saldo final: o razão de
 * estoque registra movimento, e é dele que saem giro e dias sem venda. Se a
 * tela gravasse "agora são 8", o sistema não saberia se entraram 3 ou
 * saíram 2.
 */
const MOTIVOS_SAIDA = ["Quebra", "Perda", "Uso interno", "Erro de contagem"];

export default function DashboardEstoque() {
  const [linhas, setLinhas] = useState<LinhaEstoque[]>([]);
  const [somenteBaixo, setSomenteBaixo] = useState(false);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const [ajustando, setAjustando] = useState<number | null>(null);
  const [delta, setDelta] = useState("");
  const [motivo, setMotivo] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [erroAjuste, setErroAjuste] = useState<string | null>(null);

  const carregar = useCallback(() => {
    setCarregando(true);
    setErro(null);
    apiFetch<LinhaEstoque[]>(`/estoque${somenteBaixo ? "?somente_baixo=true" : ""}`, { auth: true })
      .then(setLinhas)
      .catch(() => setErro("Não foi possível carregar o estoque."))
      .finally(() => setCarregando(false));
  }, [somenteBaixo]);

  useEffect(carregar, [carregar]);

  function abrirAjuste(produtoId: number) {
    setAjustando(produtoId);
    setDelta("");
    setMotivo("");
    setErroAjuste(null);
  }

  async function salvarAjuste(e: FormEvent, produtoId: number) {
    e.preventDefault();
    const quantidade = Number(delta);
    if (!Number.isInteger(quantidade) || quantidade === 0) {
      setErroAjuste("Informe quanto entrou (+) ou saiu (−).");
      return;
    }

    setSalvando(true);
    setErroAjuste(null);
    try {
      await apiFetch(`/estoque/${produtoId}/ajuste`, {
        method: "POST",
        auth: true,
        body: JSON.stringify({
          quantidade,
          tipo: "ajuste",
          observacao: motivo.trim() || null,
        }),
      });
      setAjustando(null);
      carregar();
    } catch {
      setErroAjuste("Não foi possível registrar o ajuste.");
    } finally {
      setSalvando(false);
    }
  }

  const totalBaixo = linhas.filter((l) => l.estoque_baixo).length;

  return (
    <div className="page page-wide">
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
                <th></th>
              </tr>
            </thead>
            <tbody>
              {linhas.map((linha) => (
                <Fragment key={linha.produto_id}>
                  <tr className={linha.estoque_baixo ? "linha-baixa" : ""}>
                    <td>{linha.nome}</td>
                    <td>{linha.marca ?? "-"}</td>
                    <td>{linha.tamanho ?? "-"}</td>
                    <td className="celula-mono">{linha.quantidade}</td>
                    <td className="celula-mono">{linha.limite_aplicado}</td>
                    <td>{linha.estoque_baixo ? "⚠ baixo" : ""}</td>
                    <td>
                      <button
                        type="button"
                        className="link-button"
                        onClick={() =>
                          ajustando === linha.produto_id
                            ? setAjustando(null)
                            : abrirAjuste(linha.produto_id)
                        }
                      >
                        {ajustando === linha.produto_id ? "Cancelar" : "Ajustar"}
                      </button>
                    </td>
                  </tr>

                  {ajustando === linha.produto_id && (
                    <tr className="estoque-ajuste-linha">
                      <td colSpan={7}>
                        <form
                          className="estoque-ajuste-form"
                          onSubmit={(e) => salvarAjuste(e, linha.produto_id)}
                        >
                          <label>
                            Entrou (+) ou saiu (−)
                            <input
                              type="number"
                              step="1"
                              value={delta}
                              onChange={(e) => setDelta(e.target.value)}
                              placeholder="-2"
                              autoFocus
                            />
                          </label>

                          <label>
                            Motivo
                            <input
                              type="text"
                              list="motivos-ajuste"
                              value={motivo}
                              onChange={(e) => setMotivo(e.target.value)}
                              placeholder="Quebra, perda, contagem..."
                              maxLength={255}
                            />
                          </label>

                          <button type="submit" disabled={salvando}>
                            {salvando ? "Salvando..." : "Registrar ajuste"}
                          </button>

                          {erroAjuste && <p className="erro">{erroAjuste}</p>}
                        </form>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <datalist id="motivos-ajuste">
        {MOTIVOS_SAIDA.map((m) => (
          <option key={m} value={m} />
        ))}
      </datalist>

      <p className="indicadores-nota">
        Reposição de mercadoria não é ajuste: use <strong>Entradas</strong>, que também registra o
        custo pago e atualiza a margem do produto.
      </p>
    </div>
  );
}
