import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";

export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const { funcionario, carregando } = useAuth();

  if (carregando) return <div className="page">Carregando...</div>;
  if (!funcionario) return <Navigate to="/login" replace />;

  return <>{children}</>;
}
