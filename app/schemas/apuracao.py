"""
Schemas de resposta para as apurações tributárias (O Cérebro).
"""

from __future__ import annotations

from typing import List
from pydantic import BaseModel, ConfigDict


class ResumoMesB3(BaseModel):
    """Resumo da apuração fiscal de um mês-calendário para Swing Trade."""
    mes: int
    ano: int
    total_vendas: str
    lucro_isento: str
    lucro_tributavel: str
    prejuizo_acumulado_utilizado: str
    prejuizo_mes_gerado: str
    prejuizo_a_compensar_seguinte: str
    imposto_devido: str


class AlertaCripto(BaseModel):
    """Alerta de teto de isenção ultrapassado em Criptoativos."""
    mes: int
    ano: int
    total_vendas: str
    limite_isencao: str
    mensagem: str


class RendimentoTrabalhoAgregado(BaseModel):
    """Agregação anual das informações de previdência, IRPF e Saúde."""
    total_rendimento_tributavel: str
    total_inss_pago: str
    total_irrf_retido: str
    total_despesas_medicas: str

class EvolucaoPatrimonial(BaseModel):
    bens_bancarios_anterior: str
    bens_bancarios_atual: str
    b3_anterior: str
    b3_atual: str
    cripto_anterior: str
    cripto_atual: str
    total_anterior: str
    total_atual: str
    variacao_nominal: str
    variacao_percentual: str

class FluxoCaixa(BaseModel):
    rendimentos_totais_liquidos: str
    aumento_patrimonial: str
    despesas_dedutiveis: str
    caixa_disponivel: str
    renda_descoberta: bool
    mensagem_alerta: str

class RelatorioAnualBase(BaseModel):
    """Agrega o ano inteiro e apura IR."""
    model_config = ConfigDict(strict=False)

    contribuinte_id: int
    ano_calendario: int
    meses: List[ResumoMesB3]
    total_lucro_isento_ano: str
    total_lucro_tributavel_ano: str
    total_imposto_devido_ano: str
    saldo_prejuizo_a_compensar_final_ano: str
    alertas_cripto: List[AlertaCripto]
    dados_trabalho_assalariado_e_saude: RendimentoTrabalhoAgregado | None = None
    evolucao_patrimonial: EvolucaoPatrimonial | None = None
    fluxo_caixa: FluxoCaixa | None = None
