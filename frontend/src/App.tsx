import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Navigate, Route, Routes, useParams } from "react-router-dom";

import Scanner from "./cliente/pages/Scanner";
import Carrinho from "./cliente/pages/Carrinho";
import Checkout from "./cliente/pages/Checkout";
import Login from "./funcionario/pages/Login";
import Caixa from "./funcionario/pages/Caixa";
import Indicadores from "./funcionario/pages/Indicadores";
import Promocoes from "./funcionario/pages/Promocoes";
import Produtos from "./funcionario/pages/Produtos";
import Entradas from "./funcionario/pages/Entradas";
import Precificacao from "./funcionario/pages/Precificacao";
import Displays from "./funcionario/pages/Displays";
import HistoricoPrecos from "./funcionario/pages/HistoricoPrecos";
import ProtectedRoute from "./funcionario/components/ProtectedRoute";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { CartProvider } from "./context/CartContext";

import { useTema } from "./tema";
import logoDark from "./assets/logo-dark.svg";
import logoMark from "./assets/logo-mark.svg";

import "./App.css";

// Marca da barra superior (fundo escuro, por isso a logo "dark"). Em tela
// estreita o CSS troca a logo completa so pelo simbolo (ver .app-brand-logo
// e .app-brand-mark no App.css); o simbolo e decorativo, entao alt vazio.
function Marca() {
  return (
    <div className="app-brand">
      <img className="app-brand-logo" src={logoDark} alt="Precix.AI" />
      <img className="app-brand-mark" src={logoMark} alt="" />
    </div>
  );
}

function ClienteLayout() {
  return (
    <CartProvider>
      <div className="app-shell">
        <nav className="app-nav">
          <Marca />
          <NavLink to="/cliente" end>Escanear</NavLink>
          <NavLink to="/cliente/carrinho">Carrinho</NavLink>
          <span className="app-nav-spacer" />
          <NavLink to="/login">Área do funcionário</NavLink>
        </nav>
        <main>
          {/* Caminhos relativos: este <Routes> esta aninhado na rota pai
              "/cliente/*" -- absolutos ("/carrinho") deixariam de casar
              e a tela renderizaria em branco, sem erro no console. */}
          <Routes>
            <Route index element={<Scanner />} />
            <Route path="carrinho" element={<Carrinho />} />
            <Route path="checkout" element={<Checkout />} />
          </Routes>
        </main>
      </div>
    </CartProvider>
  );
}

// Itens do menu lateral do console. Em lista (e nao em JSX solto) porque
// o mesmo array vira os links e o alvo do fechamento automatico no mobile.
// "Caixa" vem primeiro: e a tela mais usada no balcao, atendendo cliente
// atras de cliente. `end` so em Produtos, que mora na rota indice "/" --
// sem ele o link ficaria ativo em todas as outras.
const MENU_FUNCIONARIO: { to: string; rotulo: string; end?: boolean }[] = [
  { to: "/caixa", rotulo: "Caixa" },
  { to: "/", rotulo: "Produtos", end: true },
  { to: "/entradas", rotulo: "Entradas" },
  { to: "/precificacao", rotulo: "Margens" },
  { to: "/promocoes", rotulo: "Promoções" },
  { to: "/indicadores", rotulo: "Indicadores" },
  { to: "/historico-precos", rotulo: "Histórico" },
  { to: "/displays", rotulo: "Displays" },
];

// Abaixo desta largura a barra lateral vira gaveta sobreposta (com fundo
// escurecido) em vez de dividir espaco com o conteudo. Precisa casar com o
// mesmo valor no @media de .app-sidebar no App.css.
const LARGURA_GAVETA = "(max-width: 900px)";
const CHAVE_MENU = "console:menu-aberto";

function ehGaveta() {
  return window.matchMedia(LARGURA_GAVETA).matches;
}

// Lembra a escolha entre sessoes: quem trabalha no balcao com a tela
// pequena deixa o menu fechado o dia todo e nao quer reabrir/refechar a
// cada F5. Sem preferencia salva, abre no desktop e fecha na gaveta.
function estadoInicialMenu() {
  try {
    const salvo = localStorage.getItem(CHAVE_MENU);
    if (salvo !== null) return salvo === "true";
  } catch {
    // Modo anonimo / storage bloqueado: cai no padrao por largura.
  }
  return !ehGaveta();
}

function IconeMenu({ aberto }: { aberto: boolean }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {aberto ? (
        <path d="M6 6l12 12M18 6L6 18" />
      ) : (
        <path d="M3.5 7h17M3.5 12h17M3.5 17h17" />
      )}
    </svg>
  );
}

