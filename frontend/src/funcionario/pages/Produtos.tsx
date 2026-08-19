import { useEffect, useState, type FormEvent } from "react";
import { ApiError, apiFetch } from "../../api/client";

interface Categoria {
  id: number;
  nome: string;
  descricao: string | null;
}

interface ProdutoCodigo {
  id: number;
  tipo: "EAN13" | "CODE128" | "QR_INTERNO";
  codigo: string;
  principal: boolean;
}

interface Produto {
  id: number;
  categoria_id: number | null;
  nome: string;
  marca: string | null;
  tamanho: string | null;
  custo: string | null;
  preco_normal: string;
  preco_promocional: string | null;
  promocao_ativa: boolean;
  ativo: boolean;
  preco_vigente: string;
  codigos: ProdutoCodigo[];
  estoque: { quantidade: number; quantidade_minima: number | null } | null;
}

interface FormCriar {
  codigo: string;
  tipo_codigo: ProdutoCodigo["tipo"];
  nome: string;
  marca: string;
  tamanho: string;
  categoria_id: string;
  custo: string;
  preco_normal: string;
  quantidade_inicial: string;
}

interface FormEditar {
  nome: string;
  marca: string;
  tamanho: string;
  categoria_id: string;
  custo: string;
  preco_normal: string;
  ativo: boolean;
}

const FORM_CRIAR_VAZIO: FormCriar = {
  codigo: "",
  tipo_codigo: "EAN13",
  nome: "",
  marca: "",
  tamanho: "",
  categoria_id: "",
  custo: "",
  preco_normal: "",
  quantidade_inicial: "0",
};

function paraFormEditar(p: Produto): FormEditar {
  return {
    nome: p.nome,
    marca: p.marca ?? "",
    tamanho: p.tamanho ?? "",
    categoria_id: p.categoria_id ? String(p.categoria_id) : "",
    custo: p.custo ?? "",
    preco_normal: p.preco_normal,
    ativo: p.ativo,
  };
}

