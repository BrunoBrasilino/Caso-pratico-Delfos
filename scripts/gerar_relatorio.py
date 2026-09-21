"""Gera o relatorio do caso a partir do SQLite e da coleta do portal."""

import csv
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
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

# Totais conferidos previamente na interface, usados como controle independente
# da coleta automatizada das series diarias.
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
    out = ROOT / "outputs"
    with (out / "portal_energy_daily_julho.csv").open(encoding="utf-8", newline="") as handle:
        portal_rows = list(csv.DictReader(handle))
    with (out / "portal_inversores_daily_julho.csv").open(encoding="utf-8", newline="") as handle:
        device_rows = list(csv.DictReader(handle))
    with (out / "portal_dispositivos.csv").open(encoding="utf-8", newline="") as handle:
        devices = list(csv.DictReader(handle))
    with (out / "divergencias_diarias_julho.csv").open(encoding="utf-8", newline="") as handle:
        diff_rows = list(csv.DictReader(handle))

    expected = {
        (field_id, (date(2026, 7, 1) + timedelta(days=offset)).isoformat())
        for field_id in PORTAL_TOTALS
        for offset in range(31)
    }
    portal_keys = [(row["solar_field_id"], row["date"]) for row in portal_rows]
    if len(portal_keys) != len(set(portal_keys)) or set(portal_keys) != expected:
        raise ValueError("A serie diaria do portal tem datas ausentes, extras ou duplicadas.")

    portal_totals = defaultdict(float)
    for row in portal_rows:
        portal_totals[row["solar_field_id"]] += float(row["energy_kwh"])
    if any(abs(portal_totals[key] - value) > 0.05 for key, value in PORTAL_TOTALS.items()):
        raise ValueError("Os totais coletados diferem dos valores conferidos na interface.")

    device_totals = defaultdict(float)
    device_ids = set()
    for row in device_rows:
        device_totals[(row["solar_field_id"], row["date"])] += float(row["energy_kwh"])
        device_ids.add(row["device_id"])
    if any(
        abs(device_totals[(row["solar_field_id"], row["date"])] - float(row["energy_kwh"])) > 0.05
        for row in portal_rows
    ):
        raise ValueError("A soma dos inversores nao coincide com a serie diaria das usinas.")

    sf001 = [row for row in diff_rows if row["solar_field_id"] == "SF-001"]
    sf005 = [row for row in diff_rows if row["solar_field_id"] == "SF-005"]
    if len(sf001) != 31 or len(sf005) != 1 or sf005[0]["date"] != "2026-07-08":
        raise ValueError("O perfil de divergencias diarias mudou; revisar o texto do relatorio.")
    sf001_gap = {
        row["date"]: float(row["portal_kwh"]) - float(row["delfos_kwh"])
        for row in sf001
    }
    device_series = defaultdict(dict)
    for row in device_rows:
        if row["solar_field_id"] == "SF-001":
            device_series[row["device_id"]][row["date"]] = float(row["energy_kwh"])
    matching_devices = [
        device_id
        for device_id, series in device_series.items()
        if set(series) == set(sf001_gap)
        and all(abs(series[day] - sf001_gap[day]) <= 0.05 for day in sf001_gap)
    ]
    if matching_devices != ["SF-001-INV-05"]:
        raise ValueError("A lacuna da SF-001 nao corresponde unicamente ao inversor esperado.")

    omitted_device = next(
        row for row in devices if row["device_id"] == matching_devices[0]
    )
    with (out / "comparacao_julho.csv").open(encoding="utf-8", newline="") as handle:
        comparison_rows = {
            row["solar_field_id"]: row for row in csv.DictReader(handle)
        }
    sf001_summary = comparison_rows["SF-001"]
    capacity_gap = float(sf001_summary["portal_capacity_kwp"]) - float(
        sf001_summary["delfos_capacity_kwp"]
    )
    if abs(capacity_gap - float(omitted_device["capacity_kwp"])) > 0.01:
        raise ValueError("A diferenca de capacidade nao corresponde ao inversor omitido.")

    return (
        dict(portal_totals),
        len(portal_rows),
        len(device_rows),
        len(device_ids),
        omitted_device,
        sum(sf001_gap.values()),
    )


