// Formatacao pt-BR centralizada. Toda tela deve usar estas funcoes em vez de
// toFixed / template string com "R$" / toLocaleString solto, para preco,
// numero, percentual e data aparecerem do mesmo jeito em todo o painel.

const FUSO = "America/Sao_Paulo";

const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const brlCompacto = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
  notation: "compact",
  maximumFractionDigits: 1,
});
const numero = new Intl.NumberFormat("pt-BR");

type Valor = string | number | null | undefined;

function paraNumero(valor: Valor): number | null {
  if (valor === null || valor === undefined || valor === "") return null;
  const n = typeof valor === "number" ? valor : Number(valor);
  return Number.isFinite(n) ? n : null;
}

/** "R$ 1.234,50". Valor ausente/invalido vira "—". */
export function formatBRL(valor: Valor): string {
  const n = paraNumero(valor);
  return n === null ? "—" : brl.format(n);
}

/** Moeda compacta pros eixos de grafico: "R$ 12,5 mil". */
export function formatBRLCompacto(valor: number): string {
  return valor === 0 ? "R$ 0" : brlCompacto.format(valor);
}

/** "61.090". Aceita casas decimais opcionais. */
export function formatNumber(valor: Valor, casas = 0): string {
  const n = paraNumero(valor);
  if (n === null) return "—";
  return casas > 0
    ? n.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas })
    : numero.format(n);
}

/** Percentual a partir de um numero ja em pontos percentuais: 28.6 -> "28,6%". */
export function formatPercent(valor: Valor, casas = 1): string {
  const n = paraNumero(valor);
  if (n === null) return "—";
  return `${n.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas })}%`;
}

/** Percentual a partir de fracao: 0.286 -> "28,6%". */
export function formatPercentFracao(fracao: Valor, casas = 1): string {
  const n = paraNumero(fracao);
  return n === null ? "—" : formatPercent(n * 100, casas);
}

/** "1 dia" / "2 dias". Zero usa o plural, como em portugues. */
export function plural(n: number, singular: string, pluralForma: string): string {
  return n === 1 ? singular : pluralForma;
}

/** "1 dia", "2 dias", "8 produtos" (com o numero formatado). */
export function contar(n: number, singular: string, pluralForma: string): string {
  return `${formatNumber(n)} ${plural(n, singular, pluralForma)}`;
}

// O backend grava datetime SEM fuso (naive), sempre em UTC. `new Date(str)`
// trata string sem fuso como horario LOCAL, o que exibiria o horario UTC como
// se fosse o de Brasilia. Aqui string sem fuso e lida como UTC.
const TEM_FUSO = /(Z|[+-]\d{2}:?\d{2})$/i;

function paraData(valor: string | Date): Date {
  if (valor instanceof Date) return valor;
  return new Date(TEM_FUSO.test(valor) ? valor : `${valor}Z`);
}

// Dados do seed vem com horario 00:00:00 (nao ha hora real). Nesse caso a
// data e mostrada sem hora e sem conversao de fuso (converter jogaria o dia
// para o dia anterior, as 21h).
function semHoraReal(valor: string | Date): boolean {
  return typeof valor === "string" && /T00:00:00(\.0+)?(Z|[+-]00:?00)?$/.test(valor);
}

function dataUTCDireta(valor: string): string {
  const [ano, mes, dia] = valor.slice(0, 10).split("-");
  return `${dia}/${mes}/${ano}`;
}

/** "20/11/2026". Datas "AAAA-MM-DD" puras nao passam por fuso. */
export function formatDate(valor: string | Date | null | undefined): string {
  if (!valor) return "—";
  if (typeof valor === "string" && /^\d{4}-\d{2}-\d{2}$/.test(valor)) return dataUTCDireta(valor);
  if (semHoraReal(valor)) return dataUTCDireta(valor as string);
  const d = paraData(valor);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("pt-BR", { timeZone: FUSO });
}

/** "20/11/2026 14:35" em Brasilia; so a data quando nao ha hora real. */
export function formatDateTime(valor: string | Date | null | undefined): string {
  if (!valor) return "—";
  if (semHoraReal(valor)) return formatDate(valor);
  const d = paraData(valor);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("pt-BR", {
    timeZone: FUSO,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Instante como Date (UTC quando a string nao traz fuso), pra contas de tempo. */
export function parseInstante(valor: string): Date {
  return paraData(valor);
}
