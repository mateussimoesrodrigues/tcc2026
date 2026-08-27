import { NavLink, Route, Routes } from "react-router-dom";

import Scanner from "./cliente/pages/Scanner";
import Carrinho from "./cliente/pages/Carrinho";
import Checkout from "./cliente/pages/Checkout";
import Login from "./funcionario/pages/Login";
import DashboardEstoque from "./funcionario/pages/DashboardEstoque";
import Promocoes from "./funcionario/pages/Promocoes";
import Produtos from "./funcionario/pages/Produtos";
import Displays from "./funcionario/pages/Displays";
import HistoricoPrecos from "./funcionario/pages/HistoricoPrecos";
import ProtectedRoute from "./funcionario/components/ProtectedRoute";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { CartProvider } from "./context/CartContext";

import "./App.css";

function ClienteLayout() {
  return (
    <CartProvider>
      <div className="app-shell">
        <nav className="app-nav">
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
      <NavLink to="/funcionario" end>Estoque</NavLink>
      <NavLink to="/funcionario/produtos">Produtos</NavLink>
      <NavLink to="/funcionario/promocoes">Promoções</NavLink>
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
