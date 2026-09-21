import argparse
import csv
import json
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from urllib.request import urlopen


BASE_URL = "https://teste-pratico.performance.delfos.im"
START_DATE = "2026-07-01"
END_DATE = "2026-07-31"


def fetch_json(path):
    url = f"{BASE_URL}{path}"
    with urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def july_dates():
    current = date.fromisoformat(START_DATE)
    end = date.fromisoformat(END_DATE)
    while current <= end:
        yield current.isoformat()
        current += timedelta(days=1)


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_db(db_path):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    fields = {
        row["solar_field_id"]: dict(row)
        for row in con.execute(
            "select solar_field_id, name, city, state, capacity_kwp from solar_field"
        )
    }

    daily = {}
    for row in con.execute(
        """
        select solar_field_id, date, energy_kwh
        from energy_daily
        where date between ? and ?
        """,
        (START_DATE, END_DATE),
    ):
        daily[(row["solar_field_id"], row["date"])] = float(row["energy_kwh"])

    con.close()
    return fields, daily


def load_portal(include_devices=False):
    fields = fetch_json("/api/solar_fields.json")
    portal_fields = {row["id"]: row for row in fields}
    portal_daily = {}
    portal_daily_rows = []
    device_rows = []
    device_daily_rows = []

    for field in fields:
        field_id = field["id"]
        for row in fetch_json(f"/api/solar_fields/{field_id}/energy_daily.json"):
            if START_DATE <= row["date"] <= END_DATE:
                energy = float(row["energy_kwh"])
                portal_daily[(field_id, row["date"])] = energy
                portal_daily_rows.append(
                    {
                        "solar_field_id": field_id,
                        "date": row["date"],
                        "energy_kwh": energy,
                        "irradiation_kwh_m2": row.get("irradiation_kwh_m2", ""),
                    }
                )

        if include_devices:
            devices = fetch_json(f"/api/solar_fields/{field_id}/devices.json")
            for device in devices:
                device_rows.append(
                    {
                        "solar_field_id": field_id,
                        "device_id": device["id"],
                        "device_name": device["name"],
                        "model": device.get("model", ""),
                        "modules": device.get("modules", ""),
                        "capacity_kwp": device.get("capacity_kwp", ""),
                        "status": device.get("status", ""),
                    }
                )
                for row in fetch_json(f"/api/devices/{device['id']}/energy_daily.json"):
                    if START_DATE <= row["date"] <= END_DATE:
                        device_daily_rows.append(
                            {
                                "solar_field_id": field_id,
                                "device_id": device["id"],
                                "device_name": device["name"],
                                "date": row["date"],
                                "energy_kwh": float(row["energy_kwh"]),
                            }
                        )

    return portal_fields, portal_daily, portal_daily_rows, device_rows, device_daily_rows


