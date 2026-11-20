/**
 * Gráficos do painel de indicadores, em SVG/CSS puro (sem lib de charts, como
 * os demais do projeto). Cores só via tokens do index.css, então os temas
 * claro e escuro funcionam sem nenhum tratamento aqui.
 */
import { useEffect, useId, useRef, useState } from "react";

function useLargura<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [largura, setLargura] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new ResizeObserver(([entrada]) => setLargura(Math.round(entrada.contentRect.width)));
    obs.observe(el);
    return () => obs.disconnect();
  }, []);
  return [ref, largura] as const;
}

/** Arredonda o máximo para 1, 2, 2,5, 5 ou 10 × 10ⁿ: eixo com números "redondos". */
function maximoRedondo(valor: number): number {
  if (valor <= 0) return 1;
  const potencia = 10 ** Math.floor(Math.log10(valor));
  const fracao = valor / potencia;
  const passo = fracao <= 1 ? 1 : fracao <= 2 ? 2 : fracao <= 2.5 ? 2.5 : fracao <= 5 ? 5 : 10;
  return passo * potencia;
}

/** Curva suave sem overshoot: controles horizontais no meio de cada segmento. */
function caminhoSuave(pts: { x: number; y: number }[]): string {
  if (pts.length === 0) return "";
  let d = `M ${pts[0].x.toFixed(1)} ${pts[0].y.toFixed(1)}`;
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1];
    const b = pts[i];
    const cx = (a.x + b.x) / 2;
    d += ` C ${cx.toFixed(1)} ${a.y.toFixed(1)} ${cx.toFixed(1)} ${b.y.toFixed(1)} ${b.x.toFixed(1)} ${b.y.toFixed(1)}`;
  }
  return d;
}

// --- Área (receita ao longo do tempo) -------------------------------------

export interface PontoArea {
  rotulo: string; // "AAAA-MM-DD"
  valor: number;
  extra?: number;
}

interface PropsArea {
  pontos: PontoArea[];
  altura?: number;
  formatar: (valor: number) => string;
  formatarEixo: (valor: number) => string;
  nomeValor: string;
  nomeExtra?: string;
}

const M = { topo: 12, direita: 14, base: 26, esquerda: 52 };

const dataCurta = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;

