"""Gera o relatório técnico do caso a partir do SQLite e das evidências coletadas."""

import csv
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "relatorio_conciliacao_julho_2026.pdf"
LOGO = ROOT / "assets" / "delfos_logo.png"
REPOSITORY_URL = "https://github.com/BrunoBrasilino/Caso-pratico-Delfos/tree/main"
AUTHOR = "Bruno Brasilino"

ORANGE = colors.HexColor("#D55E23")
ORANGE_DARK = colors.HexColor("#A84317")
ORANGE_PALE = colors.HexColor("#FBEDE6")
GRAPHITE = colors.HexColor("#494C4B")
INK = colors.HexColor("#252B2A")
MUTED = colors.HexColor("#626867")
LIGHT = colors.HexColor("#F4F4F3")
MID = colors.HexColor("#D7D9D8")
WHITE = colors.white

# Totais conferidos visualmente no portal e usados como controle independente.
PORTAL_TOTALS = {
    "SF-001": 625613.9,
    "SF-002": 402938.1,
    "SF-003": 182733.0,
    "SF-004": 864240.6,
    "SF-005": 134726.0,
}


def br(value, decimals=1):
    return f"{value:,.{decimals}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def load_results():
    queries = (ROOT / "sql" / "consultas_entrega.sql").read_text(encoding="utf-8").split(";")
    with sqlite3.connect(ROOT / "delfos.db") as connection:
        results = [connection.execute(query).fetchall() for query in queries[:2]]
    return queries[:2], results


def read_output_csv(name):
    with (ROOT / "outputs" / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_collection():
    portal_rows = read_output_csv("portal_energy_daily_julho.csv")
    device_daily_rows = read_output_csv("portal_inversores_daily_julho.csv")
    devices = read_output_csv("portal_dispositivos.csv")
    diff_rows = read_output_csv("divergencias_diarias_julho.csv")
    comparison_rows = read_output_csv("comparacao_julho.csv")

    expected = {
        (field_id, (date(2026, 7, 1) + timedelta(days=offset)).isoformat())
        for field_id in PORTAL_TOTALS
        for offset in range(31)
    }
    portal_keys = [(row["solar_field_id"], row["date"]) for row in portal_rows]
    if len(portal_keys) != len(set(portal_keys)) or set(portal_keys) != expected:
        raise ValueError("A série diária do portal tem datas ausentes, extras ou duplicadas.")

    portal_totals = defaultdict(float)
    for row in portal_rows:
        portal_totals[row["solar_field_id"]] += float(row["energy_kwh"])
    if any(abs(portal_totals[key] - value) > 0.05 for key, value in PORTAL_TOTALS.items()):
        raise ValueError("Os totais coletados diferem dos valores conferidos na interface.")

    device_totals = defaultdict(float)
    device_ids = set()
    for row in device_daily_rows:
        device_totals[(row["solar_field_id"], row["date"])] += float(row["energy_kwh"])
        device_ids.add(row["device_id"])
    if any(
        abs(device_totals[(row["solar_field_id"], row["date"])] - float(row["energy_kwh"])) > 0.05
        for row in portal_rows
    ):
        raise ValueError("A soma dos inversores não coincide com a série diária das usinas.")

    sf001 = [row for row in diff_rows if row["solar_field_id"] == "SF-001"]
    sf005 = [row for row in diff_rows if row["solar_field_id"] == "SF-005"]
    if len(sf001) != 31 or len(sf005) != 1 or sf005[0]["date"] != "2026-07-08":
        raise ValueError("O perfil de divergências mudou; revisar o texto do relatório.")

    sf001_gap = {
        row["date"]: float(row["portal_kwh"]) - float(row["delfos_kwh"])
        for row in sf001
    }
    device_series = defaultdict(dict)
    for row in device_daily_rows:
        if row["solar_field_id"] == "SF-001":
            device_series[row["device_id"]][row["date"]] = float(row["energy_kwh"])
    matching_devices = [
        device_id
        for device_id, series in device_series.items()
        if set(series) == set(sf001_gap)
        and all(abs(series[day] - sf001_gap[day]) <= 0.05 for day in sf001_gap)
    ]
    if matching_devices != ["SF-001-INV-05"]:
        raise ValueError("A lacuna da SF-001 não corresponde unicamente ao inversor esperado.")

    omitted_device = next(row for row in devices if row["device_id"] == matching_devices[0])
    comparison = {row["solar_field_id"]: row for row in comparison_rows}
    capacity_gap = float(comparison["SF-001"]["portal_capacity_kwp"]) - float(
        comparison["SF-001"]["delfos_capacity_kwp"]
    )
    if abs(capacity_gap - float(omitted_device["capacity_kwp"])) > 0.01:
        raise ValueError("A diferença de capacidade não corresponde ao inversor omitido.")

    return {
        "portal_totals": dict(portal_totals),
        "portal_rows": portal_rows,
        "device_daily_rows": device_daily_rows,
        "devices": devices,
        "diff_rows": diff_rows,
        "comparison_rows": comparison_rows,
        "device_count": len(device_ids),
        "omitted_device": omitted_device,
        "omitted_energy": sum(sf001_gap.values()),
    }


def register_fonts():
    pdfmetrics.registerFont(TTFont("Century", r"C:\Windows\Fonts\GOTHIC.TTF"))
    pdfmetrics.registerFont(TTFont("Century-Bold", r"C:\Windows\Fonts\GOTHICB.TTF"))
    pdfmetrics.registerFont(TTFont("Century-Italic", r"C:\Windows\Fonts\GOTHICI.TTF"))
    pdfmetrics.registerFontFamily(
        "Century", normal="Century", bold="Century-Bold", italic="Century-Italic"
    )


def make_styles():
    base = getSampleStyleSheet()
    return {
        "cover_overline": ParagraphStyle(
            "cover_overline", parent=base["Normal"], fontName="Century-Bold",
            fontSize=10, leading=13, textColor=ORANGE, spaceAfter=11,
        ),
        "cover_title": ParagraphStyle(
            "cover_title", parent=base["Title"], fontName="Century-Bold",
            fontSize=30, leading=35, textColor=GRAPHITE, alignment=TA_LEFT,
            spaceAfter=11,
        ),
        "cover_subtitle": ParagraphStyle(
            "cover_subtitle", parent=base["Normal"], fontName="Century",
            fontSize=15, leading=20, textColor=GRAPHITE, spaceAfter=20,
        ),
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName="Century-Bold",
            fontSize=22, leading=27, textColor=GRAPHITE, alignment=TA_LEFT,
            spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"], fontName="Century",
            fontSize=9.2, leading=13.5, textColor=MUTED, alignment=TA_JUSTIFY,
            spaceAfter=11,
        ),
        "h1": ParagraphStyle(
            "h1", parent=base["Heading2"], fontName="Century-Bold",
            fontSize=12.2, leading=16, textColor=GRAPHITE, spaceBefore=11,
            spaceAfter=6,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading3"], fontName="Century-Bold",
            fontSize=9.7, leading=13, textColor=ORANGE_DARK, spaceBefore=7,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body", parent=base["BodyText"], fontName="Century",
            fontSize=8.8, leading=13.4, textColor=INK, alignment=TA_JUSTIFY,
            spaceAfter=7,
        ),
        "body_compact": ParagraphStyle(
            "body_compact", parent=base["BodyText"], fontName="Century",
            fontSize=8.2, leading=12.2, textColor=INK, alignment=TA_JUSTIFY,
            spaceAfter=5,
        ),
        "small": ParagraphStyle(
            "small", parent=base["BodyText"], fontName="Century",
            fontSize=7.4, leading=10.5, textColor=MUTED, alignment=TA_JUSTIFY,
            spaceAfter=5,
        ),
        "label": ParagraphStyle(
            "label", parent=base["Normal"], fontName="Century-Bold",
            fontSize=7.2, leading=9, textColor=ORANGE_DARK,
        ),
        "tablehead": ParagraphStyle(
            "tablehead", parent=base["Normal"], fontName="Century-Bold",
            fontSize=6.9, leading=8.7, textColor=WHITE,
        ),
        "cell": ParagraphStyle(
            "cell", parent=base["Normal"], fontName="Century",
            fontSize=7.1, leading=9.7, textColor=INK,
        ),
        "cell_bold": ParagraphStyle(
            "cell_bold", parent=base["Normal"], fontName="Century-Bold",
            fontSize=7.1, leading=9.7, textColor=INK,
        ),
        "code": ParagraphStyle(
            "code", parent=base["Code"], fontName="Courier",
            fontSize=6.5, leading=8.1, textColor=INK,
        ),
        "toc": ParagraphStyle(
            "toc", parent=base["Normal"], fontName="Century",
            fontSize=10, leading=14, textColor=INK,
        ),
        "toc_number": ParagraphStyle(
            "toc_number", parent=base["Normal"], fontName="Century-Bold",
            fontSize=10, leading=14, textColor=ORANGE,
        ),
        "kpi_value": ParagraphStyle(
            "kpi_value", parent=base["Normal"], fontName="Century-Bold",
            fontSize=16, leading=19, textColor=GRAPHITE, alignment=TA_CENTER,
        ),
        "kpi_label": ParagraphStyle(
            "kpi_label", parent=base["Normal"], fontName="Century",
            fontSize=6.8, leading=9, textColor=MUTED, alignment=TA_CENTER,
        ),
    }


