# Plano de solucao - conciliacao de geracao Delfos

## Objetivo

Comparar a geracao de julho/2026 entre o portal Heliora, tratado como fonte da verdade, e o banco `delfos.db`, identificando quais usinas batem, quais divergem e o motivo provavel de cada divergencia.

## Entregaveis esperados

1. Duas consultas SQL executadas diretamente no `delfos.db`.
2. Resultado das consultas.
3. Relatorio em PDF ou HTML com metodologia, coleta, ferramentas, resultados, divergencias e uso de IA.
4. Evidencia reprodutivel da coleta do portal, preferencialmente automatizada.

## Andamento

- Concluido: duas queries e resultados conferidos no SQLite.
- Concluido: coleta diaria automatizada do portal, inclusive por inversor, com quatro CSVs em `outputs/`.
- Concluido: comparacao diaria e mensal; 31 divergencias de valor na SF-001 e um registro ausente na SF-005.
- Concluido: relatorio atualizado em `output/pdf/relatorio_conciliacao_julho_2026.pdf`.
- Concluido: identificacao do `SF-001-INV-05` como equipamento integralmente ausente do agregado Delfos da SF-001.
- Concluido: teste automatizado em `tests/test_conciliacao.py`, com quatro verificacoes de cobertura e conciliacao.
- Pendente: rastrear em ambiente operacional se a omissao ocorreu no cadastro, na associacao do inversor ou na ingestao.

## Estrategia

1. Ler o PDF e separar o que e requisito obrigatorio do que e ponto extra.
2. Inspecionar o SQLite: tabelas, chaves, campos e cobertura de datas.
3. Extrair dados do portal de forma automatica pelos endpoints usados pela propria aplicacao:
   - `/api/solar_fields.json`
   - `/api/solar_fields/{solar_field_id}/energy_daily.json`
   - `/api/solar_fields/{solar_field_id}/devices.json`
   - `/api/devices/{device_id}/energy_daily.json`, se for necessario explicar por inversor.
4. Filtrar tudo para `2026-07-01` a `2026-07-31`.
5. Agregar energia por usina nos dois lados.
6. Comparar:
   - total do portal
   - total da Delfos
   - diferenca em kWh
   - diferenca percentual
   - quantidade de dias em cada fonte
   - datas faltantes
   - diferenca de capacidade cadastrada
7. Investigar divergencias por dia e, se necessario, por inversor.

## Automacao criada

Script: `scripts/automacao_conciliacao.py`

Comando sugerido:

```bash
python scripts/automacao_conciliacao.py --with-devices
```

Saidas geradas:

```text
outputs/portal_energy_daily_julho.csv
outputs/comparacao_julho.csv
outputs/divergencias_diarias_julho.csv
outputs/portal_inversores_daily_julho.csv
outputs/portal_dispositivos.csv
```

## Consultas SQL

As queries estao em `sql/consultas_entrega.sql`.

Resultados obtidos no banco:

| Usina | Capacidade banco (kWp) | Total Delfos (kWh) | Yield especifico |
|---|---:|---:|---:|
| SF-001 - Vale do Sol I | 3868.70 | 569911.6 | 147.31 |
| SF-002 - Serra Azul | 2797.20 | 402938.1 | 144.05 |
| SF-003 - Alvorada Norte | 1502.28 | 182733.0 | 121.64 |
| SF-004 - Campo Verde II | 5923.71 | 864240.6 | 145.90 |
| SF-005 - Riacho Fundo | 949.39 | 130467.5 | 137.42 |

| Usina | Dias registrados no banco |
|---|---:|
| SF-001 - Vale do Sol I | 31 |
| SF-002 - Serra Azul | 31 |
| SF-003 - Alvorada Norte | 31 |
| SF-004 - Campo Verde II | 31 |
| SF-005 - Riacho Fundo | 30 |

## Comparacao com a coleta do portal

Validacao feita pela coleta diaria e conferida com a visao Monthly de julho/2026:

| Usina | Total portal (kWh) | Total Delfos (kWh) | Diferenca Delfos - portal (kWh) | Status |
|---|---:|---:|---:|---|
| SF-001 - Vale do Sol I | 625613.9 | 569911.6 | -55702.3 | Diverge |
| SF-002 - Serra Azul | 402938.1 | 402938.1 | 0.0 | Bate |
| SF-003 - Alvorada Norte | 182733.0 | 182733.0 | 0.0 | Bate |
| SF-004 - Campo Verde II | 864240.6 | 864240.6 | 0.0 | Bate |
| SF-005 - Riacho Fundo | 134726.0 | 130467.5 | -4258.5 | Diverge |

Hipoteses de causa:

- `SF-001`: portal menos Delfos coincide exatamente com a geracao do `SF-001-INV-05` em todos os 31 dias. O inversor gerou `55702.3 kWh` no mes, exatamente a diferenca mensal, e tem `386.1 kWp`, exatamente a diferenca de capacidade. O agregado Delfos exclui integralmente esse inversor.
- `SF-005`: o banco tem 30 dias; falta `2026-07-08`. No portal, esse dia aparece com `4258.5 kWh`, exatamente a diferenca observada.
- `SF-002`, `SF-003` e `SF-004`: valores diarios e totais batem na precisao de 0,1 kWh.

Conferencias da coleta: 155 registros diarios de usina, sem datas faltantes ou duplicadas no portal; 868 registros de 28 inversores. A soma dos inversores coincide com o valor diario de cada usina. O teste automatizado confirma a omissao integral do `SF-001-INV-05` e o unico dia ausente da SF-005.

Comando do teste:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

## Roteiro do relatorio

1. Contexto: chamado do cliente e escopo de julho/2026.
2. Fontes: portal Heliora como verdade e `delfos.db` como base Delfos.
3. Metodologia:
   - inspecao do SQLite;
   - coleta automatizada via endpoints do portal;
   - agregacao por usina e por dia;
   - comparacao por total, percentual e cobertura de datas;
   - investigacao de causa por capacidade/dia faltante.
4. SQL: incluir as duas queries e resultados.
5. Resultados:
   - tabela comparativa por usina;
   - status bate/diverge;
   - explicacao das divergencias.
6. Validacao:
   - conferir totais com a UI Monthly;
   - conferir quantidade de dias no banco;
   - conferir se a diferenca bate com o dia faltante ou fator de escala.
7. Uso de IA:
   - usada para leitura do enunciado, geracao de script e organizacao do relatorio;
   - resultados conferidos com SQL, UI do portal e comparacoes numericas.
