"""Offline tests for scripts/history.py. Run: python scripts/test_history.py
Pages below are made up, shaped like the real ones. No network."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import history as H  # noqa: E402

VIN = "1FADP3F28EL403646"
OTHER = "1FADP3F28EL403647"
TODAY = "2026-10-08"

def am_page(vin, miles="116311", doc="SALVAGE CERTIFICATE OF TITLE", bid="150"):
    opt = lambda k, v: f'<div class="card1__option"><div class="card1__category">{k}</div>\n<div class="card1__value">{v}</div></div>'
    return (f'<meta name="description" content="Ford FOCUS 2014 | vin: {vin} находится на аукционной площадке Copart в США.">'
            f'<meta property="og:image" content="https://cs.copart.com/a_ful.jpg"/>'
            f'<li><span>Лот:</span> #59460663</li><li><span>VIN:</span> {vin}</li>'
            + opt("Состояние:", "Заводится и едет") + opt("Пробег:", miles) + opt("Основ. поврежд:", "MINOR DENT/SCRATCHES")
            + opt("Втор. поврежд:", "-") + opt("Ключи:", "Есть") + opt("Место стоянки:", "MD - BALTIMORE EAST")
            + opt("Тип документа:", doc) + opt("Текущая ставка:", bid) + opt("Статус продажи:", "Продан"))

def au_search(vin, runs):
    out = f"{len(runs)} vehicles in search result"
    for date, miles in runs:
        out += (f'<div class="product-default"><a href="/{date}/2014/Ford/Focus/{vin}">x</a>'
                f'<span>Date sale: {date}</span><span>|</span><span>Auction: manheim</span>'
                f'<i class="fal fa-tachometer-alt"></i>\n<span>{miles}</span><span>CR 4.2</span><span>$26000.00</span></div>')
    return out

def au_detail(vin):
    return (f'{{"vehicleIdentificationNumber": "{vin}", "offers": {{"price": 1}}}}'
            '<a href="/image/x.jpg" alt="Front Bumper | Prev Repair &amp;#8729; SubStd Panel Gaps/Misaligned"></a>'
            '<img alt="Left Front">')

def bh_page(vin):
    return f"<title>VIN {vin} - 2014 Ford Focus | BidHistory</title><h1>VIN {vin}</h1> sold for USD 4,100"


class FakeWeb:
    """Answers by URL. A value can be (status, body) or an Exception to raise."""
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def __call__(self, url):
        self.calls.append(url)
        for key, val in self.pages.items():
            if key in url:
                if isinstance(val, Exception):
                    raise val
                return val
        return 404, "not found"

def fetcher(pages):
    web = FakeWeb(pages)
    return H.Fetcher(gap=0, opener=web, sleep=lambda s: None), web


class ExactVin(unittest.TestCase):
    def test_americamotors_needs_the_exact_vin(self):
        self.assertEqual(H.parse_americamotors(am_page(OTHER), VIN, "u"), [])
        self.assertEqual(H.parse_americamotors(am_page(VIN[:16]), VIN, "u"), [])
        r = H.parse_americamotors(am_page(VIN), VIN, "u")[0]
        self.assertEqual((r["lot"], r["miles"], r["doc"], r["where"], r["auction"]),
                         ("59460663", 116311, "SALVAGE CERTIFICATE OF TITLE", "Baltimore East, MD", "Copart"))
        self.assertEqual(r["damage"], ["MINOR DENT/SCRATCHES"])
        self.assertNotIn("date", r)                      # the page has no date, so none is made up

    def test_autousa_ignores_other_vins(self):
        page = au_search(OTHER, [("20250225", "17,913")]) + au_search(VIN, [("20250304", "17,913")])
        runs = H.parse_autousa_search(page, VIN)
        self.assertEqual([r["date"] for r in runs], ["2025-03-04"])
        self.assertIsNone(H.parse_autousa_detail(au_detail(OTHER), VIN))

    def test_bidhistory_link_only(self):
        f, _ = fetcher({"bidhistory.info": (200, bh_page(VIN))})
        st, recs, url = H.check_bidhistory(f, VIN)
        self.assertEqual(st, "found")
        self.assertEqual(recs, [{"src": "bidhistory", "url": url, "linkOnly": True}])   # nothing copied
        f, _ = fetcher({"bidhistory.info": (404, "Vehicle Not Found")})
        self.assertEqual(H.check_bidhistory(f, VIN)[0], "none")
        f, _ = fetcher({"bidhistory.info": (200, bh_page(OTHER))})
        with self.assertRaises(H.Unavailable):              # a page about another VIN is not a "no record"
            H.check_bidhistory(f, VIN)


class Prices(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(H.classify_price("Sold for"), "sale")
        self.assertEqual(H.classify_price("Final sale price"), "sale")
        self.assertEqual(H.classify_price("Current bid"), "bid")
        self.assertEqual(H.classify_price("Текущая ставка"), "bid")
        self.assertEqual(H.classify_price("Buy Now"), "ask")
        self.assertEqual(H.classify_price("Estimated retail value"), "estimate")
        self.assertIsNone(H.classify_price(""))

    def test_abbreviated_title_brands(self):
        for doc in ("CERT OF TITLE-SLVG REBLD FLOOD", "SALVAGE (Massachusetts)", "CERT OF TITLE-SALVAGED", "RBLT TITLE"):
            self.assertTrue(H.flags_of([{"src": "americamotors", "doc": doc}]), doc)
        for doc in ("CLEAR TITLE", "Wait Title", "CERTIFICATE OF TITLE"):
            self.assertFalse(H.flags_of([{"src": "americamotors", "doc": doc}]), doc)

    def test_bid_is_never_a_sale_price(self):
        r = H.parse_americamotors(am_page(VIN), VIN, "u")[0]
        self.assertEqual(r["bid"], 150)
        self.assertNotIn("sale", r)
        runs = H.parse_autousa_search(au_search(VIN, [("20250225", "17,913")]), VIN)
        self.assertFalse(any("26000" in str(v) for v in runs[0].values()))   # unlabeled amount dropped


class Mileage(unittest.TestCase):
    def test_later_lower_reading_is_a_possible_discrepancy(self):
        recs = [{"src": "autousa", "date": "2024-01-10", "miles": 90000},
                {"src": "autousa", "date": "2025-02-25", "miles": 41000}]
        f = H.mileage_flags(recs)
        self.assertEqual(len(f), 1)
        self.assertIn("Possible mileage discrepancy", f[0]["t"])
        self.assertIn("not proof", f[0]["t"])

    def test_rising_readings_are_fine(self):
        self.assertEqual(H.mileage_flags([{"src": "autousa", "date": "2024-01-10", "miles": 40000},
                                          {"src": "autousa", "date": "2025-02-25", "miles": 41000}]), [])

    def test_zero_is_unknown_not_a_reading(self):
        f = H.mileage_flags([{"src": "americamotors", "miles": 0},
                             {"src": "autousa", "date": "2025-02-25", "miles": 17913}])
        self.assertEqual(len(f), 1)
        self.assertIn("Treated as unknown", f[0]["t"])

    def test_undated_conflict_keeps_both_readings(self):
        f = H.mileage_flags([{"src": "americamotors", "miles": 116311},
                             {"src": "autousa", "date": "2025-02-25", "miles": 98000}])
        self.assertEqual(len(f), 1)
        self.assertIn("116,311 (AmericaMotors, date unknown)", f[0]["t"])
        self.assertIn("98,000 (autousa.pro, Feb 25, 2025)", f[0]["t"])
        self.assertIn("Order unknown", f[0]["t"])


class Research(unittest.TestCase):
    def run_once(self, pages, cache=None, today=TODAY):
        f, web = fetcher(pages)
        cache = {} if cache is None else cache
        H.research([(VIN, "Ford", "Focus")], cache, fetcher=f, today=today, log=lambda *a: None)
        return cache, web

    def test_found_everywhere(self):
        cache, web = self.run_once({
            "americamotors.com": (200, am_page(VIN)),
            "autousa.pro/search": (200, au_search(VIN, [("20250211", "17,913"), ("20250225", "17,913")])),
            "autousa.pro/2025": (200, au_detail(VIN)),
            "bidhistory.info": (200, bh_page(VIN))})
        c = H.card(VIN, cache, True)
        self.assertEqual(c["st"], "found")
        self.assertTrue(any("title document SALVAGE CERTIFICATE OF TITLE" in f["t"] for f in c["flags"]))
        self.assertTrue(any("Front Bumper: previous repair, substandard panel gaps/misaligned" in f["t"] for f in c["flags"]))
        auto = [e for e in c["ev"] if e["src"] == "autousa"]
        self.assertEqual(len(auto), 1)                     # two weekly runs, same reading, one event
        self.assertEqual(auto[0]["dates"], ["2025-02-11", "2025-02-25"])
        self.assertEqual(cache[VIN]["recs"][0]["seen"], TODAY)
        self.assertEqual(len(web.calls), 5)               # 1 + 1 search + 2 details + 1

    def test_empty_results_are_not_clean(self):
        cache, _ = self.run_once({"americamotors.com": (410, "gone"), "autousa.pro": (200, "No results found"),
                                  "bidhistory.info": (404, "Vehicle Not Found")})
        c = H.card(VIN, cache, True)
        self.assertEqual(c["st"], "none")
        self.assertNotIn("flags", c)
        self.assertNotIn("clean", str(c).lower())

    def test_failures_mark_unavailable_and_keep_evidence(self):
        cache, _ = self.run_once({"americamotors.com": (200, am_page(VIN)), "autousa.pro": (200, "No results found"),
                                  "bidhistory.info": (404, "")})
        cache, web = self.run_once({"americamotors.com": (503, "down"), "autousa.pro": (403, "blocked"),
                                    "bidhistory.info": TimeoutError("slow")}, cache, today="2026-11-20")
        c = H.card(VIN, cache, True)
        self.assertEqual(c["st"], "found")                 # earlier evidence survives the failed run
        am = next(s for s in c["src"] if s["id"] == "americamotors")
        self.assertEqual((am["st"], am["at"], am["fail"]["err"]), ("found", TODAY, "HTTP 503"))
        bh = next(s for s in c["src"] if s["id"] == "bidhistory")
        self.assertEqual(bh["fail"]["err"], "TimeoutError: slow")              # the reason is kept for the log
        self.assertEqual(sum("autousa" in u for u in web.calls), 1)   # 403 is not retried

    def test_changed_page_is_unavailable_not_empty(self):
        cache, _ = self.run_once({"americamotors.com": (200, "<html>new design</html>"),
                                  "autousa.pro": (200, "<html>new design</html>"), "bidhistory.info": (404, "")})
        c = H.card(VIN, cache, True)
        self.assertEqual(c["st"], "partial")
        self.assertEqual({s["id"]: s["st"] for s in c["src"]},
                         {"americamotors": "error", "autousa": "error", "bidhistory": "none"})

    def test_all_sources_down(self):
        cache, _ = self.run_once({"americamotors.com": (500, ""), "autousa.pro": (429, ""), "bidhistory.info": (403, "")})
        self.assertEqual(H.card(VIN, cache, True)["st"], "unavailable")

    def test_bot_challenge_is_not_bypassed(self):
        f, web = fetcher({"americamotors.com": (403, "<title>Just a moment...</title>")})
        with self.assertRaises(H.Unavailable):
            f.get("https://americamotors.com/ford/focus/" + VIN)
        self.assertEqual(len(web.calls), 1)

    def test_breaker_stops_asking_a_failing_site(self):
        f, web = fetcher({"americamotors.com": (503, "")})
        for _ in range(5):
            with self.assertRaises(H.Unavailable):
                f.get("https://americamotors.com/x/x/" + VIN)
        self.assertEqual(len(web.calls), H.BREAKER * H.TRIES)

    def test_removed_record_is_kept_and_marked(self):
        cache, _ = self.run_once({"americamotors.com": (200, am_page(VIN))})
        cache, _ = self.run_once({"americamotors.com": (410, "")}, cache, today="2026-11-20")
        rec = next(r for r in cache[VIN]["recs"] if r["src"] == "americamotors")
        self.assertEqual((rec["seen"], rec["gone"]), (TODAY, "2026-11-20"))

    def test_cache_avoids_repeat_requests(self):
        pages = {"americamotors.com": (410, ""), "autousa.pro": (200, "No results found"), "bidhistory.info": (404, "")}
        cache, _ = self.run_once(pages)
        _, web = self.run_once(pages, cache, today="2026-10-12")
        self.assertEqual(web.calls, [])
        _, web = self.run_once(pages, cache, today="2026-10-19")      # none is rechecked after 10 days
        self.assertEqual(len(web.calls), 3)

    def test_invalid_vin_is_not_checked(self):
        self.assertEqual(H.card("VIN BLOCKED", {}, False)["st"], "unchecked")
        self.assertEqual(H.card(VIN, {}, True)["st"], "unchecked")


if __name__ == "__main__":
    unittest.main()