def register_fonts():
    pdfmetrics.registerFont(TTFont("Arial", r"C:\Windows\Fonts\arial.ttf"))
    pdfmetrics.registerFont(TTFont("Arial-Bold", r"C:\Windows\Fonts\arialbd.ttf"))
    pdfmetrics.registerFontFamily("Arial", normal="Arial", bold="Arial-Bold")


def make_styles():
    base = getSampleStyleSheet()
    ink = colors.HexColor("#172329")
    muted = colors.HexColor("#52626A")
    green = colors.HexColor("#146B64")
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontName="Arial-Bold", fontSize=21, leading=25, textColor=ink, alignment=TA_LEFT, spaceAfter=7),
        "subtitle": ParagraphStyle("subtitle", parent=base["Normal"], fontName="Arial", fontSize=10, leading=14, textColor=muted, spaceAfter=14),
        "h1": ParagraphStyle("h1", parent=base["Heading2"], fontName="Arial-Bold", fontSize=12, leading=16, textColor=green, spaceBefore=14, spaceAfter=7),
        "h2": ParagraphStyle("h2", parent=base["Heading3"], fontName="Arial-Bold", fontSize=10, leading=13, textColor=ink, spaceBefore=9, spaceAfter=5),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName="Arial", fontSize=9.4, leading=14.2, textColor=ink, spaceAfter=8),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName="Arial", fontSize=8.2, leading=11.4, textColor=muted, spaceAfter=7),
        "tablehead": ParagraphStyle("tablehead", parent=base["Normal"], fontName="Arial-Bold", fontSize=7.5, leading=9.2, textColor=colors.white),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontName="Arial", fontSize=8, leading=10.7, textColor=ink),
        "code": ParagraphStyle("code", parent=base["Code"], fontName="Courier", fontSize=7.1, leading=8.4, textColor=ink),
    }


def p(text, style):
    return Paragraph(text, style)


