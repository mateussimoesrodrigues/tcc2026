import { useEffect, useState, type FormEvent } from "react";
import { apiFetch } from "../../api/client";
import Icone from "../../components/Icone";
import Skeleton from "../../components/Skeleton";
import { contar, formatDateTime, formatNumber, parseInstante } from "../../utils/format";

// Painel de gestao dos displays fisicos de prateleira (etiquetas
// eletronicas). O token de cada dispositivo so aparece uma vez, na
// resposta de criacao/regeneracao -- precisa ser copiado pro firmware na
// hora (ver docs/displays-fisicos.md). Depois disso o backend so guarda o
// hash... na verdade guarda o token em claro (nao e senha de pessoa, e
// segredo de maquina), mas mesmo assim so devolve no momento em que e
// gerado, pra nao virar habito reexibir.

interface Produto {
  id: number;
  nome: string;
  marca: string | null;
}

interface Display {
  id: number;
  nome: string;
  produto_id: number | null;
  ativo: boolean;
  mac_reportado: string | null;
  bateria_pct: number | null;
  rssi_dbm: number | null;
  ultima_sincronizacao_em: string | null;
}

interface FormDisplay {
  nome: string;
  produto_id: string;
  ativo: boolean;
}

const FORM_VAZIO: FormDisplay = { nome: "", produto_id: "", ativo: true };

// Considera "atrasado" um display que nunca sincronizou ou que ficou mais
// de 3x o intervalo padrao (5 min, ver DISPLAY_SYNC_INTERVALO_SEGUNDOS no
// backend) sem falar com a API -- sinal de que ele esta desligado, sem
// wifi ou com a bateria acabada.
const LIMITE_ATRASO_MINUTOS = 15;

function estaAtrasado(d: Display): boolean {
  if (!d.ativo) return false;
  if (!d.ultima_sincronizacao_em) return true;
  // parseInstante: o backend manda datetime sem fuso (UTC); new Date(str)
  // leria como horario local e deslocaria o calculo em 3 h.
  const minutosDesdeSync = (Date.now() - parseInstante(d.ultima_sincronizacao_em).getTime()) / 60000;
  return minutosDesdeSync > LIMITE_ATRASO_MINUTOS;
}

