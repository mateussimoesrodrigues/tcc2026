/**
 * Barras agrupadas (antes x depois) em SVG inline — mesma decisão do
 * GraficoLinha: sem dependência, e o SVG vai direto para a monografia.
 */

interface Grupo {
  rotulo: string;
  antes: number;
  depois: number;
}

interface Props {
  grupos: Grupo[];
  altura?: number;
  legendaAntes?: string;
  legendaDepois?: string;
  titulo?: string;
}

const LARGURA_POR_GRUPO = 78;
const LARGURA_MINIMA = 520;
const MARGEM = { topo: 16, direita: 12, base: 56, esquerda: 46 };

export default function GraficoBarras({
  grupos,
  altura = 240,
  legendaAntes = "antes",
  legendaDepois = "durante",
  titulo,
}: Props) {
  if (grupos.length === 0) {
    return <p className="grafico-vazio">Sem promoções para comparar.</p>;
  }

  const largura = Math.max(LARGURA_MINIMA, MARGEM.esquerda + MARGEM.direita + grupos.length * LARGURA_POR_GRUPO);
  const larguraPlot = largura - MARGEM.esquerda - MARGEM.direita;
  const alturaPlot = altura - MARGEM.topo - MARGEM.base;

  const maximo = Math.max(...grupos.flatMap((g) => [g.antes, g.depois]), 0.1);
  const faixa = larguraPlot / grupos.length;
  const larguraBarra = Math.min(22, faixa / 2.6);

  const y = (valor: number) => MARGEM.topo + alturaPlot - (valor / maximo) * alturaPlot;
  const alturaBarra = (valor: number) => Math.max((valor / maximo) * alturaPlot, valor > 0 ? 1.5 : 0);

  return (
    <figure className="grafico">
      {titulo && <figcaption className="grafico-titulo">{titulo}</figcaption>}

      <div className="grafico-legenda">
        <span>
          <i className="grafico-chip grafico-chip-antes" /> {legendaAntes}
        </span>
        <span>
          <i className="grafico-chip grafico-chip-depois" /> {legendaDepois}
        </span>
      </div>

      <div className="grafico-scroll">
        <svg
          viewBox={`0 0 ${largura} ${altura}`}
          width={largura}
          className="grafico-svg"
          role="img"
          aria-label={titulo ?? "Gráfico de barras"}
        >
          {[0, 0.5, 1].map((fracao) => {
            const py = MARGEM.topo + alturaPlot - fracao * alturaPlot;
            return (
              <g key={fracao}>
                <line x1={MARGEM.esquerda} y1={py} x2={largura - MARGEM.direita} y2={py} className="grafico-grade" />
                <text x={MARGEM.esquerda - 8} y={py + 4} className="grafico-rotulo grafico-rotulo-y">
                  {(maximo * fracao).toFixed(1)}
                </text>
              </g>
            );
          })}

          {grupos.map((g, i) => {
            const centro = MARGEM.esquerda + faixa * i + faixa / 2;
            return (
              <g key={`${g.rotulo}-${i}`}>
                <rect
                  x={centro - larguraBarra - 2}
                  y={y(g.antes)}
                  width={larguraBarra}
                  height={alturaBarra(g.antes)}
                  className="grafico-barra grafico-barra-antes"
                >
                  <title>{`${g.rotulo} — antes: ${g.antes} un/dia`}</title>
                </rect>
                <rect
                  x={centro + 2}
                  y={y(g.depois)}
                  width={larguraBarra}
                  height={alturaBarra(g.depois)}
                  className="grafico-barra grafico-barra-depois"
                >
                  <title>{`${g.rotulo} — durante: ${g.depois} un/dia`}</title>
                </rect>
                {/* Rótulo inclinado: nome de produto não cabe na horizontal. */}
                <text
                  x={centro}
                  y={altura - MARGEM.base + 18}
                  className="grafico-rotulo grafico-rotulo-x"
                  transform={`rotate(-32 ${centro} ${altura - MARGEM.base + 18})`}
                  textAnchor="end"
                >
                  {g.rotulo.length > 16 ? `${g.rotulo.slice(0, 15)}…` : g.rotulo}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </figure>
  );
}