def compare(db_fields, db_daily, portal_fields, portal_daily):
    summary_rows = []
    daily_diff_rows = []
    all_dates = list(july_dates())

    field_ids = sorted(set(db_fields) | set(portal_fields))
    for field_id in field_ids:
        db_field = db_fields.get(field_id, {})
        portal_field = portal_fields.get(field_id, {})

        db_total = sum(db_daily.get((field_id, day), 0.0) for day in all_dates)
        portal_total = sum(portal_daily.get((field_id, day), 0.0) for day in all_dates)
        diff = db_total - portal_total
        diff_pct = (diff / portal_total * 100) if portal_total else 0.0
        db_days = sum((field_id, day) in db_daily for day in all_dates)
        portal_days = sum((field_id, day) in portal_daily for day in all_dates)
        missing_in_db = [
            day for day in all_dates if (field_id, day) not in db_daily and (field_id, day) in portal_daily
        ]
        missing_in_portal = [
            day for day in all_dates if (field_id, day) in db_daily and (field_id, day) not in portal_daily
        ]

        for day in all_dates:
            db_value = db_daily.get((field_id, day))
            portal_value = portal_daily.get((field_id, day))
            if db_value is None and portal_value is None:
                continue
            daily_diff = (db_value or 0.0) - (portal_value or 0.0)
            if abs(daily_diff) > 0.05 or db_value is None or portal_value is None:
                daily_diff_rows.append(
                    {
                        "solar_field_id": field_id,
                        "name": db_field.get("name") or portal_field.get("name"),
                        "date": day,
                        "delfos_kwh": "" if db_value is None else round(db_value, 3),
                        "portal_kwh": "" if portal_value is None else round(portal_value, 3),
                        "diff_kwh": round(daily_diff, 3),
                        "issue_type": (
                            "missing_in_delfos"
                            if db_value is None
                            else "missing_in_portal"
                            if portal_value is None
                            else "value_mismatch"
                        ),
                    }
                )

        summary_rows.append(
            {
                "solar_field_id": field_id,
                "name": db_field.get("name") or portal_field.get("name"),
                "delfos_total_kwh": round(db_total, 3),
                "portal_total_kwh": round(portal_total, 3),
                "diff_kwh_delfos_minus_portal": round(diff, 3),
                "diff_pct": round(diff_pct, 4),
                "delfos_days": db_days,
                "portal_days": portal_days,
                "delfos_capacity_kwp": db_field.get("capacity_kwp", ""),
                "portal_capacity_kwp": portal_field.get("capacity_kwp", ""),
                "capacity_diff_kwp": round(
                    float(db_field.get("capacity_kwp", 0.0))
                    - float(portal_field.get("capacity_kwp", 0.0)),
                    3,
                ),
                "missing_dates_in_delfos": ";".join(missing_in_db),
                "missing_dates_in_portal": ";".join(missing_in_portal),
                "status": "bate" if abs(diff) <= 0.05 and not missing_in_db and not missing_in_portal else "diverge",
            }
        )

    return summary_rows, daily_diff_rows


def main():
    parser = argparse.ArgumentParser(
        description="Coleta os dados do portal Heliora e compara julho/2026 com delfos.db."
    )
    parser.add_argument("--db", default="delfos.db")
    parser.add_argument("--out", default="outputs")
    parser.add_argument(
        "--with-devices",
        action="store_true",
        help="Tambem coleta series diarias por inversor para investigar causas.",
    )
    args = parser.parse_args()

    out_dir = Path(args.out)
    db_fields, db_daily = load_db(args.db)
    portal_fields, portal_daily, portal_daily_rows, device_rows, device_daily_rows = load_portal(
        include_devices=args.with_devices
    )
    summary_rows, daily_diff_rows = compare(db_fields, db_daily, portal_fields, portal_daily)

    write_csv(
        out_dir / "portal_energy_daily_julho.csv",
        ["solar_field_id", "date", "energy_kwh", "irradiation_kwh_m2"],
        portal_daily_rows,
    )
    write_csv(
        out_dir / "comparacao_julho.csv",
        [
            "solar_field_id",
            "name",
            "delfos_total_kwh",
            "portal_total_kwh",
            "diff_kwh_delfos_minus_portal",
            "diff_pct",
            "delfos_days",
            "portal_days",
            "delfos_capacity_kwp",
            "portal_capacity_kwp",
            "capacity_diff_kwp",
            "missing_dates_in_delfos",
            "missing_dates_in_portal",
            "status",
        ],
        summary_rows,
    )
    write_csv(
        out_dir / "divergencias_diarias_julho.csv",
        ["solar_field_id", "name", "date", "delfos_kwh", "portal_kwh", "diff_kwh", "issue_type"],
        daily_diff_rows,
    )

    if args.with_devices:
        write_csv(
            out_dir / "portal_dispositivos.csv",
            [
                "solar_field_id",
                "device_id",
                "device_name",
                "model",
                "modules",
                "capacity_kwp",
                "status",
            ],
            device_rows,
        )
        write_csv(
            out_dir / "portal_inversores_daily_julho.csv",
            ["solar_field_id", "device_id", "device_name", "date", "energy_kwh"],
            device_daily_rows,
        )

    print("Resumo da conciliacao de julho/2026")
    for row in summary_rows:
        print(
            f"{row['solar_field_id']} | {row['name']} | "
            f"Delfos={row['delfos_total_kwh']:.1f} kWh | "
            f"Portal={row['portal_total_kwh']:.1f} kWh | "
            f"Diff={row['diff_kwh_delfos_minus_portal']:.1f} kWh "
            f"({row['diff_pct']:.3f}%) | {row['status']}"
        )
    print(f"\nArquivos gerados em: {out_dir.resolve()}")


if __name__ == "__main__":
    main()
