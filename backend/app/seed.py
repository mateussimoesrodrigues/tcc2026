"""Seed unico do catalogo inicial + historico de vendas simulado.

Roda uma vez (pode rodar de novo, e idempotente: limpa e repopula) para
deixar o banco (Neon ou SQLite local) com:

- categorias do armarinho
- produtos: os 28 itens reais da planilha de precos da loja + ~27 itens
  adicionais plausiveis das mesmas marcas/fornecedores, pra termos um
  catalogo mais robusto pra demonstrar o sistema
- codigos de barras (e um QR interno extra em alguns produtos, pra
  demonstrar suporte a multiplos codigos por produto)
- estoque atual -- alguns produtos de proposito abaixo do limite baixo
  (5 unidades), pra testar o alerta de estoque baixo na Fase 2
- historico de vendas simulado dos ultimos 90 dias (movimentacao_estoque),
  com produtos "rapidos", "medios" e "lentos" (parados). E a base de dados
  real usada pelas regras da IA de promocoes na Fase 4 (giro, dias sem
  venda, estoque parado).

Uso:
    cd backend
    ./venv/Scripts/python.exe -m app.seed
"""
from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_senha
from app.models import (
    CarrinhoItem,
    Categoria,
    Estoque,
    Funcionario,
    HistoricoPreco,
    MovimentacaoEstoque,
    Pedido,
    PedidoItem,
    PromocaoSugestao,
    Produto,
    ProdutoCodigo,
    SessaoCarrinho,
)
from app.models.funcionario import PapelFuncionario
from app.models.movimentacao_estoque import TipoMovimentacao
from app.models.produto_codigo import TipoCodigo
from app.services.stock_service import LIMITE_ESTOQUE_BAIXO_PADRAO

# Credenciais do admin padrao criado pelo seed -- so para desenvolvimento/
# demonstracao do TCC. Troque a senha (ou desative o usuario) antes de
# qualquer uso real.
ADMIN_EMAIL = "admin@loja.com"
ADMIN_SENHA = "admin123"

RNG_SEED = 42
JANELA_DIAS = 90
LIMITE_ESTOQUE_BAIXO = LIMITE_ESTOQUE_BAIXO_PADRAO
HOJE = datetime.now(UTC).replace(tzinfo=None)  # coluna do banco e "sem timezone"

# ---------------------------------------------------------------------------
# 1. Categorias
# ---------------------------------------------------------------------------
CATEGORIAS = [
    "Colas",
    "Vernizes",
    "Tintas",
    "Aviamentos",
    "Utensilios e Ferramentas",
    "Materiais de Artesanato",
]

# ---------------------------------------------------------------------------
# 2. Produtos reais da planilha da loja (categoria, nome, marca, tamanho,
#    codigo de barras real, preco normal, preco com desconto ja praticado)
# ---------------------------------------------------------------------------
PRODUTOS_ORIGINAIS = [
    ("Colas", "Cola Pano", "Gliart", "100g", "7896576331634", "19.95", "15.96"),
    ("Colas", "Cola Pano", "Gliart", "35g", "7896576331050", "7.50", "6.00"),
    ("Colas", "Cola Pano", "Acrilex", "250g", "7891153168258", "33.50", "26.80"),
    ("Colas", "Cola Pano", "Acrilex", "37g", "7891153168128", "6.25", "5.00"),
    ("Colas", "Cola Pano", "Acrilex", "35g", "7891153168401", "6.50", "5.20"),
    ("Colas", "Cola Permanente", "Acrilex", "37g", "7891153162409", "7.30", "5.84"),
    ("Colas", "Cola Universal", "Gliart", "100g", "7896576352536", "19.25", "15.40"),
    ("Colas", "Cola EPS / EVA", "Gliart", "100g", "7896576356848", "12.95", "10.36"),
    ("Colas", "Cola EVA e Isopor", "Acrilex", "90g", "7891153067247", "14.95", "11.96"),
    ("Colas", "Cola de Silicone", "Gliart", "100g", "7896576352499", "17.25", "13.80"),
    ("Colas", "Cola de Silicone", "TekBond", "100g", "7898472250503", "15.40", "12.32"),
    ("Colas", "Cola de Silicone", "TekBond", "51g", "7898472250305", "10.90", "8.72"),
    ("Colas", "Cola de Silicone", "TekBond", "25g", "7898472250107", "6.50", "5.20"),
    ("Vernizes", "Verniz Vitral", "Acrilex", "250ml", "7891153006154", "79.95", "63.96"),
    ("Vernizes", "Verniz Vitral", "Acrilex", "100ml", "7891153081793", "33.40", "26.72"),
    ("Vernizes", "Verniz Acrilico Brilhante", "Acrilex", "250ml", "7891153012605", "33.50", "26.80"),
    ("Vernizes", "Verniz Acrilico Brilhante", "Acrilex", "100ml", "7891153150109", "16.75", "13.40"),
    ("Vernizes", "Verniz Acrilico Fosco", "Acrilex", "250ml", "7891153012568", "28.50", "22.80"),
    ("Vernizes", "Verniz Acrilico Fosco", "Acrilex", "100ml", "7891153169101", "15.75", "12.60"),
    ("Aviamentos", "Ziper Tratorado", "NYBC", "1 metro", "7890000030854", "9.95", "7.96"),
    ("Aviamentos", "Ziper n5", "NYBC", "1 metro", "9990000008544", "2.50", "2.00"),
    ("Tintas", "Tinta Spray", "NOU", "400ml", "7996087700503", "34.99", "27.99"),
    ("Tintas", "Tinta PVA", "Daiara", "500ml", "7899103513608", "44.99", "35.99"),
    ("Tintas", "Tinta PVA", "Daiara", "250ml", "7899103550504", "23.74", "18.99"),
    ("Tintas", "Tinta PVA", "Daiara", "37ml", "7899103571424", "5.50", "4.40"),
    ("Materiais de Artesanato", "Fio Amigurumi", "Circulo", "254 metros", "7891113010494", "18.74", "14.99"),
    ("Utensilios e Ferramentas", "Tesoura Multiuso", "Acrilex", "1 unidade", "7891153067148", "21.90", "17.52"),
    ("Utensilios e Ferramentas", "Frasco para cola ponta agulha", "Lanmax", "1 unidade", "9990000007929", "11.95", "9.56"),
]

