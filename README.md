# Conciliação de geração solar - Caso Delfos

Projeto desenvolvido para comparar a geração de julho de 2026 entre o portal Heliora, tratado como fonte da verdade, e o banco SQLite `delfos.db`.

## Resultado principal

- SF-002, SF-003 e SF-004 coincidem diariamente entre portal e banco.
- SF-005 não possui o registro de 08/07/2026 no banco. A energia desse dia, 4.258,5 kWh, explica toda a diferença mensal.
- SF-001 foi armazenada sem o inversor `SF-001-INV-05`. A geração desse equipamento coincide com a diferença nos 31 dias e soma 55.702,3 kWh. Sua capacidade de 386,1 kWp também coincide com a diferença de capacidade cadastrada.

## Arquitetura

1. O script consulta os endpoints JSON usados pelo portal.
2. As respostas são filtradas para julho de 2026 e normalizadas por usina e data.
3. O SQLite é lido diretamente, sem migração para outro banco.
4. Portal e banco são comparados por total, cobertura de datas, capacidade e diferença diária.
5. Divergências são investigadas por inversor e validadas por testes automatizados.

Endpoints consultados:

```text
GET /api/solar_fields.json
GET /api/solar_fields/{solar_field_id}/energy_daily.json
GET /api/solar_fields/{solar_field_id}/devices.json
GET /api/devices/{device_id}/energy_daily.json
```

## Estrutura do projeto

```text
docs/       plano e documentação da análise
output/     relatório final em PDF
outputs/    arquivos CSV produzidos pela coleta
scripts/    coleta, comparação e geração do relatório
sql/        consultas solicitadas no teste
tests/      teste automatizado da conciliação
```

## Execução

Requer Python 3.10 ou superior. A coleta e os testes usam apenas a biblioteca padrão. A geração do PDF requer ReportLab.

```bash
python scripts/automacao_conciliacao.py --with-devices
python -m unittest discover -s tests -p "test_*.py" -v
python scripts/gerar_relatorio.py
```

## Validação manual do SQL

Abra `delfos.db` em uma ferramenta compatível com SQLite e execute `sql/consultas_entrega.sql`.

## Saídas

- `outputs/portal_energy_daily_julho.csv`: geração diária consolidada por usina.
- `outputs/portal_dispositivos.csv`: cadastro e capacidade dos inversores.
- `outputs/portal_inversores_daily_julho.csv`: geração diária por inversor.
- `outputs/comparacao_julho.csv`: resumo da conciliação por usina.
- `outputs/divergencias_diarias_julho.csv`: diferenças diárias investigadas.
- `output/pdf/relatorio_conciliacao_julho_2026.pdf`: relatório final.

## Uso de IA

IA foi utilizada para apoiar a interpretação do enunciado, estruturar a automação, organizar os testes e redigir o relatório. Os resultados foram conferidos com consultas no SQLite, totais da interface, soma dos inversores e testes automatizados.
