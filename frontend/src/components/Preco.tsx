import { formatBRL, formatPercent } from "../utils/format";
import Icone from "./Icone";

type Valor = string | number;

/**
 * Variacao entre dois precos: queda em lima (preco que cai = promocao),
 * alta em vermelho. Preco igual nao e variacao: mostra um traco neutro.
 */
export function PriceDelta({ from, to }: { from: Valor; to: Valor }) {
  const de = Number(from);
  const para = Number(to);
  if (!Number.isFinite(de) || !Number.isFinite(para) || de === 0 || de === para) {
    return <span className="preco-delta preco-delta-zero">—</span>;
  }
  const caiu = para < de;
  const pct = (Math.abs(para - de) / de) * 100;
  return (
    <span
      className={`preco-delta ${caiu ? "preco-delta-queda" : "preco-delta-alta"}`}
      title={`${formatBRL(de)} → ${formatBRL(para)}`}
    >
      <Icone nome={caiu ? "trianguloBaixo" : "trianguloCima"} />
      <span className="sr-only">{caiu ? "Queda de " : "Alta de "}</span>
      {formatPercent(pct, 1)}
    </span>
  );
}

/** Preco de tabela riscado + preco promocional em lima. */
export function PromoPrice({ original, promo }: { original: Valor; promo: Valor }) {
  return (
    <span className="preco-promo">
      <del className="preco-promo-antigo">{formatBRL(original)}</del>
      <strong className="preco-promo-novo">{formatBRL(promo)}</strong>
    </span>
  );
}
