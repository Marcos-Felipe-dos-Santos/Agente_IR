import io
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy.orm import Session
from sqlalchemy import select

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from app.models.entities import Contribuinte, OperacaoB3, RendimentoTrabalho, DespesaMedica
from app.services.tax_engine import auditar_trabalho_saude, avaliar_variacao_patrimonial

TETO_SIMPLIFICADO_2024 = Decimal("16754.34")
ALIQUOTA_SIMPLIFICADA = Decimal("0.20")
TWO_PLACES = Decimal("0.01")


def calcular_viabilidade_declaracao(contribuinte_id: int, ano_base: int, db: Session) -> dict:
    """Compara matematicamente Desconto Simplificado (Teto Receita) contra Desconto Completo."""
    dados = auditar_trabalho_saude(contribuinte_id, ano_base, db)
    if not dados:
        return {
            "recomendacao": "Indefinida",
            "motivo": "Sem dados suficientes de salário/saúde para cálculo comparativo.",
            "simplificado": "0.00",
            "completo": "0.00"
        }
        
    rendimento = Decimal(dados["total_rendimento_tributavel"])
    inss = Decimal(dados["total_inss_pago"])
    saude = Decimal(dados["total_despesas_medicas"])
    irrf = Decimal(dados["total_irrf_retido"])
    
    # 1. Modelo Simplificado (Rendimento * 20%, máximo de 16.754,34)
    abate_simples = rendimento * ALIQUOTA_SIMPLIFICADA
    if abate_simples > TETO_SIMPLIFICADO_2024:
        abate_simples = TETO_SIMPLIFICADO_2024
        
    # 2. Modelo Completo (INSS + Saúde sem limite)
    abate_completo = inss + saude
    
    # Decisão Matemática
    melhor_modelo = "Modelo Simplificado"
    motivo = f"A dedução padrão atingiu R$ {abate_simples:,.2f}, que é superior à soma das despesas comprovadas (R$ {abate_completo:,.2f})."
    
    if abate_completo > abate_simples:
        melhor_modelo = "Modelo Completo"
        motivo = f"A soma de Saúde + INSS (R$ {abate_completo:,.2f}) excedeu o Teto Legal Simplificado ou os 20% permitidos (R$ {abate_simples:,.2f})."
        
    return {
        "recomendacao": melhor_modelo,
        "motivo": motivo,
        "simplificado": str(abate_simples.quantize(TWO_PLACES)),
        "completo": str(abate_completo.quantize(TWO_PLACES)),
        "irrf_retido": str(irrf.quantize(TWO_PLACES))
    }


