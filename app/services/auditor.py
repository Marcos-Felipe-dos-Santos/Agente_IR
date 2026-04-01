import logging
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.entities import Contribuinte, RendimentoTrabalho, DespesaMedica, ContaBancaria
from app.schemas.receita import ReceitaPrePreenchidaUpload
from app.schemas.auditoria import RelatorioAuditoria, DivergenciaDTO

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")


def _is_numeric(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False
        
        
def _str_to_dec(val: str) -> Decimal:
    """Converte valores tipo string BRL (ex 12000.50 ou 1.250,55) ou US para Decimal."""
    s = val.replace("R$", "").strip()
    if "," in s and "." in s:
        # Padrão Brasileiro 1.500,00 -> 1500.00
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        # Apenas virgula 1500,00 -> 1500.00
        s = s.replace(",", ".")
    return Decimal(s).quantize(TWO_PLACES)


def cruzar_malha_fina(contribuinte_id: int, payload: ReceitaPrePreenchidaUpload, db: Session) -> RelatorioAuditoria:
    """
    Motor principal de Inteligência Fiscal Contenciosa.
    Recebe o que a Receita *acha* e cruza com a Realidade do nosso Sistema.
    """
    divergencias = []
    risco_alto = False
    
    # 1. Auditar Rendimentos de Trabalho e Salários (RH vs Receita)
    empregos = db.scalars(select(RendimentoTrabalho).where(
        RendimentoTrabalho.contribuinte_id == contribuinte_id, 
        RendimentoTrabalho.ano_calendario == payload.ano_exercicio
    )).all()
    
    # Montar Hash table local pelo inicio do CNPJ
    map_empregos = { e.cnpj_fonte[:8]: e for e in empregos }
    
    for r_gov in payload.rendimentos_trabalho:
        cnpj_base = r_gov.cnpj_fonte[:8]
        if cnpj_base in map_empregos:
            sys_e = map_empregos[cnpj_base]
            
            # Checar tributável
            gov_rend = _str_to_dec(r_gov.rendimento_tributavel)
            sys_rend = sys_e.rendimento_tributavel
            diferenca = gov_rend - sys_rend
            
            if abs(diferenca) > 10.0:  # Margem de tolerância pequena
                status = "DIVERGENTE"
                risco_alto = True
                msg = f"A Receita está cobrando imposto sobre R$ {gov_rend:,.2f}, mas o Informe de RH só acusa R$ {sys_rend:,.2f}. Risco de Malha Fina e sonegação atribuída por erro da empresa."
                imp = f"+ R$ {diferenca:,.2f}"
            else:
                status = "OK"
                msg = f"Holerite de R$ {sys_rend:,.2f} validado rigorosamente na base do Governo."
                imp = "R$ 0,00"
                
            divergencias.append(DivergenciaDTO(
                categoria="Rendimentos",
                nome_item=r_gov.nome_fonte,
                valor_declarado_receita=str(gov_rend),
                valor_apurado_sistema=str(sys_rend),
                status=status,
                impacto_financeiro=imp,
                mensagem=msg
            ))
            
            # Checar IRRF
            gov_irrf = _str_to_dec(r_gov.irrf_retido)
            if abs(sys_e.irrf - gov_irrf) > 5.0:
                divergencias.append(DivergenciaDTO(
                    categoria="Rendimentos",
                    nome_item=f"{r_gov.nome_fonte} (IRRF)",
                    valor_declarado_receita=str(gov_irrf),
                    valor_apurado_sistema=str(sys_e.irrf),
                    status="DIVERGENTE",
                    impacto_financeiro=f"R$ {gov_irrf - sys_e.irrf:,.2f}",
                    mensagem=f"Receita alega IRRF de R$ {gov_irrf}, mas nosso motor leu R$ {sys_e.irrf}. Impacto direto na sua restituição!"
                ))
            
            del map_empregos[cnpj_base]
            
        else:
            # Receita acusa "Emprego Fantasma" não fornecido no nosso DB Local.
            gov_ren = _str_to_dec(r_gov.rendimento_tributavel)
            divergencias.append(DivergenciaDTO(
                categoria="Rendimentos Omitidos",
                nome_item=r_gov.nome_fonte,
                valor_declarado_receita=str(gov_ren),
                valor_apurado_sistema="0.00",
                status="ALERTA",
                impacto_financeiro=f"- R$ {gov_ren:,.2f}",
                mensagem="A Receita possui um Informe de Rendimento no e-CAC em seu nome que você não inseriu no Agent IR. Omissão causará Malha Fina."
            ))
            risco_alto = True
            
    # As fontes que nós importamos, mas a Receita não conhece
    for sys_omitido in map_empregos.values():
        divergencias.append(DivergenciaDTO(
            categoria="Rendimento RH não Consta",
            nome_item=sys_omitido.razao_social_fonte,
            valor_declarado_receita="0.00",
            valor_apurado_sistema=str(sys_omitido.rendimento_tributavel),
            status="ALERTA_CRITICO",
            impacto_financeiro=f"+ R$ {sys_omitido.rendimento_tributavel:,.2f}",
            mensagem="Você lançou um Holerite que não existe no e-CAC da Receita. A empresa pode não ter te reportado. Verifique a DIRF."
        ))
        risco_alto = True
        
            
    # 2. Auditar Despesas Médicas (Se a clínica não declarou D-Med)
    saudes = db.scalars(select(DespesaMedica).where(
        DespesaMedica.contribuinte_id == contribuinte_id,
        DespesaMedica.ano_calendario == payload.ano_exercicio
    )).all()
    
    map_saude = { s.cnpj_prestador[:8]: s for s in saudes }
    
    for s_gov in payload.despesas_medicas:
        cnpj_base = s_gov.cnpj_prestador[:8]
        gov_saude = _str_to_dec(s_gov.valor_pago)
        if cnpj_base in map_saude:
            sys_s = map_saude[cnpj_base]
            if abs(sys_s.valor_pago - gov_saude) > 5.0:
                divergencias.append(DivergenciaDTO(
                    categoria="Saúde",
                    nome_item=s_gov.razao_social,
                    valor_declarado_receita=str(gov_saude),
                    valor_apurado_sistema=str(sys_s.valor_pago),
                    status="DIVERGENTE",
                    impacto_financeiro=f"R$ {gov_saude - sys_s.valor_pago:,.2f}",
                    mensagem="Médico/clínica reportou um valor inferior/superior na D-Med deles. Caso você envie o modelo Completo com recibos diferentes, cairá na Malha."
                ))
            else:
                divergencias.append(DivergenciaDTO(
                    categoria="Saúde",
                    nome_item=s_gov.razao_social,
                    valor_declarado_receita=str(sys_s.valor_pago),
                    valor_apurado_sistema=str(sys_s.valor_pago),
                    status="OK",
                    impacto_financeiro="R$ 0,00",
                    mensagem="Despesa médica batida milimetricamente com a D-Med da Clínica. Dedução garantida."
                ))
            del map_saude[cnpj_base]
            
    # As saudes que sobraram na nossa lista local indicam Recibos que você tem mas O MEDICO SONEGOU na base do Governo
    for missing_saude in map_saude.values():
        divergencias.append(DivergenciaDTO(
            categoria="Medicina Sonegada / Omitida",
            nome_item=missing_saude.razao_social_prestador,
            valor_declarado_receita="0.00",
            valor_apurado_sistema=str(missing_saude.valor_pago),
            status="ALERTA_CRITICO",
            impacto_financeiro=f"+ R$ {missing_saude.valor_pago:,.2f}",
            mensagem="Você possui R$ " + str(missing_saude.valor_pago) + " em recibos dedutíveis da " + missing_saude.razao_social_prestador + " que NÃO CONSTA na Receita! Ou o médico sonegou (retifique-o) ou prepare os recibos físicos PDF pra defesa."
        ))
        risco_alto = True
        
    resumo = "Auditoria Completa. Total Sintonia com a Receita, liberação IMEDIATA para transmissão."
    if risco_alto:
        resumo = "Foram detectadas Fissuras Graves (Malha Fina). Proceda para o Conselheiro IA para avaliar o Contencioso."

    return RelatorioAuditoria(
        contribuinte_id=contribuinte_id,
        ano_exercicio=payload.ano_exercicio,
        divergencias=divergencias,
        risco_malha_fina_alto=risco_alto,
        resumo_analise=resumo
    )