// Iniciais do avatar: primeira letra do primeiro nome + primeira letra do
// ultimo sobrenome ("Mateus Souza Simões" -> "MS"). Nome de uma palavra so
// vira uma letra so ("Administrador" -> "A").
function iniciais(nome: string): string {
  const partes = nome.trim().split(/\s+/).filter(Boolean);
  if (partes.length === 0) return "?";
  // Array.from: pega o caractere inteiro mesmo se for um par substituto.
  const inicial = (palavra: string) => Array.from(palavra)[0].toLocaleUpperCase("pt-BR");
  if (partes.length === 1) return inicial(partes[0]);
  return inicial(partes[0]) + inicial(partes[partes.length - 1]);
}

function IconeSair() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M9 4H5.5A1.5 1.5 0 0 0 4 5.5v13A1.5 1.5 0 0 0 5.5 20H9" />
      <path d="M16 8l4 4-4 4M20 12H9" />
    </svg>
  );
}

function IconeSol() {
  return (
    <svg className="app-tema-sol" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M18.7 5.3l-1.6 1.6M6.9 17.1l-1.6 1.6" />
    </svg>
  );
}

function IconeLua() {
  return (
    <svg className="app-tema-lua" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5a8.5 8.5 0 1 0 10.7 10.7z" />
    </svg>
  );
}

