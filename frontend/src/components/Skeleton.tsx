// Placeholder de carregamento. `tabela` imita linhas de tabela, `cards` uma
// grade de KPIs. role="status" + texto so para leitor de tela: quem enxerga ve
// o esqueleto, quem nao enxerga ouve "Carregando".
export default function Skeleton({
  variante = "tabela",
  linhas = 6,
  rotulo = "Carregando",
}: {
  variante?: "tabela" | "cards";
  linhas?: number;
  rotulo?: string;
}) {
  if (variante === "cards") {
    return (
      <div className="skeleton skeleton-cards" role="status" aria-live="polite">
        <span className="sr-only">{rotulo}...</span>
        {Array.from({ length: Math.min(linhas, 4) }, (_, i) => (
          <div key={i} className="skeleton-card" aria-hidden="true">
            <i className="skeleton-bloco skeleton-linha-curta" />
            <i className="skeleton-bloco skeleton-linha-valor" />
            <i className="skeleton-bloco skeleton-linha-media" />
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="skeleton skeleton-tabela" role="status" aria-live="polite">
      <span className="sr-only">{rotulo}...</span>
      <div className="skeleton-cabecalho" aria-hidden="true">
        <i className="skeleton-bloco" />
      </div>
      {Array.from({ length: linhas }, (_, i) => (
        <div key={i} className="skeleton-linha" aria-hidden="true">
          <i className="skeleton-bloco skeleton-col-larga" />
          <i className="skeleton-bloco skeleton-col-media" />
          <i className="skeleton-bloco skeleton-col-curta" />
          <i className="skeleton-bloco skeleton-col-curta" />
        </div>
      ))}
    </div>
  );
}
