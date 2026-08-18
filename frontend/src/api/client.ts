// Client HTTP central: toda chamada ao backend passa por aqui.
// A URL base vem de VITE_API_URL (.env do frontend); em dev aponta pro
// uvicorn local (http://127.0.0.1:8000).

const API_URL = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

const CART_SESSION_HEADER = "X-Cart-Session";
const CART_SESSION_STORAGE_KEY = "cart_session_id";

function getCartSessionId(): string | null {
  return localStorage.getItem(CART_SESSION_STORAGE_KEY);
}

export function setCartSessionId(id: string): void {
  localStorage.setItem(CART_SESSION_STORAGE_KEY, id);
}

function getAuthToken(): string | null {
  return localStorage.getItem("funcionario_token");
}

interface RequestOptions extends RequestInit {
  auth?: boolean; // inclui o JWT do funcionario
  cartSession?: boolean; // inclui o header de sessao de carrinho do cliente
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");

  if (options.auth) {
    const token = getAuthToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }

  if (options.cartSession) {
    const sessionId = getCartSessionId();
    if (sessionId) headers.set(CART_SESSION_HEADER, sessionId);
  }

  const response = await fetch(`${API_URL}${path}`, { ...options, headers });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Erro ${response.status} em ${path}: ${body}`);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
