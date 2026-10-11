"""Typical auto loan balances from SEC loan level filings, so a lien card can show what loans like it usually still owe.

Big lenders that sell loans to investors in public deals file every loan each month (Form ABS-EE, exhibit EX-102):
make, model, year, state, original amount, current balance, payment, months left. There is no VIN, so this is
never a specific car's payoff, only the range for that lender, model and year. Lenders that sell privately
(Westlake, Credit Acceptance, Lendbuzz, Global Lending, CPS and others) file nothing.

The same files record each car's value when the loan was made. For used cars whose lender took that value from a
pricing guide (NADA or Kelley Blue Book), the median over the last 12 months of loans is a book value by make, model
and year: data/value_stats.json.

Run monthly:  SEC_CONTACT=you@example.com python scripts/balances.py
The SEC asks automated requests to name a contact (User-Agent). The address comes from the environment only and is
never written to the repo. Output: data/balance_stats.json and data/value_stats.json, read by update.py.
"""
import array, datetime as dt, gzip, io, json, os, re, sys, time, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "balance_stats.json"
VOUT = ROOT / "data" / "value_stats.json"
GAP = 0.2                 # SEC allows 10 requests a second; stay well under
NS = "{http://www.sec.gov/edgar/document/absee/autoloan/assetdata}"

# Lienholder name on the city list -> trusts on EDGAR that hold that lender's public loans. The label is what cards
# show: Capital One's public deals hold only its prime loans, Santander's include its Chrysler Capital brand, Hyundai
# Capital's include Kia and Genesis, GM Financial's include AmeriCredit, World Omni services Southeast Toyota.
FAMILIES = {
    "santander": ("Santander Consumer", r"SANTANDER(?! BANK)|CHRYSLER CAPITAL",
                  r"^(SANTANDER DRIVE|DRIVE) AUTO RECEIVABLES TRUST"),
    "capitalone": ("Capital One prime", r"CAPITAL ONE", r"^CAPITAL ONE PRIME AUTO RECEIVABLES TRUST"),
    "ally": ("Ally", r"\bALLY\b", r"^ALLY AUTO RECEIVABLES TRUST"),
    "toyota": ("Toyota Motor Credit", r"TOYOTA MOTOR CREDIT|LEXUS FINANCIAL", r"^TOYOTA AUTO RECEIVABLES"),
    "honda": ("American Honda Finance", r"AMERICAN HONDA FINANCE|HONDA FINANCIAL|ACURA FINANCIAL",
              r"^HONDA AUTO RECEIVABLES"),
    "exeter": ("Exeter", r"EXETER", r"^EXETER (SELECT )?AUTOMOBILE RECEIVABLES TRUST"),
    "carvana": ("Carvana", r"CARVANA", r"^CARVANA AUTO RECEIVABLES TRUST"),
    "bridgecrest": ("Bridgecrest", r"BRIDGECREST", r"^BRIDGECREST LENDING AUTO SECURITIZATION TRUST"),
    "gmf": ("GM Financial", r"AMERICREDIT|GM FINANCIAL|GENERAL MOTORS FINANCIAL",
            r"^(AMERICREDIT AUTOMOBILE|GM FINANCIAL CONSUMER AUTOMOBILE) RECEIVABLES TRUST"),
    "hyundai": ("Hyundai Capital", r"HYUNDAI (MOTOR FINANCE|CAPITAL)|KIA (MOTORS )?FINANCE|GENESIS FINANCE",
                r"^HYUNDAI AUTO RECEIVABLES TRUST"),
    "vw": ("VW Credit", r"VW CREDIT(?!.*LEAS)|VOLKSWAGEN CREDIT|AUDI FINANCIAL", r"^VOLKSWAGEN AUTO LOAN ENHANCED TRUST"),
    "mercedes": ("Mercedes-Benz Financial", r"MERCEDES.?BENZ FIN|MBFS", r"^MERCEDES-BENZ AUTO RECEIVABLES TRUST"),
    "bmw": ("BMW Financial", r"\bBMW\b", r"^BMW VEHICLE OWNER TRUST"),
    "ford": ("Ford Credit", r"FORD (MOTOR )?CREDIT", r"^FORD CREDIT AUTO OWNER TRUST"),
    "nissan": ("Nissan Motor Acceptance", r"NISSAN MOTOR ACCEPTANCE|INFINITI FINANCIAL", r"^NISSAN AUTO RECEIVABLES"),
    "worldomni": ("World Omni", r"WORLD OMNI|SOUTHEAST TOYOTA", r"^WORLD OMNI AUTO RECEIVABLES TRUST"),
    "carmax": ("CarMax", r"CARMAX", r"^CARMAX AUTO OWNER TRUST"),
}

