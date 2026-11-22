import { useEffect, useId, useRef, useState } from "react";
import Icone from "./Icone";

export interface ItemMenu {
  rotulo: string;
  onClick: () => void;
  /** Acao destrutiva (ex.: Desativar): texto em vermelho. */
  perigo?: boolean;
}

/**
 * Menu "⋯" de acoes de uma linha de tabela. A lista usa position: fixed (e nao
 * absolute) porque o .tabela-wrapper rola na horizontal e cortaria um menu
 * absoluto na ultima linha. Fecha com clique fora, Esc, rolagem e redimensionar.
 * Setas cima/baixo navegam entre os itens.
 */
export default function MenuAcoes({ rotulo, itens }: { rotulo: string; itens: ItemMenu[] }) {
  const [aberto, setAberto] = useState(false);
  const [pos, setPos] = useState({ top: 0, right: 0 });
  const raiz = useRef<HTMLDivElement>(null);
  const botao = useRef<HTMLButtonElement>(null);
  const lista = useRef<HTMLDivElement>(null);
  const idMenu = useId();

  function alternar() {
    if (!aberto && botao.current) {
      const caixa = botao.current.getBoundingClientRect();
      setPos({ top: caixa.bottom + 4, right: window.innerWidth - caixa.right });
    }
    setAberto((v) => !v);
  }

  useEffect(() => {
    if (!aberto) return;
    lista.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    const fechar = () => setAberto(false);
    function aoClicarFora(e: PointerEvent) {
      if (raiz.current && !raiz.current.contains(e.target as Node)) fechar();
    }
    function aoTeclar(e: KeyboardEvent) {
      if (e.key === "Escape") {
        fechar();
        botao.current?.focus();
      } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const itensDom = Array.from(lista.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []);
        const i = itensDom.indexOf(document.activeElement as HTMLElement);
        const proximo = e.key === "ArrowDown" ? i + 1 : i - 1;
        itensDom[(proximo + itensDom.length) % itensDom.length]?.focus();
      }
    }
    document.addEventListener("pointerdown", aoClicarFora);
    window.addEventListener("keydown", aoTeclar);
    window.addEventListener("scroll", fechar, true);
    window.addEventListener("resize", fechar);
    return () => {
      document.removeEventListener("pointerdown", aoClicarFora);
      window.removeEventListener("keydown", aoTeclar);
      window.removeEventListener("scroll", fechar, true);
      window.removeEventListener("resize", fechar);
    };
  }, [aberto]);

  return (
    <div className="menu-acoes" ref={raiz}>
      <button
        ref={botao}
        type="button"
        className="menu-acoes-botao"
        aria-label={rotulo}
        aria-haspopup="menu"
        aria-expanded={aberto}
        aria-controls={aberto ? idMenu : undefined}
        onClick={alternar}
      >
        <Icone nome="mais" />
      </button>
      {aberto && (
        <div
          id={idMenu}
          ref={lista}
          role="menu"
          aria-label={rotulo}
          className="menu-acoes-lista"
          style={{ top: pos.top, right: pos.right }}
        >
          {itens.map((item) => (
            <button
              key={item.rotulo}
              type="button"
              role="menuitem"
              className={item.perigo ? "perigo" : undefined}
              onClick={() => {
                setAberto(false);
                item.onClick();
              }}
            >
              {item.rotulo}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
