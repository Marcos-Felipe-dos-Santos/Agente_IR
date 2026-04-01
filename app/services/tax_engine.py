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

from app.models.entities import AtivoCripto, Contribuinte, OperacaoB3, RendimentoTrabalho, DespesaMedica, ContaBancaria, RendimentoInforme

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

def auditar_trabalho_saude(contribuinte_id: int, ano_base: int, db: Session) -> dict | None:
    """Busca folha salarial e despesas médicas para compor os rendimentos globais."""
    trabalhos = db.scalars(
        select(RendimentoTrabalho)
        .where(
            RendimentoTrabalho.contribuinte_id == contribuinte_id,
            RendimentoTrabalho.ano_calendario == ano_base
        )
    ).all()
    
    saudes = db.scalars(
        select(DespesaMedica)
        .where(
            DespesaMedica.contribuinte_id == contribuinte_id,
            DespesaMedica.ano_calendario == ano_base
        )
    ).all()
    
    if not trabalhos and not saudes:
        return None
        
    tot_trib = Decimal("0")
    tot_inss = Decimal("0")
    tot_irrf = Decimal("0")
    tot_saude = Decimal("0")
    
    for t in trabalhos:
        tot_trib += t.rendimento_tributavel
        tot_inss += t.contribuicao_previdenciaria
        tot_irrf += t.irrf
        
    for s in saudes:
        tot_saude += s.valor_pago
        
    return {
        "total_rendimento_tributavel": str(tot_trib.quantize(TWO_PLACES)),
        "total_inss_pago": str(tot_inss.quantize(TWO_PLACES)),
        "total_irrf_retido": str(tot_irrf.quantize(TWO_PLACES)),
        "total_despesas_medicas": str(tot_saude.quantize(TWO_PLACES))
    }

