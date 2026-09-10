/**
 * Gráfico de linha em SVG inline.
 *
 * Escrito à mão em vez de instalar uma lib de charts: são ~90 linhas, o
 * projeto tem exatamente dois gráficos, e o SVG resultante pode ser
 * copiado direto para a monografia sem passar por captura de tela.
 */

interface Ponto {
  rotulo: string;
  valor: number;
}

interface Props {
  pontos: Ponto[];
  altura?: number;
  formatar?: (valor: number) => string;
  titulo?: string;
}

const LARGURA = 720;
const MARGEM = { topo: 16, direita: 12, base: 28, esquerda: 62 };

export default function GraficoLinha({ pontos, altura = 220, formatar, titulo }: Props) {
  if (pontos.length === 0) {
    return <p className="grafico-vazio">Sem dados no período.</p>;
  }

  const fmt = formatar ?? ((v: number) => String(Math.round(v)));
  const larguraPlot = LARGURA - MARGEM.esquerda - MARGEM.direita;
  const alturaPlot = altura - MARGEM.topo - MARGEM.base;

  const maximo = Math.max(...pontos.map((p) => p.valor), 1);
  // Um único ponto não tem intervalo: divide por 1 para não gerar NaN.
  const passo = larguraPlot / Math.max(pontos.length - 1, 1);

  const x = (i: number) => MARGEM.esquerda + i * passo;
  const y = (valor: number) => MARGEM.topo + alturaPlot - (valor / maximo) * alturaPlot;

  const linha = pontos.map((p, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(p.valor).toFixed(1)}`).join(" ");
  const area =
    `${linha} L ${x(pontos.length - 1).toFixed(1)} ${MARGEM.topo + alturaPlot} ` +
    `L ${MARGEM.esquerda} ${MARGEM.topo + alturaPlot} Z`;

  const linhasGrade = [0, 0.25, 0.5, 0.75, 1];
  // No máximo 6 rótulos no eixo X, senão viram um borrão em telas estreitas.
  const passoRotulo = Math.max(1, Math.ceil(pontos.length / 6));

  return (
    <figure className="grafico">
      {titulo && <figcaption className="grafico-titulo">{titulo}</figcaption>}
      <div className="grafico-scroll">
        <svg
          viewBox={`0 0 ${LARGURA} ${altura}`}
          className="grafico-svg"
          role="img"
          aria-label={titulo ?? "Gráfico de linha"}
        >
          {linhasGrade.map((fracao) => {
            const py = MARGEM.topo + alturaPlot - fracao * alturaPlot;
            return (
              <g key={fracao}>
                <line
                  x1={MARGEM.esquerda}
                  y1={py}
                  x2={LARGURA - MARGEM.direita}
                  y2={py}
                  className="grafico-grade"
                />
                <text x={MARGEM.esquerda - 8} y={py + 4} className="grafico-rotulo grafico-rotulo-y">
                  {fmt(maximo * fracao)}
                </text>
              </g>
            );
          })}

          <path d={area} className="grafico-area" />
          <path d={linha} className="grafico-linha" />

          {pontos.map((p, i) =>
            i % passoRotulo === 0 || i === pontos.length - 1 ? (
              <text key={p.rotulo} x={x(i)} y={altura - 8} className="grafico-rotulo grafico-rotulo-x">
                {p.rotulo.slice(5)}
              </text>
            ) : null
          )}

          {/* Círculos só quando há poucos pontos: com 90 dias eles viram ruído. */}
          {pontos.length <= 30 &&
            pontos.map((p, i) => (
              <circle key={p.rotulo} cx={x(i)} cy={y(p.valor)} r={2.5} className="grafico-ponto">
                <title>{`${p.rotulo}: ${fmt(p.valor)}`}</title>
              </circle>
            ))}
        </svg>
      </div>
    </figure>
  );
}
