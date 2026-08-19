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
    <div className="page">
      <h1>Login do funcionário</h1>
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
  );
}
