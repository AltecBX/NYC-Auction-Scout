"""Offline tests for typical lien balances (scripts/balances.py and balance_for in update.py).
Run: python scripts/test_balances.py"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import balances as B  # noqa: E402
import update as U  # noqa: E402

U.make_models = lambda make: {"NISSAN": {"Rogue", "Rogue Sport", "Altima"}, "FORD": {"Bronco", "Bronco Sport", "F-150"}}.get(
    make.upper(), set())          # no network: the sibling list vPIC would give

def st(n, p50, name):
    return {"n": n, "p25": p50 - 2000, "p50": p50, "p75": p50 + 2000, "p90": p50 + 4000, "pay": 300, "left": 30, "name": name}

STATS = {"asOf": "2026-08-31", "families": {"capitalone": "Capital One, prime loans only", "santander": "Santander Consumer",
                                            "hyundai": "Hyundai Capital (Hyundai, Kia, Genesis)"},
         "stats": {
             "capitalone": {"NISSAN": {"2016": {"ROGUE": st(40, 9000, "ROGUE"), "ROGUESPORT": st(90, 12000, "ROGUE SPORT")}},
                            "CHEVROLE": {"2018": {"SILVERADO15": st(60, 21000, "SILVERADO 15"),
                                                  "SILVERADO25": st(80, 30000, "SILVERADO 25")}},
                            "HONDA": {"2022": {"ACCORD": st(50, 18000, "ACCORD"), "ACCORDHYBRI": st(20, 22000, "ACCORD HYBRI")}}},
             "santander": {"MERCEDES": {"2017": {"CCLASS": st(12, 11000, "C CLASS")}},
                           "NISSAN": {"2015": {"ALTIMA": st(3, 7000, "ALTIMA")}}},
             "hyundai": {"KIA": {"2020": {"SPORTAGE": st(70, 9500, "SPORTAGE")}}}}}

def car(make, model, year, **kw):
    return {"Make": make, "Model": model, "ModelYear": str(year), **kw}


class Families(unittest.TestCase):
    def test_lienholder_names(self):
        cases = {"CAPITAL ONE AUTO FINANCE": "capitalone", "SANTANDER CONSUMER USA, INC.": "santander",
                 "CHRYSLER CAPITAL": "santander", "KIA MOTORS FINANCE": "hyundai", "AMERICREDIT FINANCIAL SERVICE": "gmf",
                 "EXETER FIANANCE LLC": "exeter", "BMW FINANCIAL SERVICES / ROUTE 46 CHRYSLER LLC": "bmw",
                 "MERCEDES-BENZ FIN SERV USA LLC": "mercedes", "VW CREDIT INC": "vw",
                 # private lenders, lease companies and old Chrysler finance file nothing public
                 "WESTLAKE FINANCIAL SERVICES": None, "CREDIT ACCEPTANCE CORP": None, "LENDBUZZ FUNDING LLC": None,
                 "VW CREDIT LEASING LTD": None, "HYUNDAI LEASE TITLING TRUST": None, "DC FIN SVCS AMER LLC": None,
                 "CCAP AUTO LEASE LTD": None}
        for name, want in cases.items():
            self.assertEqual(B.family_of(name), want, name)


class Matching(unittest.TestCase):
    def test_exact_model(self):
        b = U.balance_for("CAPITAL ONE AUTO FINANCE", car("NISSAN", "Rogue", 2016), STATS)
        self.assertEqual((b["name"], b["p50"], b["n"]), ("ROGUE", 9000, 40))
        self.assertEqual(b["fam"], "Capital One, prime loans only")

    def test_sibling_model_is_not_used(self):
        stats = {**STATS, "stats": {"capitalone": {"NISSAN": {"2016": {"ROGUESPORT": st(90, 12000, "ROGUE SPORT")}}}}}
        self.assertIsNone(U.balance_for("CAPITAL ONE", car("NISSAN", "Rogue", 2016), stats))

    def test_truncated_make_and_series(self):
        b = U.balance_for("CAPITAL ONE", car("CHEVROLET", "Silverado", 2018, Series="1500"), STATS)
        self.assertEqual(b["name"], "SILVERADO 15")

    def test_hybrid_names_only_for_hybrids(self):
        gas = U.balance_for("CAPITAL ONE", car("HONDA", "Accord", 2022), STATS)
        hyb = U.balance_for("CAPITAL ONE", car("HONDA", "Accord", 2022,
                                              ElectrificationLevel="Strong HEV (Hybrid Electric Vehicle)"), STATS)
        self.assertEqual((gas["name"], hyb["name"]), ("ACCORD", "ACCORD HYBRI"))

    def test_mercedes_class(self):
        b = U.balance_for("CHRYSLER CAPITAL", car("MERCEDES-BENZ", "C-Class", 2017, Trim="C300"), STATS)
        self.assertEqual(b["name"], "C CLASS")

    def test_kia_in_hyundai_trusts(self):
        self.assertEqual(U.balance_for("KIA MOTORS FINANCE", car("KIA", "Sportage", 2020), STATS)["p50"], 9500)

    def test_too_few_loans_or_no_data(self):
        self.assertIsNone(U.balance_for("SANTANDER", car("NISSAN", "Altima", 2015), STATS))        # 3 loans
        self.assertIsNone(U.balance_for("WESTLAKE FINANCIAL", car("NISSAN", "Rogue", 2016), STATS))
        self.assertIsNone(U.balance_for("CAPITAL ONE", car("NISSAN", "Rogue", 2017), STATS))      # no year
        self.assertIsNone(U.balance_for("CAPITAL ONE", car("NISSAN", "Rogue", 2016), {}))          # no file yet


class Stats(unittest.TestCase):
    def test_percentiles(self):
        s = B.summarize([1000, 2000, 3000, 4000, 5000], [200, 0, 300, 250, 220], [10, 20, 0, 30, 40])
        self.assertEqual((s["n"], s["p25"], s["p50"], s["p75"]), (5, 2000, 3000, 4000))
        self.assertEqual((s["pay"], s["left"]), (250, 30))                     # nearest rank, zeros skipped

    def test_loans_skips_paid_off_and_repossessed(self):
        ns = 'xmlns="http://www.sec.gov/edgar/document/absee/autoloan/assetdata"'
        rec = lambda bal, extra="": (f"<assets><vehicleManufacturerName>Nissan</vehicleManufacturerName><vehicleModelName>Rogue "
                                     f"</vehicleModelName><vehicleModelYear>2016</vehicleModelYear><obligorGeographicLocation>NY"
                                     f"</obligorGeographicLocation><reportingPeriodActualEndBalanceAmount>{bal}"
                                     f"</reportingPeriodActualEndBalanceAmount><reportingPeriodScheduledPaymentAmount>250"
                                     f"</reportingPeriodScheduledPaymentAmount><remainingTermToMaturityNumber>20"
                                     f"</remainingTermToMaturityNumber><reportingPeriodEndingDate>08-31-2026"
                                     f"</reportingPeriodEndingDate>{extra}</assets>")
        xml = (f"<assetData {ns}>" + rec(9000) + rec(0, "<zeroBalanceCode>1</zeroBalanceCode>")
               + rec(7000, "<zeroBalanceCode>99</zeroBalanceCode>")       # BMW marks open loans 99
               + rec(4000, "<zeroBalanceCode>1</zeroBalanceCode>")
               + rec(5000, "<repossessedIndicator>true</repossessedIndicator>") + "</assetData>").encode()
        got = list(B.loans(xml))
        self.assertEqual([g[4] for g in got], [9000.0, 7000.0])
        self.assertEqual(got[0][:5], ("NISSAN", "ROGUE", 2016, "NY", 9000.0))


if __name__ == "__main__":
    unittest.main()