# Vehicle value source code (Schedule AL item 3(d)(7)): 1 invoice, 2 MSRP, 3 Kelley Blue Book, 98 other. What "98"
# means is in each trust's EX-103 notes (checked Oct 2026): a NADA or Kelley Blue Book guide for these lenders.
# Left out: CarMax and Carvana (their own sale price), Bridgecrest (its cost to buy and recondition), Mercedes
# (Manheim wholesale), BMW (MSRP for used cars), World Omni (mixed sources).
GUIDE_98 = {"santander", "exeter", "capitalone", "gmf", "ford"}
VALUE_MONTHS = 12

def family_of(lien):
    """Family id for a lienholder name, judged on the first name listed. None when it files nothing public."""
    first = (lien or "").split("/")[0].upper()
    if re.search(r"\bLEAS(E|ING)\b|TITLING TRUST", first):
        return None                           # lease companies own the car; their payoff is a buyout, not a loan
    for fid, (_, lien_rx, _) in FAMILIES.items():
        if re.search(lien_rx, first):
            return fid
    return None

def compact(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())

def http(url, ua, tries=4):
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=120) as r:
                body = r.read()
                if body[:2] == b"\x1f\x8b":            # gzip, either as transfer encoding or a .gz file
                    body = gzip.decompress(body)
                time.sleep(GAP)
                return body
        except Exception as e:
            err = e
            time.sleep(5 * (i + 1))
    raise err

def quarters(today):
    q = (today.month - 1) // 3 + 1
    prev = (today.year, q - 1) if q > 1 else (today.year - 1, 4)
    return [prev, (today.year, q)]

FORM_ROW = re.compile(r"^ABS-EE\s+(.+?)\s{2,}(\d+)\s+(\d{4}-\d{2}-\d{2})\s+(edgar/\S+)\s*$")

def latest_filings(ua, today):
    """Newest ABS-EE per trust for every family, from the last two quarterly form indexes."""
    rows = []
    for y, q in quarters(today):
        try:
            idx = http(f"https://www.sec.gov/Archives/edgar/full-index/{y}/QTR{q}/form.gz", ua).decode("latin-1")
        except Exception as e:
            print(f"  index {y} Q{q} unavailable: {e}")
            continue
        for line in idx.splitlines():
            m = FORM_ROW.match(line)
            if m:
                rows.append(m.groups())
    best = {}
    for name, cik, date, path in rows:
        fid = next((f for f, (_, _, trust_rx) in FAMILIES.items() if re.search(trust_rx, name.upper())), None)
        if fid and (name not in best or date > best[name][2]):
            best[name] = (fid, cik, date, path)
    newest = max((b[2] for b in best.values()), default="0000")
    cutoff = (dt.date.fromisoformat(newest) - dt.timedelta(days=75)).isoformat() if best else ""
    return {n: b for n, b in best.items() if b[2] >= cutoff}       # trusts still reporting

def ex102_url(ua, cik, path):
    acc = Path(path).stem
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}"
    try:                                         # the filing's own list says which document is EX-102
        head = http(f"{base}/{acc}-index-headers.html", ua).decode("latin-1").replace("&lt;", "<").replace("&gt;", ">")
        typed = dict(re.findall(r"<TYPE>([^\s<]+)\s*<SEQUENCE>[^<]*<FILENAME>([^\s<]+)", head))
        if not typed:
            typed = {t: f for t, f in re.findall(r"<TYPE>([^\s<]+)[\s\S]{0,200}?<FILENAME>([^\s<]+)", head)}
        if typed.get("EX-102", "").lower().endswith(".xml"):
            return f"{base}/{typed['EX-102']}"
    except Exception:
        pass
    items = json.loads(http(f"{base}/index.json", ua))["directory"]["item"]
    xmls = [i["name"] for i in items if i["name"].lower().endswith(".xml")]
    # ex102.xml, exh1024650082026.xml, bmw2025-a_exhibit102.xml, exh_102.xml; CarMax names it cart20243.xml
    name = next((n for n in xmls if re.search(r"ex(h|hibit)?[-_]?102", n, re.I)), None)
    if not name:
        rest = [n for n in xmls if "103" not in n]
        name = rest[0] if len(rest) == 1 else None
    return f"{base}/{name}" if name else None

