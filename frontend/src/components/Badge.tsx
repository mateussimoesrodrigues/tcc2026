import type { ReactNode } from "react";

export type TomBadge = "neutral" | "primary" | "promo" | "warning" | "danger";

// `promo` e o lima: so para promocao ativa / preco que caiu. Os demais tons
// nao usam lima de proposito.
export default function Badge({
  tone = "neutral",
  children,
  title,
}: {
  tone?: TomBadge;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  );
}