def gerar_dossie_pdf(contribuinte_id: int, ano: int, parecer_ia: str, db: Session) -> bytes:
    """Gera um Relatório PDF em Buffer isolado na RAM usando ReportLab."""
    buffer = io.BytesIO()
    
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4, 
        rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40
    )
    
    styles = getSampleStyleSheet()
    title_style = styles["Heading1"]
    title_style.alignment = 1 # Center
    
    subtitle_style = styles["Heading2"]
    subtitle_style.textColor = colors.HexColor("#2C3E50")
    
    normal_style = styles["Normal"]
    normal_style.fontSize = 10
    normal_style.leading = 14
    
    header_style = ParagraphStyle(
        name='AlertHeader',
        parent=normal_style,
        textColor=colors.HexColor("#D4AC0D"),
        fontWeight='bold',
        fontSize=12,
        spaceAfter=15
    )

    story = []
    
    # 1. Capa e Contribuinte
    contrib = db.get(Contribuinte, contribuinte_id)
    if not contrib:
        raise ValueError("Contribuinte não encontrado.")
    
    story.append(Paragraph(f"Dossiê Fiscal Executivo - IRPF {ano + 1}", title_style))
    story.append(Spacer(1, 20))
    story.append(Paragraph(f"<b>Contribuinte:</b> {contrib.nome_completo}", normal_style))
    story.append(Paragraph(f"<b>CPF:</b> {contrib.cpf}", normal_style))
    story.append(Paragraph(f"<b>Ano-Calendário Apurado:</b> {ano}", normal_style))
    story.append(Spacer(1, 30))
    
    # 2. Veredito Matemático (Calculadora)
    viabilidade = calcular_viabilidade_declaracao(contribuinte_id, ano, db)
    story.append(Paragraph("1. Veredito de Viabilidade (Simplificado vs Completo)", subtitle_style))
    story.append(Spacer(1, 10))
    
    data_viab = [
        ["Métrica", "Valor Legal (R$)"],
        ["Vantagem Simplificada (20% c/ Teto)", viabilidade["simplificado"]],
        ["Vantagem Completa (INSS + Saúde)", viabilidade["completo"]],
        ["Recomendação Final do Motor", viabilidade["recomendacao"]]
    ]
    t_viab = Table(data_viab, colWidths=[300, 150])
    t_viab.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#34495E")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor("#ECF0F1")),
        ('GRID', (0, 0), (-1, -1), 1, colors.white)
    ]))
    story.append(t_viab)
    story.append(Spacer(1, 15))
    story.append(Paragraph(f"<b>Justificativa:</b> {viabilidade['motivo']}", normal_style))
    story.append(Spacer(1, 30))
    
    # 3. Rendimentos Assalariados e Retidos na Fonte
    story.append(Paragraph("2. Resumo de Empregos e IR Retido na Fonte", subtitle_style))
    trabalhos = db.scalars(select(RendimentoTrabalho).where(RendimentoTrabalho.contribuinte_id == contribuinte_id, RendimentoTrabalho.ano_calendario == ano)).all()
    
    if trabalhos:
        data_trab = [["Empresa", "Salário Anual Tributável", "IRRF Já Retido", "INSS"]]
        for t in trabalhos:
            data_trab.append([
                Paragraph(t.razao_social_fonte, normal_style),
                f"R$ {t.rendimento_tributavel:,.2f}",
                f"R$ {t.irrf:,.2f}",
                f"R$ {t.contribuicao_previdenciaria:,.2f}"
            ])
            
        t_trab = Table(data_trab, colWidths=[200, 100, 100, 100])
        t_trab.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2980B9")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
        ]))
        story.append(Spacer(1, 10))
        story.append(t_trab)
    else:
        story.append(Paragraph("<i>Nenhum Holerite importado.</i>", normal_style))
        
    story.append(Spacer(1, 30))
    
    # 4. Despesas Médicas Extraídas
    story.append(Paragraph("3. Comprovantes de Saúde Extraídos", subtitle_style))
    saudes = db.scalars(select(DespesaMedica).where(DespesaMedica.contribuinte_id == contribuinte_id, DespesaMedica.ano_calendario == ano)).all()
    
    if saudes:
        data_saude = [["CNPJ da Clínica", "Valor Lançado"]]
        for s in saudes:
            data_saude.append([s.cnpj_prestador, f"R$ {s.valor_pago:,.2f}"])
            
        t_saud = Table(data_saude, colWidths=[250, 150])
        t_saud.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#27AE60")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0,0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
        ]))
        story.append(Spacer(1, 10))
        story.append(t_saud)
        story.append(Paragraph("Esses valores não sofrem limite de teto na dedução Completa.", normal_style))
    else:
        story.append(Paragraph("<i>Nenhuma Despesa Médica identificada.</i>", normal_style))
        
    story.append(Spacer(1, 40))

    # 4.5 Evolução Patrimonial e Renda a Descoberto
    story.append(Paragraph("4. Auditoria de Evolução Patrimonial (Renda Descoberta)", subtitle_style))
    story.append(Spacer(1, 10))
    
    variacao = avaliar_variacao_patrimonial(contribuinte_id, ano, db)
    ev = variacao.get("evolucao_patrimonial")
    fc = variacao.get("fluxo_caixa")
    
    if ev and fc:
        data_ev = [
            ["Inventário", f"31/12/{ano - 1}", f"31/12/{ano}"],
            ["Bens Bancários", f"R$ {ev['bens_bancarios_anterior']}", f"R$ {ev['bens_bancarios_atual']}"],
            ["B3 e Ações", f"R$ {ev['b3_anterior']}", f"R$ {ev['b3_atual']}"],
            ["Criptoativos", f"R$ {ev['cripto_anterior']}", f"R$ {ev['cripto_atual']}"],
            ["TOTAL ACUMULADO", f"R$ {ev['total_anterior']}", f"R$ {ev['total_atual']}"]
        ]
        t_ev = Table(data_ev, colWidths=[200, 100, 100])
        t_ev.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#8E44AD")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#D8BFD8")),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
        ]))
        story.append(t_ev)
        story.append(Spacer(1, 15))
        
        story.append(Paragraph(f"<b>Aumento de Patrimônio Declarado:</b> R$ {ev['variacao_nominal']} ({ev['variacao_percentual']}% de evolução)", normal_style))
        story.append(Paragraph(f"<b>Caixa Líquido Disponibilizado no Ano:</b> R$ {fc['caixa_disponivel']}", normal_style))
        story.append(Spacer(1, 10))
        
        cor_alerta = colors.HexColor("#27AE60") if not fc["renda_descoberta"] else colors.HexColor("#C0392B")
        style_alerta_malha = ParagraphStyle(
            name='AlertMalha', parent=normal_style, textColor=cor_alerta, fontWeight='bold'
        )
        story.append(Paragraph(f"VEREDITO: {fc['mensagem_alerta']}", style_alerta_malha))
        story.append(Spacer(1, 40))

    # 5. Parecer Conselheiro IA (Geral)
    story.append(Paragraph("5. Auditoria Cognitiva - Conselheiro IA Local", subtitle_style))
    story.append(Spacer(1, 15))
    
    # Tratamento simplório de Markdown para injetar os textos:
    clean_parecer = parecer_ia.replace("##", "").replace("*", "")
    lines = clean_parecer.split("\n")
    for line in lines:
        if line.strip():
            story.append(Paragraph(line, normal_style))
            story.append(Spacer(1, 6))

    doc.build(story)
    
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