def assets(xml_bytes):
    """Field getter for each loan in an EX-102 file."""
    for _, el in ET.iterparse(io.BytesIO(xml_bytes), events=("end",)):
        if el.tag == NS + "assets":
            yield lambda k, el=el: (el.findtext(NS + k) or "").strip()
            el.clear()

def loan_of(g):
    """Active loan: (make, model, year, state, balance, payment, months left, period end), else None."""
    try:
        bal = float(g("reportingPeriodActualEndBalanceAmount") or 0)
    except ValueError:
        return None
    if bal > 0 and g("zeroBalanceCode") in ("", "99") and g("repossessedIndicator") != "true":   # 99: not paid off
        try:
            return (compact(g("vehicleManufacturerName")), re.sub(r"\s+", " ", g("vehicleModelName").upper()),
                    int(g("vehicleModelYear") or 0), g("obligorGeographicLocation")[:2], bal,
                    float(g("reportingPeriodScheduledPaymentAmount") or 0), int(float(g("remainingTermToMaturityNumber") or 0)),
                    g("reportingPeriodEndingDate"))
        except ValueError:
            return None
    return None

def loans(xml_bytes):
    for g in assets(xml_bytes):
        ln = loan_of(g)
        if ln:
            yield ln

def make_key(name):
    """One key per make across lenders: CHEVROLET, CHEVROLET TRUCKS and CHEVROLE are all CHEVROLE."""
    return re.sub(r"(TRUCKS?|MOTORS?|DIVISION)$", "", compact(name))[:8]

def value_of(g, fid):
    """Used car valued from a pricing guide: (make key, model, year, origination YYYY-MM, value), else None."""
    src = g("vehicleValueSourceCode")
    if g("vehicleNewUsedCode") != "2" or not (src == "3" or (src == "98" and fid in GUIDE_98)):
        return None
    m = re.fullmatch(r"(\d\d)[/-](?:\d\d[/-])?(\d{4})", g("originationDate"))
    try:
        v, yr = float(g("vehicleValueAmount") or 0), int(g("vehicleModelYear") or 0)
    except ValueError:
        return None
    if not m or v < 500 or not yr or (src == "98" and v % 25):
        return None                  # guide values come in $25 steps; Santander and Exeter also file sale prices as 98
    return make_key(g("vehicleManufacturerName")), re.sub(r"\s+", " ", g("vehicleModelName").upper()), yr, f"{m[2]}-{m[1]}", v

def month_add(ym, k):
    y, m = int(ym[:4]), int(ym[5:7]) - 1 + k
    return f"{y + m // 12}-{m % 12 + 1:02d}"

def value_stats(vals, asof, min_n=5):
    """Book values from the last VALUE_MONTHS months of loans: make -> year -> model -> stats."""
    start = month_add(asof[:7], 1 - VALUE_MONTHS)
    out = {}
    for (mk, cm, yr), (ms, vs, spell) in vals.items():
        keep = [(m, v) for m, v in zip(ms, vs) if start <= m <= asof[:7]]
        if len(keep) < min_n:
            continue
        v = [x[1] for x in keep]
        out.setdefault(mk, {}).setdefault(str(yr), {})[cm] = {
            "n": len(v), "p25": pct(v, .25), "p50": pct(v, .5), "p75": pct(v, .75),
            "from": min(x[0] for x in keep), "to": max(x[0] for x in keep),
            "name": max(spell.items(), key=lambda x: x[1])[0]}
    return out

def pct(a, p):
    s = sorted(a)
    return round(s[min(len(s) - 1, int(p * (len(s) - 1) + 0.5))]) if s else None

def summarize(bals, pays, terms):
    return {"n": len(bals), "p25": pct(bals, .25), "p50": pct(bals, .5), "p75": pct(bals, .75), "p90": pct(bals, .9),
            "pay": pct([p for p in pays if p > 0], .5), "left": pct([t for t in terms if t > 0], .5)}