# ---------------------------------------------------------------------------
# 3. Produtos adicionais (mesmas marcas/fornecedores), sem codigo real --
#    o codigo de barras e gerado (EAN-13 valido) pelo script.
# ---------------------------------------------------------------------------
PRODUTOS_NOVOS = [
    ("Colas", "Cola Quente Bastao Grosso", "TekBond", "500g", "24.90"),
    ("Colas", "Cola Isopor e EVA", "Gliart", "500g", "29.90"),
    ("Colas", "Cola Branca Escolar", "Acrilex", "90g", "4.50"),
    ("Vernizes", "Verniz Craquele", "Acrilex", "100ml", "24.90"),
    ("Vernizes", "Verniz Vitral Incolor", "Acrilex", "500ml", "119.90"),
    ("Tintas", "Tinta para Tecido", "Corfix", "37ml", "4.90"),
    ("Tintas", "Tinta PVA Fosca", "Daiara", "3.6L", "139.90"),
    ("Tintas", "Tinta Spray Metalico", "NOU", "400ml", "39.99"),
    ("Tintas", "Tinta Relevo 3D", "Acrilex", "35ml", "6.90"),
    ("Aviamentos", "Elastico Chato 20mm", "NYBC", "10 metros", "8.90"),
    ("Aviamentos", "Fita de Cetim", "NYBC", "10 metros", "6.50"),
    ("Aviamentos", "Botao de Poliester 15mm", "NYBC", "cartela 12un", "3.90"),
    ("Aviamentos", "Micanga de Vidro", "Circulo", "500un", "9.90"),
    ("Aviamentos", "Barbante Colorido", "Circulo", "200 metros", "11.90"),
    ("Aviamentos", "Linha de Croche", "Circulo", "150 metros", "7.90"),
    ("Aviamentos", "Velcro Adesivo", "NYBC", "1 metro", "9.90"),
    ("Utensilios e Ferramentas", "Pistola de Cola Quente", "TekBond", "1 unidade", "34.90"),
    ("Utensilios e Ferramentas", "Refil Cola Quente Fina", "TekBond", "pacote 10un", "9.90"),
    ("Utensilios e Ferramentas", "Pincel Chato n12", "Condor", "1 unidade", "7.90"),
    ("Utensilios e Ferramentas", "Estilete Grande", "Acrilex", "1 unidade", "8.90"),
    ("Utensilios e Ferramentas", "Regua 30cm", "Acrilex", "1 unidade", "4.90"),
    ("Utensilios e Ferramentas", "Tesoura de Picotar Zig-Zag", "Acrilex", "1 unidade", "29.90"),
    ("Utensilios e Ferramentas", "Furador de Papel", "Acrilex", "1 unidade", "14.90"),
    ("Materiais de Artesanato", "Folha de EVA Lisa", "Gliart", "40x60cm", "2.90"),
    ("Materiais de Artesanato", "Folha de EVA Glitter", "Gliart", "40x60cm", "4.90"),
    ("Materiais de Artesanato", "Massa de Biscuit", "Acrilex", "90g", "8.90"),
    ("Materiais de Artesanato", "Feltro Liso", "Santa Fe", "1 metro", "12.90"),
    ("Materiais de Artesanato", "Manta Acrilica", "Circulo", "1 metro", "15.90"),
]


