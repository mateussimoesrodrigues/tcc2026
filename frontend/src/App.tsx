import { NavLink, Route, Routes } from "react-router-dom";

import Scanner from "./cliente/pages/Scanner";
import Carrinho from "./cliente/pages/Carrinho";
import Checkout from "./cliente/pages/Checkout";
import Login from "./funcionario/pages/Login";
import Caixa from "./funcionario/pages/Caixa";
import DashboardEstoque from "./funcionario/pages/DashboardEstoque";
import Indicadores from "./funcionario/pages/Indicadores";
import Promocoes from "./funcionario/pages/Promocoes";
import Produtos from "./funcionario/pages/Produtos";
import Displays from "./funcionario/pages/Displays";
import HistoricoPrecos from "./funcionario/pages/HistoricoPrecos";
import ProtectedRoute from "./funcionario/components/ProtectedRoute";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { CartProvider } from "./context/CartContext";

import "./App.css";

// Marca da barra superior: barras ascendentes (preco/volume) + nome.
// aria-hidden no SVG porque o nome ao lado ja e o rotulo textual.
function Marca({ contexto }: { contexto?: string }) {
  return (
    <div className="app-brand">
      <svg className="app-brand-mark" viewBox="0 0 24 24" aria-hidden="true">
        <rect x="1.5" y="13" width="5" height="8" rx="1" opacity="0.55" />
        <rect x="9.5" y="8" width="5" height="13" rx="1" opacity="0.8" />
        <rect x="17.5" y="3" width="5" height="18" rx="1" />
      </svg>
      <span className="app-brand-nome">Precificação</span>
      {contexto && <span className="app-nav-tag">{contexto}</span>}
    </div>
  );
}

function ClienteLayout() {
  return (
    <CartProvider>
      <div className="app-shell">
        <nav className="app-nav">
          <Marca />
          <NavLink to="/">Escanear</NavLink>
          <NavLink to="/carrinho">Carrinho</NavLink>
          <span className="app-nav-spacer" />
          <NavLink to="/funcionario/login">Área do funcionário</NavLink>
        </nav>
        <main>
          <Routes>
            <Route path="/" element={<Scanner />} />
            <Route path="/carrinho" element={<Carrinho />} />
            <Route path="/checkout" element={<Checkout />} />
          </Routes>
        </main>
      </div>
    </CartProvider>
  );
}

function FuncionarioNav() {
  const { funcionario, logout } = useAuth();
  if (!funcionario) return null;

  return (
    <nav className="app-nav">
      <Marca contexto="console" />
      {/* Caixa vem primeiro: e a tela mais usada no balcao, atendendo
          cliente atras de cliente. */}
      <NavLink to="/funcionario/caixa">Caixa</NavLink>
      <NavLink to="/funcionario" end>Estoque</NavLink>
      <NavLink to="/funcionario/produtos">Produtos</NavLink>
      <NavLink to="/funcionario/promocoes">Promoções</NavLink>
      <NavLink to="/funcionario/indicadores">Indicadores</NavLink>
      <NavLink to="/funcionario/historico-precos">Histórico</NavLink>
      <NavLink to="/funcionario/displays">Displays</NavLink>
      <span className="app-nav-spacer" />
      <span className="app-nav-usuario">{funcionario.nome}</span>
      <button type="button" className="link-button" onClick={logout}>
        Sair
      </button>
    </nav>
  );
}

function FuncionarioLayout() {
  return (
    <AuthProvider>
      <div className="app-shell">
        <FuncionarioNav />
        <main>
          <Routes>
            {/* Caminhos relativos aqui (nao "/funcionario/..."): este
                <Routes> ja esta aninhado dentro da rota pai "/funcionario/*"
                (ver <App> abaixo) -- absolutos nao casam de forma
                confiavel nesse padrao e o <Routes> so renderiza em
                branco, sem erro nenhum no console. */}
            <Route path="login" element={<Login />} />
            <Route
              index
              element={
                <ProtectedRoute>
                  <DashboardEstoque />
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
            <Route
              path="produtos"
              element={
                <ProtectedRoute>
                  <Produtos />
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
    </AuthProvider>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/funcionario/*" element={<FuncionarioLayout />} />
      <Route path="/*" element={<ClienteLayout />} />
    </Routes>
  );
}