export function GraficoArea({ pontos, altura = 250, formatar, formatarEixo, nomeValor, nomeExtra }: PropsArea) {
  const [ref, largura] = useLargura<HTMLDivElement>();
  const [ativo, setAtivo] = useState<number | null>(null);
  const idGrad = useId();

  const temExtra = pontos.some((p) => p.extra !== undefined);
  const maximo = maximoRedondo(Math.max(...pontos.map((p) => p.valor), ...pontos.map((p) => p.extra ?? 0), 0));
  const larguraPlot = Math.max(largura - M.esquerda - M.direita, 1);
  const alturaPlot = altura - M.topo - M.base;
  const passo = larguraPlot / Math.max(pontos.length - 1, 1);
  const x = (i: number) => M.esquerda + (pontos.length === 1 ? larguraPlot / 2 : i * passo);
  const y = (v: number) => M.topo + alturaPlot - (v / maximo) * alturaPlot;

  const ptsValor = pontos.map((p, i) => ({ x: x(i), y: y(p.valor) }));
  const linha = caminhoSuave(ptsValor);
  const base = M.topo + alturaPlot;
  const area = pontos.length
    ? `${linha} L ${x(pontos.length - 1).toFixed(1)} ${base} L ${x(0).toFixed(1)} ${base} Z`
    : "";
  const linhaExtra = temExtra
    ? caminhoSuave(pontos.map((p, i) => ({ x: x(i), y: y(p.extra ?? 0) })))
    : "";

  const passoRotulo = Math.max(1, Math.ceil(pontos.length / Math.max(Math.floor(larguraPlot / 70), 2)));

  function aoMover(e: React.PointerEvent<SVGSVGElement>) {
    const caixa = e.currentTarget.getBoundingClientRect();
    const i = Math.round((e.clientX - caixa.left - M.esquerda) / passo);
    setAtivo(Math.min(Math.max(i, 0), pontos.length - 1));
  }

  const p = ativo !== null ? pontos[ativo] : null;

  return (
    <div className="ind-area" ref={ref} style={{ height: altura }}>
      {largura > 0 && pontos.length > 0 && (
        <>
          <svg
            width={largura}
            height={altura}
            role="img"
            aria-label={`Gráfico de ${nomeValor.toLowerCase()} por dia`}
            onPointerMove={aoMover}
            onPointerLeave={() => setAtivo(null)}
          >
            <defs>
              <linearGradient id={idGrad} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--serie)" stopOpacity="0.34" />
                <stop offset="100%" stopColor="var(--serie)" stopOpacity="0" />
              </linearGradient>
            </defs>

            {[0, 0.25, 0.5, 0.75, 1].map((f) => (
              <g key={f}>
                <line x1={M.esquerda} x2={largura - M.direita} y1={y(maximo * f)} y2={y(maximo * f)} className="ind-grade" />
                <text x={M.esquerda - 10} y={y(maximo * f) + 4} className="ind-eixo ind-eixo-y">
                  {formatarEixo(maximo * f)}
                </text>
              </g>
            ))}

            <path d={area} fill={`url(#${idGrad})`} />
            {temExtra && <path d={linhaExtra} className="ind-linha-extra" />}
            <path d={linha} className="ind-linha" />

            {pontos.map((pt, i) =>
              i % passoRotulo === 0 ? (
                <text key={pt.rotulo} x={x(i)} y={altura - 6} className="ind-eixo ind-eixo-x">
                  {dataCurta(pt.rotulo)}
                </text>
              ) : null,
            )}

            {ativo !== null && (
              <g>
                <line x1={x(ativo)} x2={x(ativo)} y1={M.topo} y2={base} className="ind-guia" />
                <circle cx={x(ativo)} cy={y(pontos[ativo].valor)} r={5} className="ind-ponto" />
              </g>
            )}
          </svg>

          {p && ativo !== null && (
            <div
              className="ind-dica"
              style={{
                left: Math.min(Math.max(x(ativo), 70), largura - 70),
                top: Math.max(y(p.valor) - 62, 0),
              }}
            >
              <span className="ind-dica-data">{dataCurta(p.rotulo)}</span>
              <strong>{formatar(p.valor)}</strong>
              {temExtra && nomeExtra && (
                <span className="ind-dica-extra">
                  {nomeExtra} {formatar(p.extra ?? 0)}
                </span>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// --- Rosca (decisões da IA) -----------------------------------------------

export interface Fatia {
  rotulo: string;
  valor: number;
  cor: string; // qualquer valor CSS de cor, normalmente var(--token)
}

export function Rosca({
  fatias,
  centro,
  legendaCentro,
  tamanho = 156,
}: {
  fatias: Fatia[];
  centro: string;
  legendaCentro: string;
  tamanho?: number;
}) {
  const raio = 58;
  const espessura = 13;
  const circ = 2 * Math.PI * raio;
  const total = fatias.reduce((s, f) => s + f.valor, 0);
  const folga = fatias.filter((f) => f.valor > 0).length > 1 ? 4 : 0;
  let acumulado = 0;
  // Fatia sob o mouse: o centro troca a taxa de aprovacao pela porcentagem
  // dela sobre o total, e as outras ficam esmaecidas.
  const [ativa, setAtiva] = useState<string | null>(null);
  const fatiaAtiva = fatias.find((f) => f.rotulo === ativa && f.valor > 0);

  return (
    <div className="ind-rosca" style={{ width: tamanho, height: tamanho }}>
      <svg viewBox="0 0 140 140" role="img" aria-label={`${legendaCentro}: ${centro}`}>
        <circle cx="70" cy="70" r={raio} className="ind-rosca-trilho" strokeWidth={espessura} />
        {total > 0 &&
          fatias.map((f) => {
            if (f.valor <= 0) return null;
            const comprimento = (f.valor / total) * circ;
            const deslocamento = -acumulado;
            acumulado += comprimento;
            return (
              <circle
                key={f.rotulo}
                cx="70"
                cy="70"
                r={raio}
                fill="none"
                stroke={f.cor}
                strokeWidth={espessura}
                strokeLinecap="round"
                strokeDasharray={`${Math.max(comprimento - folga, 0.5)} ${circ}`}
                strokeDashoffset={deslocamento}
                transform="rotate(-90 70 70)"
                className="ind-rosca-fatia"
                opacity={ativa && ativa !== f.rotulo ? 0.3 : 1}
                onPointerEnter={() => setAtiva(f.rotulo)}
                onPointerLeave={() => setAtiva(null)}
              />
            );
          })}
      </svg>
      <div className="ind-rosca-centro" aria-live="polite">
        <strong>
          {fatiaAtiva ? `${((fatiaAtiva.valor / total) * 100).toFixed(0)}%` : centro}
        </strong>
        <span>{fatiaAtiva ? `${fatiaAtiva.rotulo} · ${fatiaAtiva.valor}` : legendaCentro}</span>
      </div>
    </div>
  );
}

// --- Barras verticais (padrão por dia da semana) ---------------------------

export function BarrasSemana({
  dias,
  formatar,
}: {
  dias: { rotulo: string; valor: number }[];
  formatar: (valor: number) => string;
}) {
  const maximo = Math.max(...dias.map((d) => d.valor), 0);
  return (
    <div className="ind-semana" role="img" aria-label="Receita média por dia da semana">
      {dias.map((d) => {
        const destaque = maximo > 0 && d.valor === maximo;
        return (
          <div key={d.rotulo} className={`ind-semana-col${destaque ? " destaque" : ""}`}>
            <span className="ind-semana-valor">{formatar(d.valor)}</span>
            <div className="ind-semana-trilho">
              <div
                className="ind-semana-barra"
                style={{ height: `${maximo > 0 ? Math.max((d.valor / maximo) * 100, 3) : 3}%` }}
              />
            </div>
            <span className="ind-semana-rotulo">{d.rotulo}</span>
          </div>
        );
      })}
    </div>
  );
}