// Perfil no canto direito da barra: a bolinha com as iniciais abre um menu
// com o nome, o email, o interruptor de tema e o "Sair". Fecha ao clicar
// fora, com Esc e ao sair (alternar o tema NAO fecha: o efeito fica a vista).
function MenuPerfil({ nome, email, onSair }: { nome: string; email: string; onSair: () => void }) {
  const [aberto, setAberto] = useState(false);
  const { tema, alternar } = useTema();
  const raiz = useRef<HTMLDivElement>(null);
  const botao = useRef<HTMLButtonElement>(null);
  const itemTema = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!aberto) return;
    // Teclado: ao abrir, o foco vai pro primeiro item (o tema, e nao o "Sair":
    // um Enter sem querer troca o tema em vez de derrubar a sessao).
    itemTema.current?.focus();
    function aoClicarFora(e: PointerEvent) {
      if (raiz.current && !raiz.current.contains(e.target as Node)) setAberto(false);
    }
    function aoTeclar(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setAberto(false);
        botao.current?.focus();
      }
    }
    document.addEventListener("pointerdown", aoClicarFora);
    window.addEventListener("keydown", aoTeclar);
    return () => {
      document.removeEventListener("pointerdown", aoClicarFora);
      window.removeEventListener("keydown", aoTeclar);
    };
  }, [aberto]);

  return (
    <div className="app-perfil" ref={raiz}>
      <button
        ref={botao}
        type="button"
        className="app-perfil-botao"
        onClick={() => setAberto((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={aberto}
        aria-label={`Menu do perfil de ${nome}`}
      >
        {iniciais(nome)}
      </button>
      {aberto && (
        <div className="app-perfil-menu" role="menu">
          <div className="app-perfil-id">
            <strong>{nome}</strong>
            <span>{email}</span>
          </div>
          <button
            ref={itemTema}
            type="button"
            role="menuitemcheckbox"
            aria-checked={tema === "escuro"}
            aria-label="Modo escuro"
            className="app-tema"
            onClick={alternar}
          >
            <IconeSol />
            <span className="app-tema-chave" aria-hidden="true">
              <span className="app-tema-bola" />
            </span>
            <IconeLua />
          </button>
          <button
            type="button"
            role="menuitem"
            className="app-perfil-sair"
            onClick={() => {
              setAberto(false);
              onSair();
            }}
          >
            <IconeSair />
            Sair
          </button>
        </div>
      )}
    </div>
  );
}

function ConsoleShell() {
  const { funcionario, carregando, logout } = useAuth();
  const [menuAberto, setMenuAberto] = useState(estadoInicialMenu);

  const fecharSeGaveta = useCallback(() => {
    if (ehGaveta()) setMenuAberto(false);
  }, []);

  function alternarMenu() {
    setMenuAberto((atual) => {
      const proximo = !atual;
      try {
        localStorage.setItem(CHAVE_MENU, String(proximo));
      } catch {
        // Preferencia e conveniencia: se nao der pra salvar, segue sem.
      }
      return proximo;
    });
  }

  // Esc fecha a gaveta -- ela cobre o conteudo no mobile, entao precisa da
  // mesma saida de teclado que um dialogo.
  useEffect(() => {
    if (!menuAberto) return;
    function aoTeclar(e: KeyboardEvent) {
      if (e.key === "Escape") fecharSeGaveta();
    }
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [menuAberto, fecharSeGaveta]);

  // Na tela de login nao ha menu: sem funcionario autenticado o console
  // renderiza so a barra do topo e o formulario.
  const logado = funcionario !== null;
  const mostrarMenu = logado && menuAberto;
  // Sem sessao (e ja sem carregar): so existe a tela de login, que e uma
  // tela cheia dividida e dispensa a barra do topo e o padding do <main>.
  const semSessao = !logado && !carregando;

  return (
    <div
      className={`app-shell app-console${mostrarMenu ? " menu-aberto" : ""}${semSessao ? " sem-sessao" : ""}`}
    >
      <header className="app-nav">
        {logado && (
          <button
            type="button"
            className="app-menu-toggle"
            onClick={alternarMenu}
            aria-label={menuAberto ? "Ocultar menu de navegação" : "Exibir menu de navegação"}
            aria-expanded={menuAberto}
            aria-controls="menu-lateral"
          >
            <IconeMenu aberto={menuAberto} />
          </button>
        )}
        <Marca />
        <span className="app-nav-spacer" />
        {logado && (
          <>
            <span className="app-nav-usuario">{funcionario.nome}</span>
            <MenuPerfil nome={funcionario.nome} email={funcionario.email} onSair={logout} />
          </>
        )}
      </header>

      <div className="app-corpo">
        {logado && (
          <>
            {/* aria-hidden + inert quando fechado: a barra continua no DOM
                (pra animar a abertura), mas sai do foco e do leitor de tela
                -- senao daria pra tabular pra dentro de um menu invisivel. */}
            <aside
              id="menu-lateral"
              className="app-sidebar"
              aria-hidden={!menuAberto}
              inert={!menuAberto}
            >
              <nav className="app-sidebar-nav" aria-label="Seções do console">
                {MENU_FUNCIONARIO.map(({ to, rotulo, end }) => (
                  <NavLink key={to} to={to} end={end} onClick={fecharSeGaveta}>
                    {rotulo}
                  </NavLink>
                ))}
              </nav>
            </aside>
            {/* So visivel no modo gaveta (ver App.css): fecha ao tocar fora. */}
            <button
              type="button"
              className="app-sidebar-backdrop"
              tabIndex={-1}
              aria-hidden="true"
              onClick={fecharSeGaveta}
            />
          </>
        )}
        <main>
          <Routes>
            {/* Caminhos relativos aqui (nao "/caixa", "/produtos"...):
                este <Routes> ja esta aninhado dentro da rota pai "/*"
                (ver <App> abaixo) -- absolutos nao casam de forma
                confiavel nesse padrao e o <Routes> so renderiza em
                branco, sem erro nenhum no console. */}
            <Route path="login" element={<Login />} />
            {/* Catalogo e estoque na mesma tela: as duas listavam os
                mesmos produtos e o funcionario trocava de aba pra responder
                perguntas sobre a mesma linha. */}
            <Route
              index
              element={
                <ProtectedRoute>
                  <Produtos />
                </ProtectedRoute>
              }
            />
            <Route
              path="caixa"
              element={
                <ProtectedRoute>
                  <Caixa />
                </ProtectedRoute>
              }
            />
            {/* Endereco antigo da tela de produtos: mantido como
                redirecionamento pra favoritos nao quebrarem. */}
            <Route path="produtos" element={<Navigate to="/" replace />} />
            <Route
              path="entradas"
              element={
                <ProtectedRoute>
                  <Entradas />
                </ProtectedRoute>
              }
            />
            <Route
              path="precificacao"
              element={
                <ProtectedRoute>
                  <Precificacao />
                </ProtectedRoute>
              }
            />
            <Route
              path="promocoes"
              element={
                <ProtectedRoute>
                  <Promocoes />
                </ProtectedRoute>
              }
            />
            <Route
              path="indicadores"
              element={
                <ProtectedRoute>
                  <Indicadores />
                </ProtectedRoute>
              }
            />
            <Route
              path="historico-precos"
              element={
                <ProtectedRoute>
                  <HistoricoPrecos />
                </ProtectedRoute>
              }
            />
            <Route
              path="displays"
              element={
                <ProtectedRoute>
                  <Displays />
                </ProtectedRoute>
              }
            />
          </Routes>
        </main>
      </div>
    </div>
  );
}

function FuncionarioLayout() {
  // ConsoleShell precisa ficar dentro do provider: e ele que chama
  // useAuth() pra saber se ja existe funcionario logado.
  return (
    <AuthProvider>
      <ConsoleShell />
    </AuthProvider>
  );
}

// O console morou em "/funcionario/*" ate aqui. Em vez de quebrar os
// enderecos ja salvos, o prefixo antigo vira um redirecionamento que
// preserva o resto do caminho: "/funcionario/caixa" cai em "/caixa".
function RedirecionarConsoleAntigo() {
  const resto = useParams()["*"] ?? "";
  return <Navigate to={`/${resto}`} replace />;
}

export default function App() {
  return (
    <Routes>
      {/* Area do cliente (scanner/carrinho/checkout): fica sob "/cliente"
          de proposito, sem link a partir do console -- so chega quem abre
          esse endereco direto. */}
      <Route path="/cliente/*" element={<ClienteLayout />} />

      <Route path="/funcionario/*" element={<RedirecionarConsoleAntigo />} />

      {/* Console como aplicacao principal: "/" e a tela de produtos, ou o
          login quando nao ha sessao (ver ProtectedRoute). */}
      <Route path="/*" element={<FuncionarioLayout />} />
    </Routes>
  );
}