def avaliar_variacao_patrimonial(contribuinte_id: int, ano_base: int, db: Session) -> dict:
    # 1. BENS BANCÁRIOS E CORRETORAS
    contas = db.scalars(
        select(ContaBancaria)
        .where(ContaBancaria.contribuinte_id == contribuinte_id, ContaBancaria.ano_referencia == ano_base)
    ).all()
    
    bens_bancarios_anterior = sum((c.saldo_31_12_anterior for c in contas), Decimal("0"))
    bens_bancarios_atual = sum((c.saldo_31_12_atual for c in contas), Decimal("0"))

    # 2. B3 (Replay de Custo de Aquisição)
    ops_b3 = db.scalars(
        select(OperacaoB3)
        .where(OperacaoB3.contribuinte_id == contribuinte_id)
        .order_by(OperacaoB3.data_operacao.asc(), OperacaoB3.id.asc())
    ).all()

    b3_anterior = Decimal("0")
    b3_atual = Decimal("0")
    
    estado_b3_anterior = {}
    estado_b3_atual = {}
    
    for op in ops_b3:
        y = op.data_operacao.year
        t = op.ticker
        # Calculo State
        def update_state(state_dict):
            if t not in state_dict:
                state_dict[t] = PrecoMedioState(ticker=t)
            if op.tipo_operacao == "compra":
                state_dict[t].operacao_compra(op.quantidade, op.preco_unitario, op.custos_operacionais)
            elif op.tipo_operacao == "venda":
                state_dict[t].operacao_venda(op.quantidade, op.preco_unitario, op.custos_operacionais)
        
        if y < ano_base:
            update_state(estado_b3_anterior)
            
        if y <= ano_base:
            update_state(estado_b3_atual)
            
    # Patrimonio eh Qtd * PrecoMedio (Ou seja, Custo de Aquisição total em carteira)
    b3_anterior = sum((s.custo_acumulado for s in estado_b3_anterior.values()), Decimal("0"))
    b3_atual = sum((s.custo_acumulado for s in estado_b3_atual.values()), Decimal("0"))

    # 3. CRIPTOATIVOS (Custo de Aquisição)
    ops_cripto = db.scalars(
        select(AtivoCripto)
        .where(AtivoCripto.contribuinte_id == contribuinte_id)
        .order_by(AtivoCripto.data_operacao.asc(), AtivoCripto.id.asc())
    ).all()

    estado_cripto_anterior = {}
    estado_cripto_atual = {}
    
    for op in ops_cripto:
        y = op.data_operacao.year
        t = op.moeda
        def update_c(state_dict):
            if t not in state_dict:
                state_dict[t] = PrecoMedioState(ticker=t)
            if op.tipo_operacao == "compra":
                state_dict[t].operacao_compra(op.quantidade, op.preco_unitario_brl, Decimal("0"))
            elif op.tipo_operacao == "venda":
                state_dict[t].operacao_venda(op.quantidade, op.preco_unitario_brl, Decimal("0"))
                
        if y < ano_base:
             update_c(estado_cripto_anterior)
        if y <= ano_base:
             update_c(estado_cripto_atual)
             
    c_anterior = sum((s.custo_acumulado for s in estado_cripto_anterior.values()), Decimal("0"))
    c_atual = sum((s.custo_acumulado for s in estado_cripto_atual.values()), Decimal("0"))
    
    # MATEMATICA FINAL - Patrimonio e Variação
    total_anterior = bens_bancarios_anterior + b3_anterior + c_anterior
    total_atual = bens_bancarios_atual + b3_atual + c_atual
    variacao_nominal = total_atual - total_anterior
    perc = Decimal("0")
    if total_anterior > 0:
        perc = (variacao_nominal / total_anterior) * Decimal("100")
        
    e_pat = {
        "bens_bancarios_anterior": str(bens_bancarios_anterior.quantize(TWO_PLACES)),
        "bens_bancarios_atual": str(bens_bancarios_atual.quantize(TWO_PLACES)),
        "b3_anterior": str(b3_anterior.quantize(TWO_PLACES)),
        "b3_atual": str(b3_atual.quantize(TWO_PLACES)),
        "cripto_anterior": str(c_anterior.quantize(TWO_PLACES)),
        "cripto_atual": str(c_atual.quantize(TWO_PLACES)),
        "total_anterior": str(total_anterior.quantize(TWO_PLACES)),
        "total_atual": str(total_atual.quantize(TWO_PLACES)),
        "variacao_nominal": str(variacao_nominal.quantize(TWO_PLACES)),
        "variacao_percentual": str(perc.quantize(TWO_PLACES))
    }

    # MATEMATICA FLUXO DE CAIXA JUSTIFICADO
    rendimentos_informe = db.scalars(
        select(RendimentoInforme)
        .where(RendimentoInforme.contribuinte_id == contribuinte_id, RendimentoInforme.ano_calendario == ano_base)
    ).all()
    
    trabalhos = db.scalars(select(RendimentoTrabalho).where(RendimentoTrabalho.contribuinte_id == contribuinte_id, RendimentoTrabalho.ano_calendario == ano_base)).all()
    saudes = db.scalars(select(DespesaMedica).where(DespesaMedica.contribuinte_id == contribuinte_id, DespesaMedica.ano_calendario == ano_base)).all()
    
    rend_liquido = sum(((r.valor - r.irrf) for r in rendimentos_informe), Decimal("0"))
    rend_liquido += sum(((t.rendimento_tributavel - t.contribuicao_previdenciaria - t.irrf) for t in trabalhos), Decimal("0"))
    
    desp_saude = sum((s.valor_pago for s in saudes), Decimal("0"))
    
    caixa_disp = rend_liquido - desp_saude
    
    # A Variação não pode ser matematicamente maior que o caixa liquido. 
    # (Ou seja, ele não tem dinheiro no ano para justificar a compra desse patrimônio que ele disse ter no D-Bens)
    renda_descoberta = variacao_nominal > caixa_disp
    
    msg = "Variação Patrimonial matematicamente compatível com a renda adquirida no ano-base."
    if renda_descoberta:
        msg = f"AUMENTO PATRIMONIAL A DESCOBERTO! Patrimonio aumentou R$ {variacao_nominal:,.2f}, mas sobrou apenas R$ {caixa_disp:,.2f} no ano. Risco máximo de Malha Fina e Auto de Infração."
        
    f_caixa = {
        "rendimentos_totais_liquidos": str(rend_liquido.quantize(TWO_PLACES)),
        "aumento_patrimonial": str(variacao_nominal.quantize(TWO_PLACES)),
        "despesas_dedutiveis": str(desp_saude.quantize(TWO_PLACES)),
        "caixa_disponivel": str(caixa_disp.quantize(TWO_PLACES)),
        "renda_descoberta": bool(renda_descoberta),
        "mensagem_alerta": msg
    }

    return {"evolucao_patrimonial": e_pat, "fluxo_caixa": f_caixa}
