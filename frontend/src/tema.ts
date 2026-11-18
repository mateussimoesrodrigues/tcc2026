// Tema claro/escuro. O estado mora no atributo data-tema do <html> (e o CSS
// reage a ele, ver index.css); o localStorage guarda so a ESCOLHA do usuario.
// Sem escolha salva, vale o tema do sistema e acompanha as mudancas dele.
//
// O index.html tem um script minimo com a mesma regra, que roda antes da
// primeira pintura -- sem ele a pagina piscaria clara antes de escurecer.
import { useCallback, useEffect, useState } from "react";

export type Tema = "claro" | "escuro";

const CHAVE = "tema";
const CONSULTA_ESCURO = "(prefers-color-scheme: dark)";

function ehTema(valor: unknown): valor is Tema {
  return valor === "claro" || valor === "escuro";
}

function lerSalvo(): Tema | null {
  try {
    const valor = localStorage.getItem(CHAVE);
    return ehTema(valor) ? valor : null;
  } catch {
    // Modo anonimo / storage bloqueado: segue sem persistir.
    return null;
  }
}

function doSistema(): Tema {
  return window.matchMedia(CONSULTA_ESCURO).matches ? "escuro" : "claro";
}

function temaAtual(): Tema {
  const aplicado = document.documentElement.dataset.tema;
  return ehTema(aplicado) ? aplicado : (lerSalvo() ?? doSistema());
}

export function useTema(): { tema: Tema; alternar: () => void } {
  const [tema, setTema] = useState<Tema>(temaAtual);

  useEffect(() => {
    document.documentElement.dataset.tema = tema;
  }, [tema]);

  // Enquanto o usuario nao escolher, o app segue o sistema.
  useEffect(() => {
    const consulta = window.matchMedia(CONSULTA_ESCURO);
    function aoMudar() {
      if (lerSalvo() === null) setTema(doSistema());
    }
    consulta.addEventListener("change", aoMudar);
    return () => consulta.removeEventListener("change", aoMudar);
  }, []);

  const alternar = useCallback(() => {
    const proximo: Tema = tema === "escuro" ? "claro" : "escuro";
    try {
      localStorage.setItem(CHAVE, proximo);
    } catch {
      // Preferencia e conveniencia: se nao der pra salvar, vale so nesta sessao.
    }
    setTema(proximo);
  }, [tema]);

  return { tema, alternar };
}