def ean13_com_digito_verificador(doze_digitos: str) -> str:
    """Calcula o 13o digito (verificador) de um codigo EAN-13."""
    total = sum(
        int(d) * (3 if i % 2 == 1 else 1) for i, d in enumerate(doze_digitos)
    )
    digito = (10 - (total % 10)) % 10
    return f"{doze_digitos}{digito}"


def gerar_codigo_ean13(rng: random.Random, usados: set[str]) -> str:
    while True:
        miolo = "789" + "".join(str(rng.randint(0, 9)) for _ in range(9))
        codigo = ean13_com_digito_verificador(miolo)
        if codigo not in usados:
            usados.add(codigo)
            return codigo


def limpar_tabelas(session) -> None:
    """Apaga na ordem correta (respeitando FKs) para permitir rodar o seed
    mais de uma vez em desenvolvimento sem duplicar dados. Inclui os dados
    de carrinho/pedido (Fase 3) e de promocoes/historico de preco (Fase 4)
    gerados por quem estiver mexendo no app antes de rodar o seed de novo."""
    session.query(PedidoItem).delete()
    session.query(HistoricoPreco).delete()
    session.query(MovimentacaoEstoque).delete()
    session.query(CarrinhoItem).delete()
    session.query(Estoque).delete()
    session.query(ProdutoCodigo).delete()
    session.query(PromocaoSugestao).delete()
    session.query(Pedido).delete()
    session.query(Produto).delete()
    session.query(SessaoCarrinho).delete()
    session.query(Categoria).delete()
    session.query(Funcionario).delete()
    session.commit()


def escolher_perfil_giro(rng: random.Random) -> str:
    """25% rapido, 50% medio, 25% lento (parado) -- distribuicao usada
    tanto pro estoque atual quanto pro volume de vendas simuladas."""
    return rng.choices(
        ["rapido", "medio", "lento"], weights=[25, 50, 25], k=1
    )[0]


def gerar_movimentacoes(
    rng: random.Random, produto_id: int, perfil: str
) -> tuple[int, list[MovimentacaoEstoque]]:
    """Gera o historico de 90 dias de um produto e devolve
    (estoque_atual_resultante, lista_de_movimentacoes)."""

    if perfil == "lento":
        estoque_atual = rng.randint(0, 6)  # varios abaixo do limite baixo (5)
        total_vendido = rng.randint(0, 8)
        janela_min, janela_max = 35, JANELA_DIAS  # nada vendido recentemente
    elif perfil == "medio":
        estoque_atual = rng.randint(10, 40)
        total_vendido = rng.randint(20, 70)
        janela_min, janela_max = 0, JANELA_DIAS
    else:  # rapido
        estoque_atual = rng.randint(15, 60)
        total_vendido = rng.randint(120, 320)
        janela_min, janela_max = 0, JANELA_DIAS

    # ~15% dos produtos levam um ajuste manual (quebra/perda) no meio do periodo
    ajuste_qtd = -rng.randint(1, 3) if rng.random() < 0.15 else 0

    entrada_qtd = estoque_atual + total_vendido - ajuste_qtd

    movimentacoes: list[MovimentacaoEstoque] = []

    movimentacoes.append(
        MovimentacaoEstoque(
            produto_id=produto_id,
            tipo=TipoMovimentacao.ENTRADA,
            quantidade=entrada_qtd,
            criado_em=HOJE - timedelta(days=JANELA_DIAS, hours=rng.randint(0, 3)),
        )
    )

    if ajuste_qtd != 0:
        dia_ajuste = rng.randint(1, JANELA_DIAS - 1)
        movimentacoes.append(
            MovimentacaoEstoque(
                produto_id=produto_id,
                tipo=TipoMovimentacao.AJUSTE,
                quantidade=ajuste_qtd,
                criado_em=HOJE - timedelta(days=dia_ajuste, hours=rng.randint(8, 20)),
            )
        )

    for _ in range(total_vendido):
        dia_offset = rng.randint(janela_min, janela_max)
        hora = rng.randint(8, 21)  # horario comercial
        dia_base = HOJE - timedelta(days=dia_offset)
        criado_em = dia_base.replace(
            hour=hora, minute=rng.randint(0, 59), second=rng.randint(0, 59), microsecond=0
        )
        if criado_em > HOJE:  # nao deixa vender no "futuro"
            criado_em = HOJE - timedelta(minutes=rng.randint(1, 60))
        movimentacoes.append(
            MovimentacaoEstoque(
                produto_id=produto_id,
                tipo=TipoMovimentacao.SAIDA_VENDA,
                quantidade=1,
                criado_em=criado_em,
            )
        )

    return estoque_atual, movimentacoes