def main():
    ua = os.environ.get("SEC_CONTACT", "").strip()
    if "@" not in ua:
        print("SEC_CONTACT not set, skipping SEC balance update")
        return 0
    ua = f"NYCAuctionScout {ua}"
    only = set(sys.argv[1:])                     # optional family ids, for testing
    today = dt.date.today()
    filings = latest_filings(ua, today)
    if only:
        filings = {n: b for n, b in filings.items() if b[0] in only}
    print(f"{len(filings)} trusts to read")
    agg = {}                                     # (family, make, model, year) -> [bals, pays, terms, ny_bals]
    names = {}                                   # compact model -> {written name: count}, to show the common spelling
    asof, makes = "", {}
    vals = {}                                    # (make key, compact model, year) -> [origination months, values, spellings]
    oldest = month_add(today.isoformat()[:7], -VALUE_MONTHS - 3)
    for name, (fid, cik, date, path) in sorted(filings.items()):
        try:
            url = ex102_url(ua, cik, path)
            if not url:
                print(f"  {name}: no loan file"); continue
            n = nv = 0
            for g in assets(http(url, ua)):
                vl = value_of(g, fid)
                if vl and vl[3] >= oldest and vl[2] >= today.year - 25 and compact(vl[1]):
                    mk, md, yr, ym, v = vl
                    a = vals.setdefault((mk, compact(md), yr), [[], array.array("f"), {}])
                    a[0].append(ym); a[1].append(v); a[2][md] = a[2].get(md, 0) + 1
                    nv += 1
                ln = loan_of(g)
                if not ln:
                    continue
                mk, md, yr, state, bal, pay, left, period = ln
                if yr < today.year - 25:
                    continue
                cm = compact(md)                 # "3-SERIES" and "3 SERIES" are one model
                if not cm:
                    continue
                spell = names.setdefault((mk, cm), {})
                spell[md] = spell.get(md, 0) + 1
                a = agg.setdefault((fid, mk, cm, yr), [array.array("f"), array.array("f"), array.array("h"), array.array("f")])
                a[0].append(bal); a[1].append(pay); a[2].append(left)
                if state == "NY":
                    a[3].append(bal)
                makes[(fid, mk)] = makes.get((fid, mk), 0) + 1
                p = f"{period[6:10]}-{period[0:2]}-{period[3:5]}" if re.fullmatch(r"\d\d-\d\d-\d{4}", period) else ""
                asof = max(asof, p)
                n += 1
            print(f"  {name} {date}: {n} active loans, {nv} recent used car values")
        except Exception as e:
            print(f"  {name}: failed, {e}")
    old = json.loads(OUT.read_text()) if only and OUT.exists() else {}
    stats = {f: v for f, v in old.get("stats", {}).items() if f not in only}     # a partial run keeps other lenders
    for (fid, mk, md, yr), (b, p, t, ny) in agg.items():
        if len(b) < 3:
            continue
        s = summarize(b, p, t)
        s["name"] = max(names[(mk, md)].items(), key=lambda x: x[1])[0]
        if len(ny) >= 5:
            s["ny"] = {"n": len(ny), "p25": pct(ny, .25), "p50": pct(ny, .5), "p75": pct(ny, .75)}
        stats.setdefault(fid, {}).setdefault(mk, {}).setdefault(str(yr), {})[md] = s
    if not agg:
        print("no loans read, keeping the previous file")
        return 1
    asof = max(asof, old.get("asOf", "")) if old else asof
    OUT.write_text(json.dumps({"asOf": asof, "built": today.isoformat(),
                               "families": {f: FAMILIES[f][0] for f in stats},
                               "trusts": len(filings) + (old.get("trusts", 0) if old else 0), "stats": stats},
                              separators=(",", ":"), sort_keys=True))
    if only:
        print("partial run: value_stats.json needs every lender, left as is")
    elif vals:
        vstats = value_stats(vals, asof)
        VOUT.write_text(json.dumps({"asOf": asof, "built": today.isoformat(), "months": VALUE_MONTHS, "stats": vstats},
                                   separators=(",", ":"), sort_keys=True))
        print(f"wrote {VOUT.name}: {sum(len(y) for m in vstats.values() for y in m.values())} model groups from "
              f"{sum(len(x[1]) for x in vals.values())} used car values")
    print(f"wrote {OUT.name}: {sum(len(y) for f in stats.values() for m in f.values() for y in m.values())} model groups, "
          f"as of {asof}; makes by family: " + ", ".join(f"{f}:{m}" for (f, m), c in sorted(makes.items()) if c > 500)[:600])
    return 0

if __name__ == "__main__":
    sys.exit(main())
