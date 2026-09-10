import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";

export default function Login() {
  const { funcionario, carregando, login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  // Ja autenticado (ex.: clicou em "Area do funcionario" de novo com uma
  // sessao ainda valida) -- manda direto pro dashboard em vez de mostrar
  // o formulario de novo por cima da navegacao do funcionario.
  if (!carregando && funcionario) {
    return <Navigate to="/funcionario" replace />;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    setEnviando(true);
    try {
      await login(email, senha);
      navigate("/funcionario");
    } catch {
      setErro("Email ou senha inválidos.");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="page page-login">
      <div className="login-marca">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <rect x="1.5" y="13" width="5" height="8" rx="1" opacity="0.55" />
          <rect x="9.5" y="8" width="5" height="13" rx="1" opacity="0.8" />
          <rect x="17.5" y="3" width="5" height="18" rx="1" />
        </svg>
        <span>
          Precificação <em>Inteligente</em>
        </span>
      </div>
      <div className="login-card">
        <h1>Login do funcionário</h1>
        <p className="login-sub">Acesso restrito à equipe da loja.</p>
        <form onSubmit={handleSubmit} className="form">
          <label>
            Email
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label>
            Senha
            <input
              type="password"
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          {erro && <p className="erro">{erro}</p>}
          <button type="submit" disabled={enviando}>
            {enviando ? "Entrando..." : "Entrar"}
          </button>
        </form>
      </div>
    </div>
  );
}
