import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { apiFetch } from "../api/client";

export interface Funcionario {
  id: number;
  nome: string;
  email: string;
  papel: "admin" | "operador";
  ativo: boolean;
}

interface AuthContextValue {
  funcionario: Funcionario | null;
  carregando: boolean;
  login: (email: string, senha: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);
const TOKEN_KEY = "funcionario_token";
const API_URL = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [funcionario, setFuncionario] = useState<Funcionario | null>(null);
  const [carregando, setCarregando] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) {
      setCarregando(false);
      return;
    }
    apiFetch<Funcionario>("/auth/me", { auth: true })
      .then(setFuncionario)
      .catch(() => localStorage.removeItem(TOKEN_KEY))
      .finally(() => setCarregando(false));
  }, []);

  async function login(email: string, senha: string) {
    // O login usa OAuth2PasswordRequestForm no backend, que espera
    // application/x-www-form-urlencoded (nao JSON) com username/password.
    const resposta = await fetch(`${API_URL}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ username: email, password: senha }),
    });
    if (!resposta.ok) {
      throw new Error("Email ou senha invalidos");
    }
    const dados = await resposta.json();
    localStorage.setItem(TOKEN_KEY, dados.access_token);
    setFuncionario(dados.funcionario);
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    setFuncionario(null);
  }

  return (
    <AuthContext.Provider value={{ funcionario, carregando, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth precisa ser usado dentro de <AuthProvider>");
  return ctx;
}
