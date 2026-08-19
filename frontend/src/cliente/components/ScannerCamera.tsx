import { useEffect, useRef, useState } from "react";
import { Html5Qrcode } from "html5-qrcode";

// Le QR e codigo de barras (EAN-13/CODE128) pela camera do navegador.
// Usa a API `Html5Qrcode` (nao o widget `Html5QrcodeScanner`, que ja vem
// com UI propria) para controlar o layout dentro da pagina.
//
// BarcodeDetector nativo do navegador nao existe no iOS Safari (sem
// previsao da Apple), entao html5-qrcode (baseado em ZXing.js) e usado
// para cobrir Android e iOS de forma consistente. Requer HTTPS em
// producao/celular (funciona em http://localhost em dev).

const READER_ELEMENT_ID = "scanner-camera-reader";

interface ScannerCameraProps {
  onScan: (codigo: string) => void;
  pausado?: boolean; // pausa a leitura sem desmontar a camera (ex.: durante confirmacao de item)
}

export default function ScannerCamera({ onScan, pausado = false }: ScannerCameraProps) {
  const scannerRef = useRef<Html5Qrcode | null>(null);
  const onScanRef = useRef(onScan);
  const [erro, setErro] = useState<string | null>(null);
  const [iniciando, setIniciando] = useState(true);

  onScanRef.current = onScan;

  useEffect(() => {
    const scanner = new Html5Qrcode(READER_ELEMENT_ID, { verbose: false });
    scannerRef.current = scanner;
    let cancelado = false;

    scanner
      .start(
        { facingMode: "environment" },
        { fps: 10, qrbox: { width: 250, height: 250 } },
        (codigoDecodificado) => {
          if (!cancelado) onScanRef.current(codigoDecodificado);
        },
        () => {
          // erro "nao achou codigo neste frame" -- disparado a cada frame
          // sem leitura, nao e um erro real, so ignoramos.
        }
      )
      .then(() => {
        if (!cancelado) setIniciando(false);
      })
      .catch(() => {
        if (!cancelado) {
          setErro(
            "Não foi possível acessar a câmera. Verifique a permissão do navegador e se a página está em HTTPS."
          );
          setIniciando(false);
        }
      });

    return () => {
      cancelado = true;
      // stop()/pause() da lib podem lancar sincronamente (nao so rejeitar
      // a Promise) quando o scanner nao esta num estado "parável" -- ex.:
      // desmontou antes do start() terminar, ou HMR remontou o componente
      // no meio da inicializacao. Por isso o try/catch por fora, alem do
      // .catch() na Promise.
      try {
        scanner
          .stop()
          .then(() => scanner.clear())
          .catch(() => {
            /* camera pode ja ter sido parada (ex.: erro na inicializacao) */
          });
      } catch {
        /* scanner nunca chegou a rodar -- nada para parar */
      }
    };
  }, []);

  useEffect(() => {
    const scanner = scannerRef.current;
    if (!scanner) return;
    try {
      if (pausado) {
        scanner.pause(true);
      } else {
        scanner.resume();
      }
    } catch {
      /* scanner ainda nao terminou de iniciar -- pause/resume so valem
         depois que a Promise do start() resolver */
    }
  }, [pausado]);

  return (
    <div className="scanner-camera">
      <div id={READER_ELEMENT_ID} className="scanner-camera-reader" />
      {iniciando && !erro && <p>Abrindo câmera...</p>}
      {erro && <p className="erro">{erro}</p>}
    </div>
  );
}