def data_table(headings, rows, widths, styles):
    cells = [[p(escape(str(value)), styles["tablehead"]) for value in headings]]
    cells.extend([[p(escape(str(value)), styles["cell"]) for value in row] for row in rows])
    table = Table(cells, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#195D59")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F4")]),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.HexColor("#B7C9C6")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def architecture_table(styles):
    stages = [
        ("1. Descoberta", "Lista as usinas e lê capacidade, localização e identificador."),
        ("2. Coleta", "Faz requisições GET aos JSONs diários de usinas e inversores."),
        ("3. Normalização", "Filtra 01 a 31/07/2026 e usa (usina, data) como chave de comparação."),
        ("4. Conciliação", "Agrega energia, conta dias, calcula deltas e procura datas ou equipamentos ausentes."),
        ("5. Evidências", "Grava CSVs, executa testes automáticos e alimenta o relatório."),
    ]
    cells = []
    for index, (stage, description) in enumerate(stages):
        cells.append([
            p(stage, styles["tablehead"]),
            p(description, styles["cell"]),
        ])
    table = Table(cells, colWidths=[105, 400], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#195D59")),
        ("ROWBACKGROUNDS", (1, 0), (1, -1), [colors.white, colors.HexColor("#F1F5F4")]),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#B7C9C6")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D8E2E0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def page_chrome(canvas, doc):
    canvas.saveState()
    width, height = A4
    canvas.setStrokeColor(colors.HexColor("#B7C9C6"))
    canvas.line(45, height - 42, width - 45, height - 42)
    canvas.setFont("Arial", 8)
    canvas.setFillColor(colors.HexColor("#52626A"))
    canvas.drawString(45, 33, "Conciliação de geração | Julho de 2026")
    canvas.drawRightString(width - 45, 33, f"{doc.page}")
    canvas.restoreState()


def build():
    register_fonts()
    styles = make_styles()
    sql, (totals, days) = load_results()
    (
        portal_totals,
        portal_days,
        device_days,
        device_count,
        omitted_device,
        omitted_energy,
    ) = load_collection()
    if set(portal_totals) != {row[0] for row in totals}:
        raise ValueError("As usinas do banco e da conferencia no portal nao coincidem.")
    day_counts = {field_id: count for field_id, _, count in days}
    comparison_csv = read_output_csv("comparacao_julho.csv")
    diff_csv = read_output_csv("divergencias_diarias_julho.csv")
    devices_csv = read_output_csv("portal_dispositivos.csv")
    story = []

    story += [
        p("Conciliação de geração solar", styles["title"]),
        p("Caso prático Delfos | Julho de 2026 | Portal Heliora como referência", styles["subtitle"]),
        HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#195D59")),
        p("Síntese", styles["h1"]),
        p("Das cinco usinas analisadas, três têm valores diários idênticos nas duas fontes. Vale do Sol I e Riacho Fundo somam <b>59.960,8 kWh a menos</b> no banco Delfos em relação ao portal. Em Vale do Sol I, a diferença corresponde integralmente ao inversor 05. Em Riacho Fundo, falta o registro de 08/07.", styles["body"]),
        p("Comparação mensal", styles["h1"]),
    ]

    summary = []
    for field_id, name, capacity, db_total, yield_value in totals:
        portal_total = portal_totals[field_id]
        delta = db_total - portal_total
        if abs(delta) < 0.05:
            delta = 0.0
        summary.append((
            f"{field_id} - {name}", br(portal_total), br(db_total),
            br(delta), f"{br(delta / portal_total * 100, 2)}%",
            "Bate" if abs(delta) < 0.05 else "Diverge",
        ))
    story.append(data_table(
        ["Usina", "Portal kWh", "Delfos kWh", "Delta kWh", "Delta %", "Status"],
        summary, [143, 77, 77, 83, 57, 68], styles,
    ))
    story += [
        Spacer(1, 7),
        p("Delta = Delfos - portal; percentual calculado sobre o portal. Totais do portal obtidos pela coleta diária automatizada e conferidos na interface; totais Delfos calculados no SQLite.", styles["small"]),
        p("Divergências investigadas", styles["h1"]),
        p("<b>SF-005 - Riacho Fundo.</b> O banco registra 30 dias, sem 08/07/2026. O portal exibe 4.258,5 kWh nessa data, valor igual à diferença mensal. A ausência desse registro explica a diferença observada no total.", styles["body"]),
        p(f"<b>SF-001 - Vale do Sol I.</b> Em cada um dos 31 dias, portal menos Delfos é exatamente igual à geração do {omitted_device['device_name']} ({omitted_device['device_id']}). No mês, o inversor gerou {br(omitted_energy)} kWh, exatamente o déficit observado. Sua capacidade é {br(float(omitted_device['capacity_kwp']), 1)} kWp, também igual à diferença entre a capacidade do portal (4.254,8 kWp) e a do banco (3.868,7 kWp). Portanto, o agregado Delfos exclui integralmente esse inversor.", styles["body"]),
        p("<b>SF-002, SF-003 e SF-004.</b> As séries diárias coincidem na precisão de 0,1 kWh, assim como os totais mensais.", styles["body"]),
        PageBreak(),
        p("Consultas SQL e resultados", styles["title"]),
        p("Consultas executadas diretamente no arquivo delfos.db, com filtro inclusivo de 01 a 31/07/2026.", styles["subtitle"]),
        p("1. Geração total e yield específico", styles["h1"]),
        Preformatted(sql[0].strip(), styles["code"]),
        Spacer(1, 7),
    ]
    story.append(data_table(
        ["ID", "Usina", "Cap. kWp", "Total kWh", "Yield kWh/kWp"],
        [(field_id, name, br(capacity, 2), br(total), br(yield_value, 2)) for field_id, name, capacity, total, yield_value in totals],
        [62, 155, 88, 97, 103], styles,
    ))
    story += [
        Spacer(1, 8),
        p("Yield específico = geração mensal registrada no banco / capacidade cadastrada no banco. A capacidade divergente da SF-001 afeta também a leitura desse indicador.", styles["small"]),
        p("2. Dias registrados", styles["h1"]),
        Preformatted(sql[1].strip(), styles["code"]),
        Spacer(1, 7),
    ]
    story.append(data_table(
        ["ID", "Usina", "Dias em julho"],
        [(field_id, name, day_counts[field_id]) for field_id, name, *_ in totals],
        [80, 295, 130], styles,
    ))
    story += [
        PageBreak(),
        p("Arquitetura da automação", styles["title"]),
        p("A coleta consulta os mesmos arquivos JSON consumidos pela aplicação web. Não há automação de cliques nem leitura de HTML; são requisições HTTP GET somente para leitura.", styles["subtitle"]),
        p("Fluxo do processamento", styles["h1"]),
        architecture_table(styles),
        p("Endpoints utilizados", styles["h1"]),
    ]
    story.append(data_table(
        ["Requisição", "Finalidade"],
        [
            ("GET /api/solar_fields.json", "Usinas, capacidade e localização"),
            ("GET /api/solar_fields/{id}/energy_daily.json", "Geração diária consolidada da usina"),
            ("GET /api/solar_fields/{id}/devices.json", "Inversores e respectivas capacidades"),
            ("GET /api/devices/{id}/energy_daily.json", "Geração diária de cada inversor"),
        ],
        [250, 255],
        styles,
    ))
    story += [
        Spacer(1, 7),
        p(f"A execução realiza 39 requisições: uma para listar as usinas, cinco para as séries das usinas, cinco para os cadastros de dispositivos e 28 para as séries dos inversores. Cada resposta JSON é convertida em registros tabulares antes da comparação.", styles["small"]),
        p("Lógica de comparação", styles["h1"]),
        p("<b>1.</b> O banco SQLite e o portal são carregados em estruturas indexadas por usina e data. O intervalo é inclusivo entre 01/07 e 31/07/2026.", styles["body"]),
        p("<b>2.</b> Para cada usina, o programa soma a energia, conta datas, calcula Delfos menos portal, mede a diferença percentual e registra datas ausentes em cada fonte.", styles["body"]),
        p("<b>3.</b> Quando há divergência, a comparação desce para o nível diário. Na SF-001, a série portal menos Delfos foi comparada com cada inversor; apenas o INV-05 coincide nos 31 dias. Na SF-005, a diferença é um único registro ausente.", styles["body"]),
        p("<b>4.</b> O teste automático rejeita datas duplicadas ou faltantes no portal, confirma que a soma dos inversores fecha com cada usina e valida as causas identificadas.", styles["body"]),
        PageBreak(),
        p("Arquivos e evidências", styles["title"]),
        p("Os CSVs preservam a granularidade necessária para reproduzir o diagnóstico e podem ser abertos em Excel, Google Sheets, Python ou ferramentas de banco de dados.", styles["subtitle"]),
        p("Saídas geradas", styles["h1"]),
    ]
    story.append(data_table(
        ["Arquivo", "Linhas", "Conteúdo"],
        [
            ("portal_energy_daily_julho.csv", portal_days, "Usina, data, energia e irradiação"),
            ("portal_dispositivos.csv", device_count, "Cadastro, modelo, módulos e capacidade"),
            ("portal_inversores_daily_julho.csv", device_days, "Série diária por inversor"),
            ("comparacao_julho.csv", len(comparison_csv), "Resumo da conciliação por usina"),
            ("divergencias_diarias_julho.csv", len(diff_csv), "Diferenças diárias que exigem investigação"),
        ],
        [200, 55, 250],
        styles,
    ))
    story += [
        p("Recorte de comparacao_julho.csv", styles["h1"]),
    ]
    comparison_examples = [
        row for row in comparison_csv if row["solar_field_id"] in {"SF-001", "SF-002", "SF-005"}
    ]
    story.append(data_table(
        ["ID", "Portal kWh", "Delfos kWh", "Delta kWh", "Dias DB/portal", "Status"],
        [
            (
                row["solar_field_id"],
                br(float(row["portal_total_kwh"])),
                br(float(row["delfos_total_kwh"])),
                br(float(row["diff_kwh_delfos_minus_portal"])),
                f"{row['delfos_days']}/{row['portal_days']}",
                row["status"],
            )
            for row in comparison_examples
        ],
        [60, 87, 87, 87, 95, 89],
        styles,
    ))
    story += [
        p("Recortes que explicam as divergências", styles["h1"]),
    ]
    sf001_example = next(row for row in diff_csv if row["solar_field_id"] == "SF-001")
    sf005_example = next(row for row in diff_csv if row["solar_field_id"] == "SF-005")
    inv05 = next(row for row in devices_csv if row["device_id"] == "SF-001-INV-05")
    story.append(data_table(
        ["Evidência", "Data/equipamento", "Valor", "Interpretação"],
        [
            ("Diferença diária SF-001", sf001_example["date"], f"{br(abs(float(sf001_example['diff_kwh'])))} kWh", "Igual ao INV-05 no mesmo dia"),
            ("Cadastro INV-05", inv05["device_id"], f"{br(float(inv05['capacity_kwp']), 1)} kWp", "Igual à diferença de capacidade"),
            ("Registro ausente SF-005", sf005_example["date"], f"{br(abs(float(sf005_example['diff_kwh'])))} kWh", "Igual à diferença mensal"),
        ],
        [130, 115, 85, 175],
        styles,
    ))
    story += [
        Spacer(1, 8),
        p("Como reproduzir", styles["h1"]),
        Preformatted(
            "python scripts/automacao_conciliacao.py --with-devices\n"
            "python -m unittest discover -s tests -p \"test_*.py\" -v\n"
            "python scripts/gerar_relatorio.py",
            styles["code"],
        ),
        PageBreak(),
        p("Validação, limites e próximos passos", styles["title"]),
        p("Controles aplicados", styles["h1"]),
        p(f"A coleta produziu {portal_days} registros diários de usina e {device_days} registros de {device_count} inversores. Cada usina tem 31 datas no portal, sem duplicatas. A soma dos inversores coincide diariamente com cada usina, os totais reproduzem a interface e quatro testes automatizados passaram.", styles["body"]),
        p("Conclusão sobre a SF-001", styles["h1"]),
        p("A divergência não decorre de arredondamento nem de um fator genérico de escala. Os valores armazenados no banco equivalem à geração do portal sem o inversor SF-001-INV-05. O material fornecido não permite distinguir se a omissão ocorreu no cadastro, na associação do equipamento ou na etapa de ingestão; essa é a investigação operacional recomendada.", styles["body"]),
        p("Limites", styles["h1"]),
        p("O banco entregue possui apenas agregados diários por usina e não contém histórico de ingestão, logs ou medições por inversor. Por isso, a análise identifica com precisão o dado omitido, mas não a etapa interna que produziu a omissão. O portal foi tratado como fonte da verdade, conforme o enunciado.", styles["body"]),
        p("O que exigiria dados adicionais", styles["h1"]),
        p("Com os dados disponíveis, é possível concluir que o INV-05 foi excluído do agregado, mas não localizar a etapa interna que causou a exclusão. Para isso, seriam necessários o histórico de associação entre inversores e usinas, a configuração do coletor, os identificadores usados no mapeamento e os logs ou arquivos brutos da ingestão. Não há indício de necessidade de inspeção física: o portal mostra o inversor online e produzindo normalmente. Uma visita à usina só faria sentido se esses registros apontassem falha de medição ou comunicação no equipamento.", styles["body"]),
        p("Ação recomendada", styles["h1"]),
        p("Revisar o vínculo lógico do INV-05 com a SF-001 e o mapeamento usado pela ingestão; depois, reprocessar julho e executar novamente o teste de conciliação. O mesmo teste pode permanecer no fluxo recorrente para detectar futuras omissões.", styles["body"]),
        p("Uso de inteligência artificial", styles["h1"]),
        p("IA foi usada para interpretar o enunciado, estruturar as consultas, desenvolver a coleta e o teste automatizado e redigir este relatório. As consultas foram executadas contra o SQLite; a coleta foi validada pelos totais da interface e pela soma dos inversores; e a omissão do SF-001-INV-05 foi comprovada nos 31 dias e na capacidade cadastrada.", styles["body"]),
        Spacer(1, 8),
        HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#B7C9C6")),
        Spacer(1, 8),
        p("Fontes: enunciado 'Orientações Teste Tecnico - Estágio Analise de Dados e Automação.pdf'; banco local delfos.db; portal https://teste-pratico.performance.delfos.im; CSVs da coleta automatizada na pasta outputs.", styles["small"]),
    ]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(OUTPUT), pagesize=A4, leftMargin=45, rightMargin=45, topMargin=60, bottomMargin=54, title="Conciliação de geração - Julho de 2026", author="Análise do caso prático")
    doc.build(story, onFirstPage=page_chrome, onLaterPages=page_chrome)
    print(OUTPUT)


if __name__ == "__main__":
    build()