def p(text, style):
    return Paragraph(text, style)


def section_header(number, title, subtitle, styles):
    prefix = f"{number}  " if number else ""
    return [
        p(f"{prefix}{title}", styles["title"]),
        HRFlowable(width="100%", thickness=1.2, color=ORANGE, spaceAfter=7),
        p(subtitle, styles["subtitle"]),
    ]


def data_table(headings, rows, widths, styles, highlight_rows=None, bold_first=False):
    highlight_rows = set(highlight_rows or [])
    cells = [[p(escape(str(value)), styles["tablehead"]) for value in headings]]
    for row in rows:
        rendered = []
        for index, value in enumerate(row):
            style = styles["cell_bold"] if bold_first and index == 0 else styles["cell"]
            rendered.append(p(escape(str(value)), style))
        cells.append(rendered)
    table = Table(cells, colWidths=widths, repeatRows=1, hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), ORANGE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, ORANGE_DARK),
        ("LINEBELOW", (0, -1), (-1, -1), 0.45, MID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for row_index in highlight_rows:
        commands.extend([
            ("BACKGROUND", (0, row_index + 1), (-1, row_index + 1), ORANGE_PALE),
            ("LINEBEFORE", (0, row_index + 1), (0, row_index + 1), 2.2, ORANGE),
        ])
    table.setStyle(TableStyle(commands))
    return table


def callout(title, body, styles, accent=ORANGE):
    content = [p(title, styles["h2"]), p(body, styles["body_compact"])]
    table = Table([[content]], colWidths=[505], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ORANGE_PALE),
        ("LINEBEFORE", (0, 0), (0, -1), 4, accent),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#EAC9B9")),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return KeepTogether(table)


def kpi_table(styles):
    values = [
        ("5", "usinas analisadas"),
        ("3", "sem divergência"),
        ("2", "com divergência"),
        ("59.960,8", "kWh não registrados"),
    ]
    cells = [[p(value, styles["kpi_value"]), p(label, styles["kpi_label"])] for value, label in values]
    table = Table([cells], colWidths=[126.25] * 4, rowHeights=[58], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, MID),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, MID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def architecture_diagram():
    drawing = Drawing(505, 160)

    def box(x, y, width, height, title, detail, primary=False):
        drawing.add(Rect(
            x, y, width, height,
            fillColor=ORANGE if primary else LIGHT,
            strokeColor=ORANGE if primary else MID,
            strokeWidth=0.9,
        ))
        text_color = WHITE if primary else GRAPHITE
        drawing.add(String(
            x + width / 2, y + height / 2 + 4, title,
            textAnchor="middle", fontName="Century-Bold", fontSize=8,
            fillColor=text_color,
        ))
        drawing.add(String(
            x + width / 2, y + height / 2 - 9, detail,
            textAnchor="middle", fontName="Century", fontSize=6.6,
            fillColor=text_color,
        ))

    def arrow(x1, y1, x2, y2):
        drawing.add(Line(x1, y1, x2 - 6, y2, strokeColor=ORANGE_DARK, strokeWidth=1.25))
        drawing.add(Polygon(
            [x2 - 6, y2 - 3.5, x2, y2, x2 - 6, y2 + 3.5],
            fillColor=ORANGE_DARK, strokeColor=ORANGE_DARK,
        ))

    box(0, 100, 95, 42, "Portal Heliora", "API JSON")
    box(0, 25, 95, 42, "Banco Delfos", "SQLite")
    box(137, 62, 118, 48, "Coleta e conciliação", "Python", primary=True)
    box(297, 62, 88, 48, "Evidências", "5 arquivos CSV")
    box(425, 101, 80, 40, "Validação", "4 testes")
    box(425, 24, 80, 40, "Comunicação", "relatório PDF")

    arrow(95, 121, 137, 94)
    arrow(95, 46, 137, 77)
    arrow(255, 86, 297, 86)
    arrow(385, 86, 425, 121)
    arrow(385, 86, 425, 44)
    return drawing


def cover_chrome(canvas, doc):
    canvas.saveState()
    width, height = A4
    canvas.setFillColor(ORANGE)
    canvas.rect(0, height - 13, width, 13, stroke=0, fill=1)
    canvas.setStrokeColor(ORANGE)
    canvas.setLineWidth(1)
    canvas.line(45, 38, width - 45, 38)
    canvas.setFont("Century", 7.2)
    canvas.setFillColor(MUTED)
    canvas.drawCentredString(width / 2, 24, "Caso prático Delfos | Relatório técnico")
    canvas.restoreState()


def page_chrome(canvas, doc):
    canvas.saveState()
    width, height = A4
    canvas.setFillColor(ORANGE)
    canvas.rect(0, height - 7, width, 7, stroke=0, fill=1)
    canvas.drawImage(str(LOGO), 45, height - 43, width=59, height=20, preserveAspectRatio=True, mask="auto")
    canvas.setFont("Century", 6.8)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(width - 45, height - 34, "Conciliação de geração solar | Julho de 2026")
    canvas.setStrokeColor(MID)
    canvas.setLineWidth(0.6)
    canvas.line(45, height - 49, width - 45, height - 49)
    canvas.line(45, 39, width - 45, 39)
    canvas.setFont("Century", 6.8)
    canvas.drawString(45, 25, f"{AUTHOR} | Processo seletivo Delfos")
    canvas.drawRightString(width - 45, 25, f"Página {doc.page}")
    canvas.restoreState()


def build():
    register_fonts()
    styles = make_styles()
    sql, (totals, days) = load_results()
    collected = load_collection()

    portal_totals = collected["portal_totals"]
    if set(portal_totals) != {row[0] for row in totals}:
        raise ValueError("As usinas do banco e da coleta não coincidem.")

    day_counts = {field_id: count for field_id, _, count in days}
    comparison_rows = collected["comparison_rows"]
    diff_rows = collected["diff_rows"]
    devices = collected["devices"]
    omitted_energy = collected["omitted_energy"]
    sf001_example = next(row for row in diff_rows if row["solar_field_id"] == "SF-001")
    sf005_example = next(row for row in diff_rows if row["solar_field_id"] == "SF-005")

    monthly_rows = []
    monthly_highlights = []
    for index, (field_id, name, capacity, db_total, yield_value) in enumerate(totals):
        portal_total = portal_totals[field_id]
        delta = db_total - portal_total
        if abs(delta) < 0.05:
            delta = 0.0
        if abs(delta) > 0.05:
            monthly_highlights.append(index)
        monthly_rows.append((
            field_id, name, br(portal_total), br(db_total), br(delta),
            f"{br(delta / portal_total * 100, 2)}%",
            "Conforme" if abs(delta) < 0.05 else "Diverge",
        ))

    story = []

    # 1. Capa
    logo = Image(str(LOGO), width=52 * mm, height=17.3 * mm)
    logo.hAlign = "LEFT"
    story += [
        Spacer(1, 34), logo, Spacer(1, 88),
        p("RELATÓRIO TÉCNICO", styles["cover_overline"]),
        p("Conciliação de geração solar", styles["cover_title"]),
        p("Portal Heliora x banco Delfos", styles["cover_subtitle"]),
        HRFlowable(width="100%", thickness=1.5, color=ORANGE, spaceAfter=18),
    ]
    cover_meta = Table([
        [p("AUTOR", styles["label"]), p(AUTHOR, styles["body_compact"])],
        [p("PROCESSO SELETIVO", styles["label"]), p("Estágio em Análise de Dados e Automação", styles["body_compact"])],
        [p("PERÍODO ANALISADO", styles["label"]), p("1 a 31 de julho de 2026", styles["body_compact"])],
        [p("DATA DE ENTREGA", styles["label"]), p("21 de setembro de 2026", styles["body_compact"])],
        [p("VERSÃO", styles["label"]), p("1.0 - entrega final", styles["body_compact"])],
    ], colWidths=[120, 385], hAlign="LEFT")
    cover_meta.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, MID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [cover_meta, PageBreak()]

    # 2. Sumário
    story += section_header("", "Sumário", "Estrutura do documento e localização dos principais resultados.", styles)
    toc_rows = [
        ("01", "Resumo executivo", "3"),
        ("02", "Escopo e metodologia", "4"),
        ("03", "Arquitetura e coleta automatizada", "5"),
        ("04", "Implementação da conciliação", "6"),
        ("05", "Geração do relatório e saídas", "7"),
        ("06", "Testes automatizados", "8"),
        ("07", "Consultas SQL e resultados", "9"),
        ("08", "Conciliação e evidências", "10"),
        ("09", "Decisões, limites e evolução", "11"),
        ("10", "Reprodutibilidade e anexos", "12"),
    ]
    toc = Table([
        [p(number, styles["toc_number"]), p(title, styles["toc"]), p(page, styles["toc_number"])]
        for number, title, page in toc_rows
    ], colWidths=[42, 415, 48], rowHeights=[31] * len(toc_rows), hAlign="LEFT")
    toc.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [WHITE, LIGHT]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.35, MID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [toc, Spacer(1, 16), callout(
        "Como ler este relatório",
        "A resposta ao caso aparece primeiro. Em seguida, o documento apresenta o caminho técnico que sustenta a conclusão: fontes, arquitetura, código, testes, SQL e evidências. As limitações são registradas separadamente para distinguir fatos comprovados de hipóteses operacionais.",
        styles,
    ), PageBreak()]

    # 3. Resumo executivo
    story += section_header(
        "01", "Resumo executivo",
        "Resultado da conciliação de julho de 2026, tratando o portal Heliora como fonte da verdade.",
        styles,
    )
    story += [callout(
        "Conclusão principal",
        "Três das cinco usinas estão integralmente conciliadas. As duas divergências somam <b>59.960,8 kWh</b> a menos no banco Delfos: <b>55.702,3 kWh</b> na SF-001 e <b>4.258,5 kWh</b> na SF-005.",
        styles,
    ), Spacer(1, 10), kpi_table(styles), p("Comparação mensal", styles["h1"])]
    story.append(data_table(
        ["ID", "Usina", "Portal kWh", "Delfos kWh", "Delta kWh", "Delta %", "Status"],
        monthly_rows, [48, 105, 75, 75, 75, 55, 72], styles,
        highlight_rows=monthly_highlights, bold_first=True,
    ))
    story += [
        p("Delta = Delfos - portal. As linhas em laranja exigem investigação; as demais fecham diariamente dentro da tolerância de 0,05 kWh.", styles["small"]),
        p("Diagnóstico das divergências", styles["h1"]),
        p("<b>SF-001 - Vale do Sol I.</b> O banco reproduz a série do portal sem o inversor SF-001-INV-05. A diferença ocorre em todos os 31 dias, soma exatamente a geração mensal do equipamento e também coincide com sua capacidade de 386,1 kWp.", styles["body"]),
        p("<b>SF-005 - Riacho Fundo.</b> O banco contém 30 dias. O registro de 08/07/2026 está ausente e o valor do portal nessa data, 4.258,5 kWh, é exatamente a diferença mensal.", styles["body"]),
        p("<b>SF-002, SF-003 e SF-004.</b> Totais, cobertura de datas e valores diários coincidem entre as duas fontes.", styles["body"]),
        PageBreak(),
    ]

    # 4. Escopo e metodologia
    story += section_header(
        "02", "Escopo e metodologia",
        "Definição do problema, fontes de dados, critérios de comparação e sequência de investigação.",
        styles,
    )
    story += [
        p("Objetivo", styles["h1"]),
        p("Identificar onde o banco <b>delfos.db</b> diverge do portal do cliente, quantificar o impacto em kWh e, quando sustentado pelos dados, explicar a causa da diferença. A análise cobre exclusivamente o intervalo de 01/07/2026 a 31/07/2026.", styles["body"]),
        p("Fontes e papéis", styles["h1"]),
    ]
    story.append(data_table(
        ["Fonte", "Conteúdo utilizado", "Papel na análise"],
        [
            ("Portal Heliora", "Usinas, geração diária, inversores, capacidade e status", "Fonte da verdade definida pelo enunciado"),
            ("delfos.db", "Cadastro de usinas e geração diária agregada", "Registro interno a ser conciliado"),
            ("CSVs gerados", "Recortes normalizados e resultados da comparação", "Trilha de evidência reproduzível"),
            ("Interface do portal", "Totais mensais exibidos ao usuário", "Controle independente da coleta via API"),
        ], [105, 210, 190], styles,
    ))
    story += [p("Etapas executadas", styles["h1"])]
    story.append(data_table(
        ["Etapa", "Operação", "Resultado esperado"],
        [
            ("1. Inspeção", "Leitura do enunciado, esquema SQLite e rotas usadas pelo portal", "Escopo e chaves de comparação"),
            ("2. Coleta", "Requisições HTTP GET aos JSONs de usinas e inversores", "Séries estruturadas do portal"),
            ("3. Normalização", "Filtro de datas e indexação por (usina, data)", "Fontes comparáveis"),
            ("4. Conciliação", "Somas, contagem de dias, deltas e datas ausentes", "Usinas conformes e divergentes"),
            ("5. Investigação", "Decomposição diária e por inversor", "Explicação das divergências"),
            ("6. Validação", "Testes automáticos e conferência com a interface", "Conclusões verificadas"),
        ], [70, 250, 185], styles,
    ))
    story += [
        p("Regras de cálculo", styles["h1"]),
        p("A diferença é calculada como <b>Delfos - portal</b>. O percentual usa o portal como denominador. Uma usina é marcada como conforme somente quando o valor absoluto da diferença é menor ou igual a 0,05 kWh e não existem datas ausentes em nenhuma fonte. O yield específico do banco é a geração mensal dividida pela capacidade cadastrada.", styles["body"]),
        PageBreak(),
    ]

    # 5. Arquitetura e coleta
    story += section_header(
        "03", "Arquitetura e coleta automatizada",
        "Fluxo de dados da origem até as evidências, com uso de endpoints JSON somente para leitura.",
        styles,
    )
    story += [architecture_diagram(), p("Endpoints consumidos", styles["h1"])]
    story.append(data_table(
        ["Requisição HTTP GET", "Retorno", "Uso"],
        [
            ("/api/solar_fields.json", "Lista de usinas", "Identificadores, nomes, localização e capacidade"),
            ("/api/solar_fields/{id}/energy_daily.json", "Série diária da usina", "Total mensal e comparação por data"),
            ("/api/solar_fields/{id}/devices.json", "Inversores da usina", "Cadastro, status e capacidade por equipamento"),
            ("/api/devices/{id}/energy_daily.json", "Série diária do inversor", "Fechamento da usina e investigação de causa"),
        ], [230, 105, 170], styles,
    ))
    story += [
        p("Funcionamento da coleta", styles["h1"]),
        p("O programa primeiro obtém as cinco usinas. Para cada usina, consulta a série diária consolidada e o cadastro de dispositivos. Quando a opção <b>--with-devices</b> é usada, percorre os 28 inversores e baixa a série diária de cada um. O período é filtrado no momento da leitura, antes de os registros serem gravados.", styles["body"]),
        callout(
            "39 requisições controladas",
            "A execução realiza 1 chamada para a lista de usinas, 5 para as séries das usinas, 5 para os cadastros de dispositivos e 28 para as séries dos inversores. Todas são operações GET, com timeout de 30 segundos e sem alteração no sistema de origem.",
            styles,
        ),
        p("Por que usar a API", styles["h1"]),
        p("Os endpoints retornam JSON estruturado, exatamente como a aplicação web consome os dados. Isso evita dependência de posição de botões, renderização da página ou leitura de HTML. Para este caso, é uma automação mais simples de repetir e auditar do que simular cliques ou baixar manualmente dezenas de arquivos.", styles["body"]),
        PageBreak(),
    ]

    # 6. Implementação da conciliação
    story += section_header(
        "04", "Implementação da conciliação",
        "Responsabilidades de cada parte de scripts/automacao_conciliacao.py e estruturas utilizadas no processamento.",
        styles,
    )
    story.append(data_table(
        ["Função", "Entrada", "Operação", "Saída"],
        [
            ("fetch_json", "Caminho da API", "Monta a URL, aplica timeout, decodifica UTF-8 e converte JSON", "Lista ou objeto Python"),
            ("load_db", "delfos.db", "Lê cadastro e geração diária com filtro de período", "Dicionários por usina e (usina, data)"),
            ("load_portal", "Endpoints e flag de dispositivos", "Percorre usinas, séries e inversores; normaliza números", "Cadastros e listas tabulares"),
            ("compare", "Estruturas do banco e portal", "Soma energia, conta datas, calcula deltas e classifica ocorrências", "Resumo mensal e diferenças diárias"),
            ("write_csv", "Cabeçalho e registros", "Grava UTF-8 com colunas estáveis", "Arquivo de evidência"),
            ("main", "Argumentos --db, --out e --with-devices", "Orquestra o processo e apresenta o resumo", "Execução completa"),
        ], [76, 95, 245, 89], styles,
    ))
    story += [
        p("Estruturas de comparação", styles["h1"]),
        p("A chave principal é a tupla <b>(solar_field_id, date)</b>. Essa escolha permite consultar diretamente o valor de uma usina em um dia, detectar ausência sem depender da ordem dos registros e somar o mês percorrendo um conjunto fixo de 31 datas. Energia e capacidade são convertidas para números antes dos cálculos.", styles["body"]),
        p("Como uma divergência é classificada", styles["h1"]),
        p("Para cada data, o script distingue três situações: <b>missing_in_delfos</b>, quando só o portal possui o registro; <b>missing_in_portal</b>, quando só o banco possui; e <b>value_mismatch</b>, quando ambos existem, mas a diferença supera 0,05 kWh. O resumo mensal também registra contagem de dias, capacidades e listas de datas ausentes.", styles["body"]),
        p("Investigação por inversor", styles["h1"]),
        p("A soma dos inversores é agrupada por usina e data. Na SF-001, a série <b>portal - Delfos</b> foi comparada com cada série individual. Somente o SF-001-INV-05 coincide em todas as 31 datas; a soma mensal e a capacidade do mesmo inversor também fecham com as duas lacunas observadas.", styles["body"]),
        p("Comportamento em caso de erro", styles["h1"]),
        p("Falhas de rede, JSON inválido ou SQLite indisponível interrompem a execução e impedem a geração silenciosa de evidências parciais. A versão atual ainda não implementa retentativas, logs estruturados ou retomada por lote; esses pontos estão registrados como evolução operacional.", styles["body"]),
        PageBreak(),
    ]

    # 7. Relatório e saídas
    story += section_header(
        "05", "Geração do relatório e saídas",
        "Como os resultados são persistidos, validados novamente e transformados neste documento.",
        styles,
    )
    output_rows = [
        ("portal_energy_daily_julho.csv", len(collected["portal_rows"]), "Usina, data, energia e irradiação", "Base diária do portal"),
        ("portal_dispositivos.csv", len(collected["devices"]), "Cadastro, modelo, módulos, capacidade e status", "Inventário dos inversores"),
        ("portal_inversores_daily_julho.csv", len(collected["device_daily_rows"]), "Usina, inversor, data e energia", "Decomposição da geração"),
        ("comparacao_julho.csv", len(comparison_rows), "Totais, deltas, dias, capacidades e status", "Resumo da conciliação"),
        ("divergencias_diarias_julho.csv", len(diff_rows), "Datas, valores, diferenças e tipo de ocorrência", "Fila de investigação"),
    ]
    story.append(data_table(
        ["Arquivo", "Linhas", "Conteúdo", "Finalidade"], output_rows,
        [175, 43, 190, 97], styles,
    ))
    story += [
        p("scripts/gerar_relatorio.py", styles["h1"]),
        p("O gerador lê as duas consultas SQL, executa-as diretamente no SQLite e carrega os cinco CSVs. Antes de montar as páginas, verifica cobertura completa do portal, ausência de duplicidades, fechamento entre inversores e usinas, perfil esperado das divergências e correspondência da capacidade do INV-05. Se uma premissa mudar, a geração é interrompida para evitar um relatório visualmente correto com narrativa desatualizada.", styles["body"]),
        p("sql/consultas_entrega.sql", styles["h1"]),
        p("O arquivo mantém as duas consultas solicitadas fora do código de apresentação. Elas podem ser executadas isoladamente em qualquer ferramenta compatível com SQLite. Essa separação facilita revisão técnica e evita que a lógica do banco fique escondida no gerador do PDF.", styles["body"]),
        p("Formato das evidências", styles["h1"]),
        p("CSV foi escolhido por ser simples, portátil e auditável. Ele não suporta cor, negrito ou realce persistente; por isso, as linhas críticas são reproduzidas com destaque visual na seção 08 deste relatório. As chaves exibidas permitem localizar exatamente os mesmos registros nos arquivos brutos.", styles["body"]),
        callout(
            "Papéis diferentes, mesma execução",
            "Os CSVs preservam a evidência detalhada; os testes verificam as regras; o PDF comunica uma execução fechada. Em uma evolução futura, um dashboard seria a interface de acompanhamento contínuo sem substituir esses três artefatos.",
            styles,
        ),
        PageBreak(),
    ]

    # 8. Testes
    story += section_header(
        "06", "Testes automatizados",
        "Verificações executadas sobre os CSVs e o SQLite para reduzir o risco de conclusões incorretas.",
        styles,
    )
    story += [
        p("Como a suíte funciona", styles["h1"]),
        p("Ao iniciar, <b>tests/test_conciliacao.py</b> carrega os cinco resultados relevantes e consulta novamente a tabela energy_daily do SQLite. Os registros são organizados em conjuntos e dicionários para que cada asserção compare chaves e valores, e não apenas totais já agregados. A suíte usa a biblioteca padrão unittest e pode ser executada sem serviços adicionais.", styles["body"]),
    ]
    story.append(data_table(
        ["Teste", "O que faz", "Garantia fornecida"],
        [
            ("Cobertura do portal", "Monta as 155 combinações esperadas de 5 usinas x 31 dias; rejeita duplicadas, ausentes ou extras", "A coleta diária está completa e sem dupla contagem"),
            ("Fechamento por inversor", "Soma os inversores por usina e data e compara com a série consolidada, tolerância 0,05 kWh", "A decomposição por equipamento reproduz a fonte"),
            ("Causa da SF-001", "Compara portal - banco com INV-05 em 31 dias, no mês e na capacidade, tolerância 0,01 kWp", "A lacuna corresponde exatamente ao equipamento identificado"),
            ("Causa da SF-005", "Compara os conjuntos de datas do portal e banco", "08/07 é a única data ausente e não há datas extras"),
        ], [105, 260, 140], styles,
    ))
    story += [
        p("Critérios de aprovação", styles["h1"]),
        p("Os quatro testes precisam terminar com status <b>OK</b>. Qualquer data inesperada, diferença acima da tolerância ou mudança na identidade do inversor faz a execução falhar e exibe a chave responsável. Isso transforma as principais conclusões do relatório em regras verificáveis.", styles["body"]),
        p("O que os testes não provam", styles["h1"]),
        p("A suíte confirma consistência entre os arquivos coletados, o SQLite entregue e as hipóteses do diagnóstico. Ela não valida a instrumentação física da usina, a cadeia interna de ingestão da Delfos nem a permanência futura do contrato da API. Esses riscos exigiriam telemetria bruta, logs e testes de integração em ambiente operacional.", styles["body"]),
        p("Resultado desta execução", styles["h1"]),
        callout(
            "4 de 4 testes aprovados - status OK",
            "Cobertura diária, fechamento por inversor, diagnóstico da SF-001 e data ausente da SF-005 foram confirmados na execução final.",
            styles,
        ),
        PageBreak(),
    ]

    # 9. SQL
    story += section_header(
        "07", "Consultas SQL e resultados",
        "Consultas executadas diretamente em delfos.db, com filtro inclusivo de 01 a 31/07/2026.",
        styles,
    )
    story += [p("1. Geração total e yield específico", styles["h1"]), Preformatted(sql[0].strip(), styles["code"]), Spacer(1, 5)]
    story.append(data_table(
        ["ID", "Usina", "Capacidade kWp", "Total kWh", "Yield kWh/kWp"],
        [(field_id, name, br(capacity, 2), br(total), br(yield_value, 2)) for field_id, name, capacity, total, yield_value in totals],
        [58, 165, 92, 92, 98], styles,
    ))
    story += [
        p("O yield usa a capacidade registrada no banco. Como a SF-001 também possui lacuna de capacidade, esse indicador deve ser interpretado junto da divergência cadastral.", styles["small"]),
        p("2. Quantidade de dias registrados", styles["h1"]),
        Preformatted(sql[1].strip(), styles["code"]), Spacer(1, 5),
    ]
    story.append(data_table(
        ["ID", "Usina", "Dias em julho"],
        [(field_id, name, day_counts[field_id]) for field_id, name, *_ in totals],
        [75, 315, 115], styles, highlight_rows=[4],
    ))
    story += [
        p("O resultado sinaliza imediatamente a SF-005 com 30 dias. A SQL identifica a ausência de cobertura; a comparação diária localiza a data e quantifica o impacto.", styles["small"]),
        PageBreak(),
    ]

    # 10. Evidências
    story += section_header(
        "08", "Conciliação e evidências",
        "Recortes dos arquivos gerados com destaque nas chaves que explicam as duas divergências.",
        styles,
    )
    comparison_examples = [row for row in comparison_rows if row["solar_field_id"] in {"SF-001", "SF-002", "SF-005"}]
    story += [p("Recorte de comparacao_julho.csv", styles["h1"])]
    story.append(data_table(
        ["ID", "Portal kWh", "Delfos kWh", "Delta kWh", "Dias DB/portal", "Cap. delta kWp", "Status"],
        [
            (
                row["solar_field_id"], br(float(row["portal_total_kwh"])),
                br(float(row["delfos_total_kwh"])),
                br(float(row["diff_kwh_delfos_minus_portal"])),
                f"{row['delfos_days']}/{row['portal_days']}",
                br(float(row["capacity_diff_kwp"]), 1), row["status"],
            )
            for row in comparison_examples
        ], [49, 76, 76, 76, 88, 82, 58], styles,
        highlight_rows=[0, 2], bold_first=True,
    ))
    story += [
        p("As linhas destacadas são as únicas que exigem investigação. SF-002 é mostrada como controle de uma usina conciliada.", styles["small"]),
        p("Evidência da SF-001", styles["h1"]),
    ]
    inv05 = next(row for row in devices if row["device_id"] == "SF-001-INV-05")
    story.append(data_table(
        ["Fonte", "Chave", "Valor observado", "Relação com o problema"],
        [
            ("divergencias_diarias_julho.csv", f"SF-001 | {sf001_example['date']}", f"Portal - Delfos = {br(abs(float(sf001_example['diff_kwh'])))} kWh", "Igual à geração do INV-05 no mesmo dia"),
            ("portal_inversores_daily_julho.csv", f"{inv05['device_id']} | {sf001_example['date']}", f"{br(abs(float(sf001_example['diff_kwh'])))} kWh", "Repete a lacuna diária"),
            ("portal_dispositivos.csv", inv05["device_id"], f"{br(float(inv05['capacity_kwp']), 1)} kWp", "Igual à lacuna de capacidade"),
            ("Soma mensal", "SF-001-INV-05", f"{br(omitted_energy)} kWh", "Igual à lacuna mensal"),
        ], [142, 105, 110, 148], styles, highlight_rows=[0, 1, 2, 3],
    ))
    story += [p("Evidência da SF-005", styles["h1"])]
    story.append(data_table(
        ["Arquivo", "Usina/data", "Delfos kWh", "Portal kWh", "Tipo"],
        [(
            "divergencias_diarias_julho.csv", f"SF-005 | {sf005_example['date']}",
            "vazio", br(float(sf005_example["portal_kwh"])), sf005_example["issue_type"],
        )], [172, 105, 76, 76, 76], styles, highlight_rows=[0],
    ))
    story += [
        p("O CSV bruto não armazena cores. O realce acima pertence ao relatório e serve para orientar a localização das mesmas chaves nos arquivos entregues.", styles["small"]),
        PageBreak(),
    ]

    # 11. Decisões e evolução
    story += section_header(
        "09", "Decisões, limites e evolução",
        "Justificativa das escolhas, autocrítica da implementação e caminho para uso recorrente.",
        styles,
    )
    story.append(data_table(
        ["Escolha", "Por que foi adequada", "Limite consciente"],
        [
            ("Python", "Integra HTTP, JSON, CSV, SQLite, testes e PDF com biblioteca padrão e código legível", "Não oferece interface operacional por si só"),
            ("API JSON", "Fonte estruturada, reproduzível e menos frágil que automação de cliques", "Depende do contrato dos endpoints"),
            ("SQLite", "É o formato entregue e permite análise local sem servidor", "Não atende histórico multiusuário em produção"),
            ("CSV", "Portátil, auditável e fácil de abrir em diferentes ferramentas", "Não preserva formatação nem experiência interativa"),
            ("unittest", "Transforma as principais conclusões em regras executáveis", "Cobre o caso e não toda a cadeia operacional"),
            ("ReportLab/PDF", "Produz documento estável, versionável e compartilhável", "Relatório é estático e sua narrativa ainda conhece o caso"),
        ], [84, 247, 174], styles,
    ))
    story += [
        p("Autocrítica", styles["h1"]),
        p("A solução privilegia clareza e reprodutibilidade no escopo do teste. O período, alguns controles e parte da narrativa estão ligados a julho de 2026. A coleta é síncrona e interrompe na primeira falha; não há retentativas, logs estruturados, autenticação ou histórico de execuções. Os CSVs são adequados como evidência, mas insuficientes como interface recorrente.", styles["body"]),
        p("Melhorias futuras", styles["h1"]),
        p("<b>1. Generalização.</b> Receber período, tolerâncias e fontes como parâmetros; separar regras genéricas da narrativa específica do caso.", styles["body_compact"]),
        p("<b>2. Operação confiável.</b> Incluir retentativas, logs, identificação de execução, tratamento de autenticação, armazenamento histórico e agendamento.", styles["body_compact"]),
        p("<b>3. Dashboard.</b> Criar uma interface em Streamlit ou tecnologia equivalente, com seleção de período, atualização, status por usina, gráfico Portal x Delfos, detalhe por inversor e exportação.", styles["body_compact"]),
        p("<b>4. Alertas e acompanhamento.</b> Executar a conciliação de forma recorrente e notificar somente novas divergências ou mudanças de causa.", styles["body_compact"]),
        callout(
            "Arquitetura futura sugerida",
            "O dashboard seria a interface para o usuário; um banco histórico sustentaria tendências e reprocessamentos; os CSVs permaneceriam como evidência de cada execução; os testes protegeriam as regras; e o PDF continuaria como registro formal para compartilhamento.",
            styles,
        ),
        PageBreak(),
    ]

    # 12. Reprodutibilidade e anexos
    story += section_header(
        "10", "Reprodutibilidade e anexos",
        "Comandos, validações independentes, uso de IA, dados adicionais necessários e acesso ao código-fonte.",
        styles,
    )
    story += [
        p("Como reproduzir", styles["h1"]),
        Preformatted(
            "python scripts/automacao_conciliacao.py --with-devices\n"
            "python -m unittest discover -s tests -p \"test_*.py\" -v\n"
            "python scripts/gerar_relatorio.py", styles["code"],
        ),
        p("Controles independentes", styles["h1"]),
        p("Os totais obtidos pela soma das séries JSON foram comparados com os valores exibidos na visão mensal do portal. As consultas SQL foram executadas diretamente no SQLite. A soma dos inversores reproduziu diariamente cada usina e os quatro testes automatizados passaram. Essas verificações usam caminhos diferentes para reduzir o risco de um único erro ser repetido em todo o relatório.", styles["body"]),
        p("Limite do diagnóstico da SF-001", styles["h1"]),
        p("Os dados provam que o INV-05 ficou fora do agregado do banco, mas não permitem localizar a etapa interna responsável. Para distinguir falha de cadastro, associação ou ingestão, seriam necessários o histórico de vínculo entre usina e inversor, a configuração do coletor, os identificadores de mapeamento, logs e arquivos brutos. Não há evidência de falha física: o portal mostra o equipamento online e gerando.", styles["body"]),
        p("Uso de inteligência artificial", styles["h1"]),
        p("IA foi utilizada para interpretar o enunciado, estruturar a investigação, apoiar o desenvolvimento dos scripts, organizar testes e redigir o relatório. Nenhuma conclusão foi aceita apenas por geração textual: SQL, totais da interface, séries diárias, soma dos inversores e testes automatizados foram usados como controles verificáveis.", styles["body"]),
        p("Anexo A - repositório", styles["h1"]),
        p(
            f'O código-fonte, as consultas, os testes, os CSVs e este relatório estão disponíveis em:<br/><link href="{REPOSITORY_URL}" color="#A84317"><u>{REPOSITORY_URL}</u></link>',
            styles["body_compact"],
        ),
        p("Conteúdo principal: scripts/automacao_conciliacao.py, scripts/gerar_relatorio.py, tests/test_conciliacao.py, sql/consultas_entrega.sql e outputs/.", styles["small"]),
        Spacer(1, 10),
        HRFlowable(width="100%", thickness=0.7, color=MID, spaceAfter=7),
        p("Fontes: enunciado 'Orientações Teste Tecnico - Estágio Analise de Dados e Automação.pdf'; banco local delfos.db; portal teste-pratico.performance.delfos.im; evidências da pasta outputs.", styles["small"]),
    ]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=A4,
        leftMargin=45, rightMargin=45, topMargin=62, bottomMargin=52,
        title="Relatório técnico - Conciliação de geração solar",
        author=AUTHOR,
        subject="Caso prático Delfos - Estágio em Análise de Dados e Automação",
    )
    doc.build(story, onFirstPage=cover_chrome, onLaterPages=page_chrome)
    print(OUTPUT)


if __name__ == "__main__":
    build()