def rodar_seed() -> None:
    rng = random.Random(RNG_SEED)
    codigos_usados: set[str] = set()

    # Garante que as tabelas existem (uteis rodando contra o SQLite local
    # sem ter passado pelo alembic ainda). Contra o Neon, as migrations ja
    # devem ter sido aplicadas antes (alembic upgrade head).
    Base.metadata.create_all(bind=engine)

    session = SessionLocal()
    try:
        print("Limpando tabelas existentes...")
        limpar_tabelas(session)

        print(f"Inserindo funcionario admin padrao ({ADMIN_EMAIL})...")
        session.add(
            Funcionario(
                nome="Administrador",
                email=ADMIN_EMAIL,
                senha_hash=hash_senha(ADMIN_SENHA),
                papel=PapelFuncionario.ADMIN,
            )
        )

        print("Inserindo categorias...")
        categorias_por_nome = {}
        for nome in CATEGORIAS:
            categoria = Categoria(nome=nome)
            session.add(categoria)
            categorias_por_nome[nome] = categoria
        session.flush()  # garante os ids das categorias

        total_movimentacoes = 0
        produtos_criados = 0
        produtos_estoque_baixo = 0

        def criar_produto(
            categoria_nome: str,
            nome: str,
            marca: str,
            tamanho: str,
            codigo: str,
            preco_normal: str,
            preco_promocional: str | None,
        ) -> None:
            nonlocal total_movimentacoes, produtos_criados, produtos_estoque_baixo

            custo = (Decimal(preco_normal) * Decimal(str(rng.uniform(0.45, 0.62)))).quantize(Decimal("0.01"))

            produto = Produto(
                categoria_id=categorias_por_nome[categoria_nome].id,
                nome=nome,
                marca=marca,
                tamanho=tamanho,
                custo=custo,
                preco_normal=Decimal(preco_normal),
                preco_promocional=Decimal(preco_promocional) if preco_promocional else None,
                # Nunca nasce ativa: `preco_promocional` aqui e so o "Valor
                # c/ desconto" historico da planilha, mantido como
                # referencia. A promocao so passa a valer (preco_vigente
                # usa preco_promocional) quando um funcionario aprova pelo
                # fluxo de sugestoes (ver promotion_service.aprovar).
                promocao_ativa=False,
            )
            session.add(produto)
            session.flush()  # garante produto.id

            session.add(
                ProdutoCodigo(
                    produto_id=produto.id,
                    tipo=TipoCodigo.EAN13,
                    codigo=codigo,
                    principal=True,
                )
            )
            codigos_usados.add(codigo)

            # ~1 a cada 6 produtos ganha tambem um QR interno, pra demonstrar
            # que um produto pode ter mais de um codigo cadastrado.
            if produtos_criados % 6 == 0:
                qr = f"QR-{produto.id:05d}-{rng.randint(1000, 9999)}"
                session.add(
                    ProdutoCodigo(
                        produto_id=produto.id,
                        tipo=TipoCodigo.QR_INTERNO,
                        codigo=qr,
                        principal=False,
                    )
                )

            perfil = escolher_perfil_giro(rng)
            estoque_atual, movimentacoes = gerar_movimentacoes(rng, produto.id, perfil)

            session.add(
                Estoque(
                    produto_id=produto.id,
                    quantidade=estoque_atual,
                    quantidade_minima=None,  # usa o limite global (Fase 2)
                )
            )
            session.add_all(movimentacoes)

            total_movimentacoes += len(movimentacoes)
            produtos_criados += 1
            if estoque_atual <= LIMITE_ESTOQUE_BAIXO:
                produtos_estoque_baixo += 1

        print(f"Inserindo {len(PRODUTOS_ORIGINAIS)} produtos reais da planilha...")
        for categoria_nome, nome, marca, tamanho, codigo, preco_normal, preco_promocional in PRODUTOS_ORIGINAIS:
            codigos_usados.add(codigo)
            criar_produto(categoria_nome, nome, marca, tamanho, codigo, preco_normal, preco_promocional)

        print(f"Inserindo {len(PRODUTOS_NOVOS)} produtos adicionais (catalogo expandido)...")
        for categoria_nome, nome, marca, tamanho, preco_normal in PRODUTOS_NOVOS:
            codigo = gerar_codigo_ean13(rng, codigos_usados)
            criar_produto(categoria_nome, nome, marca, tamanho, codigo, preco_normal, None)

        session.commit()

        print("-" * 60)
        print(f"OK: {produtos_criados} produtos, {total_movimentacoes} movimentacoes de estoque")
        print(f"    {produtos_estoque_baixo} produtos com estoque <= {LIMITE_ESTOQUE_BAIXO} (pra testar alerta)")
        print(f"    janela de historico de vendas: ultimos {JANELA_DIAS} dias")
        print(f"    login admin: {ADMIN_EMAIL} / {ADMIN_SENHA} (so para dev/demo -- troque depois)")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    rodar_seed()