export default function Displays() {
  const [displays, setDisplays] = useState<Display[]>([]);
  const [produtos, setProdutos] = useState<Produto[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const [modo, setModo] = useState<"lista" | "criar" | "editar">("lista");
  const [displayEditando, setDisplayEditando] = useState<Display | null>(null);
  const [form, setForm] = useState<FormDisplay>(FORM_VAZIO);
  const [salvando, setSalvando] = useState(false);
  const [erroForm, setErroForm] = useState<string | null>(null);

  // Token recem-gerado (criacao ou regeneracao), mostrado uma unica vez.
  const [tokenRevelado, setTokenRevelado] = useState<{ nome: string; token: string } | null>(null);

  function carregarProdutos() {
    apiFetch<Produto[]>("/produtos", { auth: true }).then(setProdutos).catch(() => {});
  }

  function carregarDisplays() {
    setCarregando(true);
    setErro(null);
    apiFetch<Display[]>("/displays", { auth: true })
      .then(setDisplays)
      .catch(() => setErro("Não foi possível carregar os displays."))
      .finally(() => setCarregando(false));
  }

  useEffect(carregarProdutos, []);
  useEffect(carregarDisplays, []);

  function abrirCriar() {
    setForm(FORM_VAZIO);
    setErroForm(null);
    setModo("criar");
  }

  function abrirEditar(display: Display) {
    setDisplayEditando(display);
    setForm({
      nome: display.nome,
      produto_id: display.produto_id ? String(display.produto_id) : "",
      ativo: display.ativo,
    });
    setErroForm(null);
    setModo("editar");
  }

  function fechar() {
    setModo("lista");
    setDisplayEditando(null);
    setErroForm(null);
  }

  async function handleCriar(e: FormEvent) {
    e.preventDefault();
    setSalvando(true);
    setErroForm(null);
    try {
      const criado = await apiFetch<Display & { token: string }>("/displays", {
        method: "POST",
        auth: true,
        body: JSON.stringify({
          nome: form.nome.trim(),
          produto_id: form.produto_id ? Number(form.produto_id) : null,
        }),
      });
      fechar();
      carregarDisplays();
      setTokenRevelado({ nome: criado.nome, token: criado.token });
    } catch {
      setErroForm("Não foi possível cadastrar o display.");
    } finally {
      setSalvando(false);
    }
  }

  async function handleEditar(e: FormEvent) {
    e.preventDefault();
    if (!displayEditando) return;
    setSalvando(true);
    setErroForm(null);
    try {
      await apiFetch(`/displays/${displayEditando.id}`, {
        method: "PUT",
        auth: true,
        body: JSON.stringify({
          nome: form.nome.trim(),
          produto_id: form.produto_id ? Number(form.produto_id) : null,
          ativo: form.ativo,
        }),
      });
      fechar();
      carregarDisplays();
    } catch {
      setErroForm("Não foi possível salvar as alterações.");
    } finally {
      setSalvando(false);
    }
  }

  async function handleRegenerarToken(display: Display) {
    if (
      !window.confirm(
        `Gerar um novo token para "${display.nome}"? O token atual gravado no firmware do dispositivo para de funcionar imediatamente -- é preciso regravar o firmware com o novo.`
      )
    ) {
      return;
    }
    try {
      const resposta = await apiFetch<{ token: string }>(`/displays/${display.id}/token`, {
        method: "POST",
        auth: true,
      });
      setTokenRevelado({ nome: display.nome, token: resposta.token });
    } catch {
      setErro("Não foi possível gerar um novo token.");
    }
  }

  async function handleDesativar(display: Display) {
    if (
      !window.confirm(
        `Desativar "${display.nome}"? Ele para de conseguir sincronizar (o token deixa de ser aceito) até ser reativado.`
      )
    ) {
      return;
    }
    try {
      await apiFetch(`/displays/${display.id}`, { method: "DELETE", auth: true });
      carregarDisplays();
    } catch {
      setErro("Não foi possível desativar o display.");
    }
  }

  function nomeProduto(id: number | null): string {
    if (!id) return "— nenhum —";
    return produtos.find((p) => p.id === id)?.nome ?? `#${id}`;
  }

  if (tokenRevelado) {
    return (
      <div className="page page-wide">
        <h1>Token gerado</h1>
        <p>
          Copie o token abaixo e grave no firmware do display <strong>{tokenRevelado.nome}</strong> (variável{" "}
          <code>DISPLAY_TOKEN</code> do sketch). Por segurança, ele não é mostrado de novo: se perder, gere outro na
          lista.
        </p>
        <div className="display-token-box">{tokenRevelado.token}</div>
        <div className="form-acoes">
          <button type="button" onClick={() => setTokenRevelado(null)}>
            OK, já copiei
          </button>
        </div>
      </div>
    );
  }

  if (modo === "criar" || (modo === "editar" && displayEditando)) {
    return (
      <div className="page page-wide">
        <h1>{modo === "criar" ? "Novo display" : `Editar display: ${displayEditando!.nome}`}</h1>
        <form onSubmit={modo === "criar" ? handleCriar : handleEditar} className="form form-produto">
          <label>
            Nome/localização
            <input
              placeholder="ex.: Prateleira 3 - Linha de colas"
              value={form.nome}
              onChange={(e) => setForm({ ...form, nome: e.target.value })}
              required
            />
          </label>
          <label>
            Produto vinculado
            <select value={form.produto_id} onChange={(e) => setForm({ ...form, produto_id: e.target.value })}>
              <option value="">Sem produto (etiqueta ainda não posicionada)</option>
              {produtos.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.nome}
                  {p.marca ? ` (${p.marca})` : ""}
                </option>
              ))}
            </select>
          </label>
          {modo === "editar" && (
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={form.ativo}
                onChange={(e) => setForm({ ...form, ativo: e.target.checked })}
              />
              Ativo (aceita sincronização do dispositivo)
            </label>
          )}

          {erroForm && <p className="erro">{erroForm}</p>}

          <div className="form-acoes">
            <button type="submit" disabled={salvando}>
              {salvando ? "Salvando..." : modo === "criar" ? "Cadastrar display" : "Salvar alterações"}
            </button>
            <button type="button" className="link-button" onClick={fechar}>
              Cancelar
            </button>
          </div>
        </form>
      </div>
    );
  }

  const atrasados = displays.filter(estaAtrasado).length;

  return (
    <div className="page page-wide">
      <h1>Displays físicos</h1>
      <p>
        Etiquetas eletrônicas de prateleira (ESP32) que exibem o preço vigente do produto vinculado. Cada
        dispositivo se identifica no sistema com o seu próprio token.
      </p>

      {/* So faz sentido falar de sincronizacao quando ha displays cadastrados. */}
      {!carregando && !erro && displays.length > 0 && (
        <p className={atrasados > 0 ? "alerta alerta-com-icone" : ""}>
          {atrasados > 0 ? (
            <>
              <Icone nome="alerta" />
              {contar(atrasados, "display", "displays")} sem sincronizar há mais de {LIMITE_ATRASO_MINUTOS} min (ou
              nunca).
            </>
          ) : (
            "Todos os displays ativos sincronizaram recentemente."
          )}
        </p>
      )}

      {/* Sem filtros nesta tela: so o botao, sem a caixa de filtros. */}
      <div className="barra-acoes">
        <button type="button" onClick={abrirCriar} className="produtos-novo-btn">
          + Novo display
        </button>
      </div>

      {erro && <p className="erro">{erro}</p>}
      {carregando && <Skeleton />}

      {!carregando && !erro && displays.length === 0 && (
        <p>Nenhum display cadastrado ainda. Cadastre um antes de configurar o firmware do dispositivo.</p>
      )}

      {!carregando && !erro && displays.length > 0 && (
        <div className="tabela-wrapper">
          <table className="tabela-estoque">
            <thead>
              <tr>
                <th>Display</th>
                <th>Produto</th>
                <th>Última sincronização</th>
                <th>Bateria</th>
                <th>Sinal</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {displays.map((d) => (
                <tr key={d.id} className={!d.ativo ? "linha-inativa" : estaAtrasado(d) ? "linha-baixa" : ""}>
                  <td>{d.nome}</td>
                  <td>{nomeProduto(d.produto_id)}</td>
                  <td>
                    {d.ultima_sincronizacao_em ? formatDateTime(d.ultima_sincronizacao_em) : "nunca"}
                  </td>
                  <td>{d.bateria_pct != null ? `${formatNumber(d.bateria_pct)}%` : "-"}</td>
                  <td>{d.rssi_dbm != null ? `${formatNumber(d.rssi_dbm)} dBm` : "-"}</td>
                  <td className="produtos-acoes-linha">
                    <span className="acoes-inline">
                      <button type="button" className="link-button" onClick={() => abrirEditar(d)}>
                        Editar
                      </button>
                      <button type="button" className="link-button" onClick={() => handleRegenerarToken(d)}>
                        Novo token
                      </button>
                      {d.ativo && (
                        <button type="button" className="link-button produtos-desativar" onClick={() => handleDesativar(d)}>
                          Desativar
                        </button>
                      )}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
