import type { SVGProps } from "react";

// Icones de traco (24x24, mesmo estilo dos da barra lateral em App.tsx). Sem
// biblioteca externa: o projeto desenha os seus como SVG inline. Herdam a cor
// do texto (currentColor) e o tamanho da fonte (1em), entao se encaixam em
// qualquer linha de texto, botao ou badge.
const CAMINHOS = {
  alerta: (
    <>
      <path d="M12 3.8L2.8 19.5h18.4z" />
      <path d="M12 10v4.2M12 17.1h.01" />
    </>
  ),
  seta: <path d="M4 12h15M13.5 6.5L19 12l-5.5 5.5" />,
  mais: (
    <>
      <circle cx="5.5" cy="12" r="1.2" />
      <circle cx="12" cy="12" r="1.2" />
      <circle cx="18.5" cy="12" r="1.2" />
    </>
  ),
  chevron: <path d="M8.5 5.5L15 12l-6.5 6.5" />,
  chevronBaixo: <path d="M5.5 8.5L12 15l6.5-6.5" />,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  x: <path d="M6 6l12 12M18 6L6 18" />,
  info: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 11v5.2M12 7.9h.01" />
    </>
  ),
  // Triangulos cheios: variacao de preco (caiu / subiu).
  trianguloBaixo: <path d="M6 9.5h12L12 17.5z" className="icone-cheio" />,
  trianguloCima: <path d="M6 14.5h12L12 6.5z" className="icone-cheio" />,
} as const;

export type NomeIcone = keyof typeof CAMINHOS;

interface Props extends Omit<SVGProps<SVGSVGElement>, "name"> {
  nome: NomeIcone;
  /** Texto para leitor de tela. Sem ele o icone e decorativo (aria-hidden). */
  titulo?: string;
}

export default function Icone({ nome, titulo, className, ...resto }: Props) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={`icone${className ? ` ${className}` : ""}`}
      role={titulo ? "img" : undefined}
      aria-label={titulo}
      aria-hidden={titulo ? undefined : true}
      focusable="false"
      {...resto}
    >
      {CAMINHOS[nome]}
    </svg>
  );
}
