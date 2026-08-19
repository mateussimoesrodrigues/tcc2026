import { useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "../../api/client";
import { useCart } from "../../context/CartContext";
import ScannerCamera from "../components/ScannerCamera";

interface ProdutoPublico {
  produto_id: number;
  nome: string;
  marca: string | null;
  tamanho: string | null;
  preco_vigente: string;
}

interface LookupResposta {
  encontrado: boolean;
  produto: ProdutoPublico | null;
}

type Resultado =
  | { tipo: "sucesso"; produto: ProdutoPublico }
  | { tipo: "nao_encontrado"; codigo: string }
  | { tipo: "erro"; mensagem: string };

// Evita reprocessar o mesmo codigo em frames seguidos enquanto a camera
// continua lendo (a lib chama onScan repetidamente para o mesmo QR/barras
// parado na frente da lente).
const JANELA_IGNORAR_REPETICAO_MS = 2500;

export default function Scanner() {
  const navigate = useNavigate();
  const { adicionarItem } = useCart();
  const [resultado, setResultado] = useState<Resultado | null>(null);
  const [processando, setProcessando] = useState(false);
  const [codigoManual, setCodigoManual] = useState("");
  const ultimoCodigoRef = useRef<{ codigo: string; em: number } | null>(null);

  async function processarCodigo(codigo: string) {
    setProcessando(true);
    try {
      const lookup = await apiFetch<LookupResposta>(`/catalogo/codigo/${encodeURIComponent(codigo)}`);
      if (!lookup.encontrado || !lookup.produto) {
        setResultado({ tipo: "nao_encontrado", codigo });
        return;
      }
      await adicionarItem(lookup.produto.produto_id, 1);
      setResultado({ tipo: "sucesso", produto: lookup.produto });
    } catch {
      setResultado({ tipo: "erro", mensagem: "Não foi possível adicionar o produto ao carrinho." });
    } finally {
      setProcessando(false);
    }
  }

  function handleScan(codigo: string) {
    const agora = Date.now();
    const ultimo = ultimoCodigoRef.current;
    if (ultimo && ultimo.codigo === codigo && agora - ultimo.em < JANELA_IGNORAR_REPETICAO_MS) {
      return;
    }
    ultimoCodigoRef.current = { codigo, em: agora };
    processarCodigo(codigo);
  }

  function handleEnvioManual(e: FormEvent) {
    e.preventDefault();
    const codigo = codigoManual.trim();
    if (!codigo) return;
    setCodigoManual("");
    processarCodigo(codigo);
  }

  return (
    <div className="page">
      <h1>Escanear produto</h1>
      <p>Aponte a câmera para o código de barras ou QR do produto.</p>

      <ScannerCamera onScan={handleScan} pausado={processando} />

      <details className="scanner-manual">
        <summary>Câmera não funcionou? Digitar o código</summary>
        <form onSubmit={handleEnvioManual} className="scanner-manual-form">
          <input
            type="text"
            value={codigoManual}
            onChange={(e) => setCodigoManual(e.target.value)}
            placeholder="Código de barras ou QR"
            inputMode="numeric"
          />
          <button type="submit" disabled={processando || !codigoManual.trim()}>
            Adicionar
          </button>
        </form>
      </details>

      {resultado?.tipo === "sucesso" && (
        <div className="scanner-resultado scanner-resultado-ok">
          <strong>{resultado.produto.nome}</strong>
          {resultado.produto.marca && <span> — {resultado.produto.marca}</span>}
          <p>Adicionado ao carrinho por R$ {resultado.produto.preco_vigente}</p>
        </div>
      )}
      {resultado?.tipo === "nao_encontrado" && (
        <div className="scanner-resultado scanner-resultado-erro">
          Produto não encontrado para o código <code>{resultado.codigo}</code>.
        </div>
      )}
      {resultado?.tipo === "erro" && (
        <div className="scanner-resultado scanner-resultado-erro">{resultado.mensagem}</div>
      )}

      <button type="button" onClick={() => navigate("/carrinho")} className="scanner-ir-carrinho">
        Ver carrinho
      </button>
    </div>
  );
}