export default function Produtos() {
  const [produtos, setProdutos] = useState<Produto[]>([]);
  const [categorias, setCategorias] = useState<Categoria[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const [busca, setBusca] = useState("");
  const [categoriaFiltro, setCategoriaFiltro] = useState("");
  const [somenteAtivos, setSomenteAtivos] = useState(true);

  const [modo, setModo] = useState<"lista" | "criar" | "editar">("lista");
  const [produtoEditando, setProdutoEditando] = useState<Produto | null>(null);
  const [formCriar, setFormCriar] = useState<FormCriar>(FORM_CRIAR_VAZIO);
  const [formEditar, setFormEditar] = useState<FormEditar | null>(null);
  const [novaCategoria, setNovaCategoria] = useState("");
  const [mostrarNovaCategoria, setMostrarNovaCategoria] = useState(false);
  const [novoCodigo, setNovoCodigo] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [erroForm, setErroForm] = useState<string | null>(null);

  function carregarCategorias() {
    apiFetch<Categoria[]>("/categorias", { auth: true }).then(setCategorias).catch(() => {});
  }

  function carregarProdutos() {
    setCarregando(true);
    setErro(null);
    const params = new URLSearchParams();
    if (busca.trim()) params.set("busca", busca.trim());
    if (categoriaFiltro) params.set("categoria_id", categoriaFiltro);
    params.set("somente_ativos", String(somenteAtivos));
    apiFetch<Produto[]>(`/produtos?${params.toString()}`, { auth: true })
      .then(setProdutos)
      .catch(() => setErro("Não foi possível carregar os produtos."))
      .finally(() => setCarregando(false));
  }

  useEffect(carregarCategorias, []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(carregarProdutos, [busca, categoriaFiltro, somenteAtivos]);

  function abrirCriar() {
    setFormCriar(FORM_CRIAR_VAZIO);
    setErroForm(null);
    setModo("criar");
  }

  function abrirEditar(produto: Produto) {
    setProdutoEditando(produto);
    setFormEditar(paraFormEditar(produto));
    setNovoCodigo("");
    setErroForm(null);
    setModo("editar");
  }

  function fechar() {
    setModo("lista");
    setProdutoEditando(null);
    setFormEditar(null);
    setErroForm(null);
  }

  async function criarNovaCategoria() {
    const nome = novaCategoria.trim();
    if (!nome) return;
    try {
      const categoria = await apiFetch<Categoria>("/categorias", {
        method: "POST",
        auth: true,
        body: JSON.stringify({ nome }),
      });
      setCategorias((atual) => [...atual, categoria].sort((a, b) => a.nome.localeCompare(b.nome)));
      setNovaCategoria("");
      setMostrarNovaCategoria(false);
    } catch {
      setErroForm("Não foi possível criar a categoria.");
    }
  }

  async function handleCriar(e: FormEvent) {
    e.preventDefault();
    setSalvando(true);
    setErroForm(null);
    try {
      await apiFetch("/produtos", {
        method: "POST",
        auth: true,
        body: JSON.stringify({
          codigo: formCriar.codigo.trim(),
          tipo_codigo: formCriar.tipo_codigo,
          nome: formCriar.nome.trim(),
          marca: formCriar.marca.trim() || null,
          tamanho: formCriar.tamanho.trim() || null,
          categoria_id: formCriar.categoria_id ? Number(formCriar.categoria_id) : null,
          custo: formCriar.custo.trim() || null,
          preco_normal: formCriar.preco_normal.trim() || null,
          quantidade_inicial: Number(formCriar.quantidade_inicial) || 0,
        }),
      });
      fechar();
      carregarProdutos();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setErroForm("Esse código já pertence a outro produto. Ajuste o estoque do produto existente em vez de cadastrar um novo.");
      } else if (err instanceof ApiError && err.status === 422) {
        setErroForm("Código novo: informe o preço normal para cadastrar este produto.");
      } else {
        setErroForm("Não foi possível cadastrar o produto.");
      }
    } finally {
      setSalvando(false);
    }
  }

  async function handleEditar(e: FormEvent) {
    e.preventDefault();
    if (!produtoEditando || !formEditar) return;
    setSalvando(true);
    setErroForm(null);
    try {
      await apiFetch(`/produtos/${produtoEditando.id}`, {
        method: "PUT",
        auth: true,
        body: JSON.stringify({
          nome: formEditar.nome.trim(),
          marca: formEditar.marca.trim() || null,
          tamanho: formEditar.tamanho.trim() || null,
          categoria_id: formEditar.categoria_id ? Number(formEditar.categoria_id) : null,
          custo: formEditar.custo.trim() || null,
          preco_normal: formEditar.preco_normal.trim(),
          ativo: formEditar.ativo,
        }),
      });
      fechar();
      carregarProdutos();
    } catch {
      setErroForm("Não foi possível salvar as alterações.");
    } finally {
      setSalvando(false);
    }
  }

  async function handleAdicionarCodigo() {
    if (!produtoEditando || !novoCodigo.trim()) return;
    setErroForm(null);
    try {
      const atualizado = await apiFetch<Produto>(`/produtos/${produtoEditando.id}/codigos`, {
        method: "POST",
        auth: true,
        body: JSON.stringify({ codigo: novoCodigo.trim(), tipo: "EAN13", principal: false }),
      });
      setProdutoEditando(atualizado);
      setNovoCodigo("");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setErroForm("Esse código já pertence a outro produto.");
      } else {
        setErroForm("Não foi possível adicionar o código.");
      }
    }
  }

  async function handleDesativar(produto: Produto) {
    if (!window.confirm(`Desativar "${produto.nome}"? Ele deixa de aparecer no catálogo e no scanner, mas o histórico é mantido.`)) {
      return;
    }
    try {
      await apiFetch(`/produtos/${produto.id}`, { method: "DELETE", auth: true });
      carregarProdutos();
    } catch {
      setErro("Não foi possível desativar o produto.");
    }
  }

  function nomeCategoria(id: number | null): string {
    if (!id) return "-";
    return categorias.find((c) => c.id === id)?.nome ?? "-";
  }

  if (modo === "criar") {
    return (
      <div className="page page-wide">
        <h1>Novo produto</h1>
        <form onSubmit={handleCriar} className="form form-produto">
          <label>
            Código de barras/QR
            <input
              value={formCriar.codigo}
              onChange={(e) => setFormCriar({ ...formCriar, codigo: e.target.value })}
              required
            />
          </label>
          <label>
            Tipo do código
            <select
              value={formCriar.tipo_codigo}
              onChange={(e) => setFormCriar({ ...formCriar, tipo_codigo: e.target.value as ProdutoCodigo["tipo"] })}
            >
              <option value="EAN13">EAN-13</option>
              <option value="CODE128">CODE128</option>
              <option value="QR_INTERNO">QR interno</option>
            </select>
          </label>
          <label>
            Nome
            <input value={formCriar.nome} onChange={(e) => setFormCriar({ ...formCriar, nome: e.target.value })} required />
          </label>
          <label>
            Marca
            <input value={formCriar.marca} onChange={(e) => setFormCriar({ ...formCriar, marca: e.target.value })} />
          </label>
          <label>
            Tamanho
            <input value={formCriar.tamanho} onChange={(e) => setFormCriar({ ...formCriar, tamanho: e.target.value })} />
          </label>
          <label>
            Categoria
            <select
              value={formCriar.categoria_id}
              onChange={(e) => setFormCriar({ ...formCriar, categoria_id: e.target.value })}
            >
              <option value="">Sem categoria</option>
              {categorias.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.nome}
                </option>
              ))}
            </select>
          </label>
          {!mostrarNovaCategoria ? (
            <button type="button" className="link-button" onClick={() => setMostrarNovaCategoria(true)}>
              + nova categoria
            </button>
          ) : (
            <div className="nova-categoria">
              <input
                placeholder="Nome da categoria"
                value={novaCategoria}
                onChange={(e) => setNovaCategoria(e.target.value)}
              />
              <button type="button" onClick={criarNovaCategoria}>
                Criar
              </button>
            </div>
          )}
          <label>
            Custo (opcional)
            <input
              type="number"
              step="0.01"
              min="0"
              value={formCriar.custo}
              onChange={(e) => setFormCriar({ ...formCriar, custo: e.target.value })}
            />
          </label>
          <label>
            Preço normal
            <input
              type="number"
              step="0.01"
              min="0"
              value={formCriar.preco_normal}
              onChange={(e) => setFormCriar({ ...formCriar, preco_normal: e.target.value })}
              required
            />
          </label>
          <label>
            Quantidade inicial em estoque
            <input
              type="number"
              min="0"
              value={formCriar.quantidade_inicial}
              onChange={(e) => setFormCriar({ ...formCriar, quantidade_inicial: e.target.value })}
            />
          </label>

          {erroForm && <p className="erro">{erroForm}</p>}

          <div className="form-acoes">
            <button type="submit" disabled={salvando}>
              {salvando ? "Salvando..." : "Cadastrar produto"}
            </button>
            <button type="button" className="link-button" onClick={fechar}>
              Cancelar
            </button>
          </div>
        </form>
      </div>
    );
  }

  if (modo === "editar" && produtoEditando && formEditar) {
    return (
      <div className="page page-wide">
        <h1>Editar produto</h1>
        <form onSubmit={handleEditar} className="form form-produto">
          <label>
            Nome
            <input value={formEditar.nome} onChange={(e) => setFormEditar({ ...formEditar, nome: e.target.value })} required />
          </label>
          <label>
            Marca
            <input value={formEditar.marca} onChange={(e) => setFormEditar({ ...formEditar, marca: e.target.value })} />
          </label>
          <label>
            Tamanho
            <input value={formEditar.tamanho} onChange={(e) => setFormEditar({ ...formEditar, tamanho: e.target.value })} />
          </label>
          <label>
            Categoria
            <select
              value={formEditar.categoria_id}
              onChange={(e) => setFormEditar({ ...formEditar, categoria_id: e.target.value })}
            >
              <option value="">Sem categoria</option>
              {categorias.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.nome}
                </option>
              ))}
            </select>
          </label>
          <label>
            Custo (opcional)
            <input
              type="number"
              step="0.01"
              min="0"
              value={formEditar.custo}
              onChange={(e) => setFormEditar({ ...formEditar, custo: e.target.value })}
            />
          </label>
          <label>
            Preço normal
            <input
              type="number"
              step="0.01"
              min="0"
              value={formEditar.preco_normal}
              onChange={(e) => setFormEditar({ ...formEditar, preco_normal: e.target.value })}
              required
            />
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={formEditar.ativo}
              onChange={(e) => setFormEditar({ ...formEditar, ativo: e.target.checked })}
            />
            Ativo (visível no catálogo/scanner)
          </label>

          <div className="produto-codigos">
            <strong>Códigos cadastrados</strong>
            <ul>
              {produtoEditando.codigos.map((c) => (
                <li key={c.id}>
                  {c.codigo} <span className="promo-detalhe">({c.tipo}{c.principal ? ", principal" : ""})</span>
                </li>
              ))}
            </ul>
            <div className="nova-categoria">
              <input placeholder="Adicionar novo código" value={novoCodigo} onChange={(e) => setNovoCodigo(e.target.value)} />
              <button type="button" onClick={handleAdicionarCodigo}>
                Adicionar
              </button>
            </div>
          </div>

          {erroForm && <p className="erro">{erroForm}</p>}

          <div className="form-acoes">
            <button type="submit" disabled={salvando}>
              {salvando ? "Salvando..." : "Salvar alterações"}
            </button>
            <button type="button" className="link-button" onClick={fechar}>
              Cancelar
            </button>
          </div>
        </form>
      </div>
    );
  }

  return (
    <div className="page page-wide">
      <h1>Produtos</h1>

      <div className="produtos-filtros">
        <input
          placeholder="Buscar por nome..."
          value={busca}
          onChange={(e) => setBusca(e.target.value)}
        />
        <select value={categoriaFiltro} onChange={(e) => setCategoriaFiltro(e.target.value)}>
          <option value="">Todas as categorias</option>
          {categorias.map((c) => (
            <option key={c.id} value={c.id}>
              {c.nome}
            </option>
          ))}
        </select>
        <label className="checkbox-label">
          <input type="checkbox" checked={somenteAtivos} onChange={(e) => setSomenteAtivos(e.target.checked)} />
          Somente ativos
        </label>
        <button type="button" onClick={abrirCriar} className="produtos-novo-btn">
          + Novo produto
        </button>
      </div>

      {erro && <p className="erro">{erro}</p>}
      {carregando && <p>Carregando...</p>}

      {!carregando && !erro && produtos.length === 0 && <p>Nenhum produto encontrado.</p>}

      {!carregando && !erro && produtos.length > 0 && (
        <div className="tabela-wrapper">
          <table className="tabela-estoque">
            <thead>
              <tr>
                <th>Produto</th>
                <th>Marca</th>
                <th>Tamanho</th>
                <th>Categoria</th>
                <th>Preço</th>
                <th>Estoque</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {produtos.map((p) => (
                <tr key={p.id} className={!p.ativo ? "linha-inativa" : ""}>
                  <td>{p.nome}</td>
                  <td>{p.marca ?? "-"}</td>
                  <td>{p.tamanho ?? "-"}</td>
                  <td>{nomeCategoria(p.categoria_id)}</td>
                  <td>
                    R$ {p.preco_vigente}
                    {p.promocao_ativa && <span className="promo-detalhe"> (promoção)</span>}
                  </td>
                  <td>{p.estoque?.quantidade ?? "-"}</td>
                  <td className="produtos-acoes-linha">
                    <button type="button" className="link-button" onClick={() => abrirEditar(p)}>
                      Editar
                    </button>
                    {p.ativo && (
                      <button type="button" className="link-button produtos-desativar" onClick={() => handleDesativar(p)}>
                        Desativar
                      </button>
                    )}
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
