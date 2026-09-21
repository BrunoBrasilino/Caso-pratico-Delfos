import csv
import sqlite3
import unittest
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
START_DATE = date(2026, 7, 1)
TOLERANCE_KWH = 0.05
TOLERANCE_KWP = 0.01


def read_csv(name):
    with (OUTPUTS / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class ReconciliationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.portal_daily = read_csv("portal_energy_daily_julho.csv")
        cls.device_daily = read_csv("portal_inversores_daily_julho.csv")
        cls.devices = read_csv("portal_dispositivos.csv")
        cls.comparison = {
            row["solar_field_id"]: row for row in read_csv("comparacao_julho.csv")
        }

        with sqlite3.connect(ROOT / "delfos.db") as connection:
            cls.db_daily = {
                (field_id, day): float(energy)
                for field_id, day, energy in connection.execute(
                    """
                    select solar_field_id, date, energy_kwh
                    from energy_daily
                    where date between '2026-07-01' and '2026-07-31'
                    """
                )
            }

    def test_portal_has_complete_unique_daily_coverage(self):
        field_ids = set(self.comparison)
        expected = {
            (field_id, (START_DATE + timedelta(days=offset)).isoformat())
            for field_id in field_ids
            for offset in range(31)
        }
        actual = [
            (row["solar_field_id"], row["date"]) for row in self.portal_daily
        ]

        self.assertEqual(len(actual), len(set(actual)), "Portal tem datas duplicadas")
        self.assertEqual(set(actual), expected, "Portal tem datas ausentes ou extras")

    def test_device_daily_sum_matches_each_solar_field(self):
        by_field_day = defaultdict(float)
        for row in self.device_daily:
            by_field_day[(row["solar_field_id"], row["date"])] += float(
                row["energy_kwh"]
            )

        for row in self.portal_daily:
            key = (row["solar_field_id"], row["date"])
            self.assertAlmostEqual(
                by_field_day[key],
                float(row["energy_kwh"]),
                delta=TOLERANCE_KWH,
                msg=f"Soma dos inversores difere da usina em {key}",
            )

    def test_sf001_gap_is_exactly_inverter_05(self):
        portal = {
            row["date"]: float(row["energy_kwh"])
            for row in self.portal_daily
            if row["solar_field_id"] == "SF-001"
        }
        inverter_05 = {
            row["date"]: float(row["energy_kwh"])
            for row in self.device_daily
            if row["device_id"] == "SF-001-INV-05"
        }
        self.assertEqual(set(portal), set(inverter_05))

        for day, portal_kwh in portal.items():
            db_kwh = self.db_daily[("SF-001", day)]
            self.assertAlmostEqual(
                portal_kwh - db_kwh,
                inverter_05[day],
                delta=TOLERANCE_KWH,
                msg=f"Lacuna da SF-001 nao corresponde ao INV-05 em {day}",
            )

        monthly_gap = sum(portal.values()) - sum(
            self.db_daily[("SF-001", day)] for day in portal
        )
        self.assertAlmostEqual(
            monthly_gap,
            sum(inverter_05.values()),
            delta=TOLERANCE_KWH,
        )

        device = next(
            row for row in self.devices if row["device_id"] == "SF-001-INV-05"
        )
        comparison = self.comparison["SF-001"]
        capacity_gap = float(comparison["portal_capacity_kwp"]) - float(
            comparison["delfos_capacity_kwp"]
        )
        self.assertAlmostEqual(
            capacity_gap,
            float(device["capacity_kwp"]),
            delta=TOLERANCE_KWP,
        )

    def test_sf005_has_only_the_expected_missing_day(self):
        portal_days = {
            row["date"]
            for row in self.portal_daily
            if row["solar_field_id"] == "SF-005"
        }
        db_days = {
            day for field_id, day in self.db_daily if field_id == "SF-005"
        }
        self.assertEqual(portal_days - db_days, {"2026-07-08"})
        self.assertEqual(db_days - portal_days, set())


if __name__ == "__main__":
    unittest.main()
