import { NavLink, Route, Routes } from "react-router-dom";

import Scanner from "./cliente/pages/Scanner";
import Carrinho from "./cliente/pages/Carrinho";
import Checkout from "./cliente/pages/Checkout";
import Login from "./funcionario/pages/Login";
import DashboardEstoque from "./funcionario/pages/DashboardEstoque";
import Promocoes from "./funcionario/pages/Promocoes";
import Produtos from "./funcionario/pages/Produtos";
import HistoricoPrecos from "./funcionario/pages/HistoricoPrecos";

import "./App.css";

function ClienteLayout() {
  return (
    <div className="app-shell">
      <nav className="app-nav">
        <NavLink to="/">Escanear</NavLink>
        <NavLink to="/carrinho">Carrinho</NavLink>
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<Scanner />} />
          <Route path="/carrinho" element={<Carrinho />} />
          <Route path="/checkout" element={<Checkout />} />
        </Routes>
      </main>
    </div>
  );
}

function FuncionarioLayout() {
  return (
    <div className="app-shell">
      <nav className="app-nav">
        <NavLink to="/funcionario">Estoque</NavLink>
        <NavLink to="/funcionario/produtos">Produtos</NavLink>
        <NavLink to="/funcionario/promocoes">Promoções</NavLink>
        <NavLink to="/funcionario/historico-precos">Histórico</NavLink>
      </nav>
      <main>
        <Routes>
          <Route path="/funcionario/login" element={<Login />} />
          <Route path="/funcionario" element={<DashboardEstoque />} />
          <Route path="/funcionario/produtos" element={<Produtos />} />
          <Route path="/funcionario/promocoes" element={<Promocoes />} />
          <Route path="/funcionario/historico-precos" element={<HistoricoPrecos />} />
        </Routes>
      </main>
    </div>
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
