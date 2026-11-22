import { useEffect, useRef, useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { apiFetch } from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import logoDark from "../../assets/logo-dark.svg";
import logoMark from "../../assets/logo-mark.svg";

// Olho do campo de senha. Aberto = senha escondida (clicar mostra); cortado
// por uma barra = senha visivel (clicar esconde).
function IconeOlho({ cortado }: { cortado: boolean }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
      {cortado && <path d="M4 4l16 16" />}
    </svg>
  );
}

export default function Login() {
  const { funcionario, carregando, login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [mostrarSenha, setMostrarSenha] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [demorando, setDemorando] = useState(false);
  const [erroEmail, setErroEmail] = useState<string | null>(null);
  const [erroSenha, setErroSenha] = useState<string | null>(null);
  const inputEmail = useRef<HTMLInputElement>(null);
  const inputSenha = useRef<HTMLInputElement>(null);

  // O backend (Render, plano gratuito) dorme sem uso e a primeira chamada leva
  // varios segundos. Um GET silencioso em /health ao abrir a tela ja o acorda
  // enquanto a pessoa digita. Falha e ignorada: nao e requisito para logar.
  useEffect(() => {
    apiFetch("/health").catch(() => {});
  }, []);

  // Passou de ~10 s esperando: provavelmente o servidor ainda esta acordando.
  useEffect(() => {
    if (!enviando) return;
    const timer = setTimeout(() => setDemorando(true), 10000);
    return () => {
      clearTimeout(timer);
      setDemorando(false);
    };
  }, [enviando]);

  // Ja autenticado (ex.: clicou em "Area do funcionario" de novo com uma
  // sessao ainda valida) -- manda direto pro dashboard em vez de mostrar
  // o formulario de novo por cima da navegacao do funcionario.
  if (!carregando && funcionario) {
    return <Navigate to="/" replace />;
  }

  // Mesma regra de antes (os dois campos sao obrigatorios e o e-mail precisa
  // parecer um e-mail), mas a mensagem aparece abaixo do campo, nao no balao
  // nativo do navegador.
  function validar(): boolean {
    const emailAjustado = email.trim();
    const novoErroEmail = !emailAjustado
      ? "Informe seu e-mail."
      : !/^\S+@\S+$/.test(emailAjustado)
        ? "Informe um e-mail válido."
        : null;
    const novoErroSenha = senha ? null : "Informe sua senha.";
    setErroEmail(novoErroEmail);
    setErroSenha(novoErroSenha);
    if (novoErroEmail) inputEmail.current?.focus();
    else if (novoErroSenha) inputSenha.current?.focus();
    return !novoErroEmail && !novoErroSenha;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    if (!validar()) return;
    setEnviando(true);
    try {
      await login(email, senha);
      navigate("/");
    } catch {
      setErro("Email ou senha inválidos.");
    } finally {
      setEnviando(false);
    }
  }

  // Tela dividida: painel de marca (fundo escuro, por isso a logo "dark") a
  // esquerda e o formulario a direita. Sem a barra do topo: o ConsoleShell a
  // esconde enquanto nao ha sessao (ver .sem-sessao no App.css).
  return (
    <div className="login-split">
      <section className="login-painel-marca">
        <img className="login-logo" src={logoDark} alt="Precix.AI" />
        <h1 className="login-headline">Preço certo, na hora certa.</h1>
        <p className="login-descricao">
          Gestão de precificação com IA para o varejo físico — do estoque ao display da prateleira.
        </p>
        {/* Simbolo gigante e quase transparente, cortado pela borda do painel. */}
        <img className="login-deco" src={logoMark} alt="" aria-hidden="true" />
      </section>

      <section className="login-painel-form">
        <div className="login-form-wrap">
          <h2 className="login-titulo">Entrar</h2>
          <p className="login-sub">Acesse o painel com sua conta de funcionário.</p>
          <form onSubmit={handleSubmit} className="login-form" noValidate>
            <label htmlFor="login-email">E-mail</label>
            <input
              id="login-email"
              ref={inputEmail}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="nome@loja.com.br"
              autoComplete="username"
              required
              aria-invalid={erroEmail ? true : undefined}
              aria-describedby={erroEmail ? "login-email-erro" : undefined}
            />
            {erroEmail && (
              <p id="login-email-erro" className="login-erro-campo" role="alert">
                {erroEmail}
              </p>
            )}
            <label htmlFor="login-senha">Senha</label>
            <div className="login-senha">
              <input
                id="login-senha"
                ref={inputSenha}
                type={mostrarSenha ? "text" : "password"}
                value={senha}
                onChange={(e) => setSenha(e.target.value)}
                autoComplete="current-password"
                required
                aria-invalid={erroSenha ? true : undefined}
                aria-describedby={erroSenha ? "login-senha-erro" : undefined}
              />
              <button
                type="button"
                className="login-olho"
                onClick={() => setMostrarSenha((v) => !v)}
                aria-label={mostrarSenha ? "Ocultar senha" : "Mostrar senha"}
                aria-pressed={mostrarSenha}
              >
                <IconeOlho cortado={mostrarSenha} />
              </button>
            </div>
            {erroSenha && (
              <p id="login-senha-erro" className="login-erro-campo" role="alert">
                {erroSenha}
              </p>
            )}
            {erro && <p className="erro">{erro}</p>}
            <button type="submit" className="login-entrar" disabled={enviando}>
              {enviando ? "Entrando…" : "Entrar"}
            </button>
            <p className="login-aviso-demora" role="status">
              {demorando ? "Servidor iniciando, isso pode levar alguns segundos." : ""}
            </p>
          </form>
          <p className="login-nota">Acesso restrito à equipe da loja.</p>
        </div>
      </section>
    </div>
  );
}
