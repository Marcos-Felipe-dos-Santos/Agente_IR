"""
Motor de Apuração Tributária (O Cérebro).

Executa regras financeiras e matemáticas para apuração do IR anual.
Neste módulo operamos apenas leitura nos bancos de dados, montando
o balanço fiscal "on-the-fly" rodando replay das operações cronologicamente.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import AtivoCripto, Contribuinte, OperacaoB3

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")
EIGHT_PLACES = Decimal("0.00000001")
ALIQUOTA_SWING_TRADE = Decimal("0.15")  # 15% Swing Trade
LIMITE_ISENCAO_ACOES_MES = Decimal("20000.00")
LIMITE_ISENCAO_CRIPTO_MES = Decimal("35000.00")


# ── Estados Internos da Engine ──────────────────────────────────────
@dataclass
class PrecoMedioState:
    """Rastreia custo e quantidade na carteira de um Ticker em D+."""
    ticker: str
    quantidade: Decimal = Decimal("0")
    custo_acumulado: Decimal = Decimal("0")

    @property
    def preco_medio(self) -> Decimal:
        if self.quantidade <= 0:
            return Decimal("0")
        return (self.custo_acumulado / self.quantidade).quantize(
            EIGHT_PLACES, rounding=ROUND_HALF_UP
        )

    def operacao_compra(self, qtd: Decimal, preco_unitario: Decimal, custos: Decimal) -> None:
        """Adiciona qtd e valor em custódia."""
        valor_operacional = (qtd * preco_unitario) + custos
        self.quantidade += qtd
        self.custo_acumulado += valor_operacional

    def operacao_venda(self, qtd: Decimal, preco_venda: Decimal, custos_venda: Decimal) -> tuple[Decimal, Decimal, Decimal]:
        """
        Subtrai posição através do custo médio em carteira.
        Retorna: (lucro_liquido_da_op, custo_proporcional_operado, volume_de_venda).
        """
        pm_atual = self.preco_medio
        # Se vender a mais, assume as posições do mês mas com o PM restante até 0.
        # Caso clássico para day-trade ou notas ausentes historicamente.
        # Aqui, mantemos strict. Venda a descoberto (short) é zerada ou limit.
        qtd_efetiva = min(qtd, self.quantidade) if self.quantidade > 0 else qtd
        
        # Ousto proporcional é a custo "comprado" sendo abatida da reserva
        custo_proporcional = (qtd_efetiva * pm_atual).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        valor_bruto_venda = (qtd * preco_venda)

        # Lucro = Venda_liquida - Custo de Aquisição
        # Venda Liquida = Venda_bruta - custos_venda
        venda_liquida = valor_bruto_venda - custos_venda
        lucro_liquido = (venda_liquida - custo_proporcional).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

        self.quantidade = max(Decimal("0"), self.quantidade - qtd_efetiva)
        self.custo_acumulado = max(Decimal("0"), self.custo_acumulado - custo_proporcional)

        return lucro_liquido, custo_proporcional, valor_bruto_venda


@dataclass
class RelatorioMesState:
    """Mantém a matemática do mês."""
    mes: int
    ano: int
    total_vendas_b3: Decimal = Decimal("0")
    lucro_mes: Decimal = Decimal("0")       # Pode ser lucro (>) ou prejuízo (<) acumulado pelas vendas
    prejuizo_mes_gerado: Decimal = Decimal("0")
    
    # Resolvidos ao fim
    lucro_isento: Decimal = Decimal("0")
    lucro_tributavel: Decimal = Decimal("0")
    prejuizo_utilizado: Decimal = Decimal("0")
    prejuizo_transferido: Decimal = Decimal("0")
    imposto_devido: Decimal = Decimal("0")


# ── Lógica Core: Calcular Mensal B3 (On-the-fly) ────────────────────
def apurar_meses_b3(contribuinte_id: int, ano_base: int, db: Session) -> tuple[list[dict], Decimal]:
    """
    Busca todas as operações desde *a primeira*, para remontar a carteira até
    o fim de `ano_base`. Consolida apenas os meses de `ano_base` como output.

    Retorna:
    - Lista de json-ready schemas para os meses processados em `ano_base`.
    - Saldo de prejuízo final (rolado para ano_base + 1).
    """

    # Buscar todas as operações = O(N).
    ops = db.scalars(
        select(OperacaoB3)
        .where(
            OperacaoB3.contribuinte_id == contribuinte_id,
        )
        .order_by(OperacaoB3.data_operacao.asc(), OperacaoB3.id.asc())
    ).all()

    # Preço Médio Global no Tempo
    carteira_global: dict[str, PrecoMedioState] = {}
    
    # Apuração agrupamentos
    # Chave: "YYYY-MM"
    apura_meses_storage: dict[str, RelatorioMesState] = {}

    for op in ops:
        ano_op = op.data_operacao.year
        mes_op = op.data_operacao.month

        # Só importam as operações passadas ou do próprio ano para o saldo da carteira.
        if ano_op > ano_base:
            continue

        chave_mes = f"{ano_op:04d}-{mes_op:02d}"
        if chave_mes not in apura_meses_storage:
            apura_meses_storage[chave_mes] = RelatorioMesState(mes=mes_op, ano=ano_op)
        
        estado_mes = apura_meses_storage[chave_mes]
        
        # State de Ativo
        ticker = op.ticker
        if ticker not in carteira_global:
            carteira_global[ticker] = PrecoMedioState(ticker=ticker)
        
        state_ticker = carteira_global[ticker]

        if op.tipo_operacao == "compra":
            state_ticker.operacao_compra(op.quantidade, op.preco_unitario, op.custos_operacionais)
        elif op.tipo_operacao == "venda":
            lucro_liquido, custo_prop, vol_venda = state_ticker.operacao_venda(
                op.quantidade, op.preco_unitario, op.custos_operacionais
            )

            # Atingimos limite no Swing Trade => Somatório bruto das vendas do mês.
            estado_mes.total_vendas_b3 += vol_venda

            # Saldo global do mês
            estado_mes.lucro_mes += lucro_liquido

    # ────────────────────────────────────────────────────────
    # Fechamento Contábil de todos os meses, propagando prejuízo.
    # ────────────────────────────────────────────────────────

    # Ordenar meses para replay retroativo
    meses_ordenados = sorted(apura_meses_storage.keys())

    prejuizo_acumulado_global = Decimal("0")

    result_dicts_ano_base = []

    for chave in meses_ordenados:
        estado = apura_meses_storage[chave]
        
        lucro_bruto_atual = estado.lucro_mes
        isento = estado.total_vendas_b3 <= LIMITE_ISENCAO_ACOES_MES

        if lucro_bruto_atual < 0:
            # Geramos prejuízo
            estado.prejuizo_mes_gerado = abs(lucro_bruto_atual)
            prejuizo_acumulado_global += estado.prejuizo_mes_gerado

        elif lucro_bruto_atual > 0:
            if isento:
                # O limite só importa para lucros. Se o lucro é isento (< 20k de VD),
                # esse lucro PULA o abatimento. Abatimento de DARF só pode em Lucro Tributável.
                estado.lucro_isento = lucro_bruto_atual
            else:
                # Lucro tributável
                if prejuizo_acumulado_global > 0:
                    offset = min(lucro_bruto_atual, prejuizo_acumulado_global)
                    lucro_bruto_atual -= offset
                    prejuizo_acumulado_global -= offset
                    estado.prejuizo_utilizado = offset
                
                estado.lucro_tributavel = lucro_bruto_atual
                
                # IRRF, 15% Swing trade. Note que DARF de daytrade é 20%. 
                if estado.lucro_tributavel > 0:
                    estado.imposto_devido = (estado.lucro_tributavel * ALIQUOTA_SWING_TRADE).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

        estado.prejuizo_transferido = prejuizo_acumulado_global

        if estado.ano == ano_base:
            result_dicts_ano_base.append({
                "mes": estado.mes,
                "ano": estado.ano,
                "total_vendas": str(estado.total_vendas_b3.quantize(TWO_PLACES)),
                "lucro_isento": str(estado.lucro_isento.quantize(TWO_PLACES)),
                "lucro_tributavel": str(estado.lucro_tributavel.quantize(TWO_PLACES)),
                "prejuizo_acumulado_utilizado": str(estado.prejuizo_utilizado.quantize(TWO_PLACES)),
                "prejuizo_mes_gerado": str(estado.prejuizo_mes_gerado.quantize(TWO_PLACES)),
                "prejuizo_a_compensar_seguinte": str(estado.prejuizo_transferido.quantize(TWO_PLACES)),
                "imposto_devido": str(estado.imposto_devido.quantize(TWO_PLACES)),
            })

    return result_dicts_ano_base, prejuizo_acumulado_global


def auditar_cripto_vendas(contribuinte_id: int, ano_base: int, db: Session) -> list[dict]:
    """
    Agrupa vendas de Criptomoedas do usuário. Caso em algum mês 
    a soma das vendas > R$ 35.000, levanta um alerta fiscal para o json-relatório.
    """
    vendas = db.scalars(
        select(AtivoCripto)
        .where(
            AtivoCripto.contribuinte_id == contribuinte_id,
            AtivoCripto.tipo_operacao == "venda"
        )
    ).all()

    alertas = []

    # Map: YYYY -> MM -> Vendas
    acumulado_mes = defaultdict(lambda: defaultdict(Decimal))

    for op in vendas:
        ano = op.data_operacao.year
        mes = op.data_operacao.month
        acumulado_mes[ano][mes] += op.valor_total_brl

    # Auditar limites no ano_base apenas.
    # Mas como Cripto requer GCAP se der lucro a cada venda mensal > 35k,
    # vamos mostrar os alertas para o ano analisado.
    if ano_base in acumulado_mes:
        meses_ano = acumulado_mes[ano_base]
        for mes, soma_vendas in sorted(meses_ano.items()):
            if soma_vendas > LIMITE_ISENCAO_CRIPTO_MES:
                alertas.append({
                    "ano": ano_base,
                    "mes": mes,
                    "total_vendas": str(soma_vendas.quantize(TWO_PLACES)),
                    "limite_isencao": str(LIMITE_ISENCAO_CRIPTO_MES),
                    "mensagem": f"Atenção: Vendas de criptomoedas em {mes:02d}/{ano_base} superaram o limite de "
                                f"isenção de R$ 35.000,00 (Total = R$ {soma_vendas:,.2f}). "
                                f"Lucros obtidos devem ser tributados no GCAP do mês correspondente."
                })

    return alertas
