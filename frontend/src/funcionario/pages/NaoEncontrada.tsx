import { useEffect } from "react";
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import logoDark from "../../assets/logo-dark.svg";
import Skeleton from "../../components/Skeleton";

// Rota que nao existe. Sem sessao nao ha painel para onde voltar: vai pro login.
// Com sessao, mostra uma pagina simples com o caminho de volta. O cartao e
// grafite nos dois temas (a logo "dark" tem o lima, que so entra sobre escuro).
export default function NaoEncontrada() {
  const { funcionario, carregando } = useAuth();

  useEffect(() => {
    if (!funcionario) return;
    const anterior = document.title;
    document.title = "Página não encontrada · Precix.AI";
    return () => {
      document.title = anterior;
    };
  }, [funcionario]);

  if (carregando) return <Skeleton linhas={3} />;
  if (!funcionario) return <Navigate to="/login" replace />;

  return (
    <div className="pagina-404">
      <img className="pagina-404-logo" src={logoDark} alt="Precix.AI" />
      <p className="pagina-404-codigo" aria-hidden="true">
        404
      </p>
      <h1>Página não encontrada</h1>
      <p>O endereço que você abriu não existe ou foi movido.</p>
      <Link to="/" className="pagina-404-botao">
        Ir para o painel
      </Link>
    </div>
  );
}
