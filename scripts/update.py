"""Pull NYC Finance vehicle auction lists, decode every VIN, write data/auctions.json.

Run: python scripts/update.py            (normal daily run)
     python scripts/update.py --force    (re-parse every PDF even if unchanged)
     python scripts/update.py --pdf FILE --id auction-100826-bronx   (parse a local PDF, for testing)
"""
import argparse, datetime as dt, hashlib, io, json, re, sys, time
import urllib.error, urllib.parse, urllib.request
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "auctions.json"
VIN_CACHE = DATA / "vin_cache.json"
MODEL_CACHE = DATA / "model_cache.json"

PAGE = "https://www.nyc.gov/site/finance/vehicles/auctions.page"
BASE = "https://www.nyc.gov"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
KEEP_PAST_DAYS = 14
MODEL_TTL_DAYS = 30

BOROUGHS = {"bronx": "Bronx", "brooklyn": "Brooklyn", "queens": "Queens",
            "statenisland": "Staten Island", "manhattan": "Manhattan"}
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"

# ---------- helpers ----------

def http(url, data=None, tries=5, binary=False):
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=60) as r:
                b = r.read()
                return b if binary else json.loads(b)
        except urllib.error.HTTPError as e:
            if e.code == 400 and not binary:   # NHTSA answers 400 with a valid body when there are 0 results
                try:
                    return json.loads(e.read())
                except Exception:
                    pass
            err = e
        except Exception as e:
            err = e
        time.sleep(3 * (i + 1))
    raise err

def load(p, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default

TR = {**{str(i): i for i in range(10)}, **dict(zip("ABCDEFGH", range(1, 9))),
      **dict(zip("JKLMN", range(1, 6))), "P": 7, "R": 9, **dict(zip("STUVWXYZ", range(2, 10)))}
W = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]

def vin_ok(v):
    if len(v) != 17 or any(c not in TR for c in v):
        return False
    s = sum(TR[c] * w for c, w in zip(v, W)) % 11
    return v[8] == ("X" if s == 10 else str(s))

# ---------- city site ----------

def list_pdfs():
    html = http(PAGE, binary=True).decode("utf-8", "replace")
    links = re.findall(r'href="([^"]*/downloads/pdf/auction/auction-[^"]+\.pdf)"', html, re.I)
    seen, out = set(), []
    for href in links:
        url = href if href.startswith("http") else BASE + href
        aid = Path(urllib.parse.urlparse(url).path).stem.lower()
        if aid not in seen:
            seen.add(aid); out.append((aid, url))
    return out

def borough_of(aid):
    for k, v in BOROUGHS.items():
        if aid.endswith(k):
            return v
    return aid.split("-")[-1].title()

def date_from_id(aid):
    m = re.search(r"auction-(\d{6,8})-", aid)
    if not m:
        return None
    s = m.group(1)
    try:
        return dt.datetime.strptime(s, "%m%d%y" if len(s) == 6 else "%m%d%Y").date().isoformat()
    except ValueError:
        return None

# ---------- PDF parsing ----------

ROW = re.compile(r"^\s*(\d{1,3})\s+(\d{4})\s+(.+)$")

def split_row(rest):
    t = rest.split()
    vi = None
    for i, tok in enumerate(t):
        if tok.upper() == "VIN" and i + 1 < len(t) and t[i + 1].upper() == "BLOCKED":
            vi, vin, after = i, "VIN BLOCKED", t[i + 2:]
            break
        if len(tok) == 17 and tok.isalnum() and any(c.isdigit() for c in tok):
            vi, vin, after = i, tok.upper(), t[i + 1:]
            break
    if vi is None:  # VIN typed with the wrong length: take the token right after the 2 letter state
        for i in range(2, len(t)):
            if re.fullmatch(r"[A-Z]{2}", t[i - 1]) and t[i].isalnum() and 10 <= len(t[i]) <= 19 \
                    and any(c.isdigit() for c in t[i]):
                vi, vin, after = i, t[i].upper(), t[i + 1:]
                break
    if vi is None or vi < 2:
        return None
    state = t[vi - 1] if re.fullmatch(r"[A-Z]{2}", t[vi - 1]) else ""
    pi = vi - 2 if state else vi - 1
    plate = t[pi] if pi >= 1 else ""
    make = " ".join(t[:pi]) if pi >= 1 else " ".join(t[:vi])
    return dict(make=make, plate=plate, st=state, vin=vin, lien=" ".join(after))

# words that start the second half of a lienholder name wrapped inside its cell
WRAP_START = {"FINANCIAL", "FINANCE", "FIANANCE", "SERVICES", "SERVICE", "SERV", "SVCS", "ACCEPTANCE", "ACCEPTABLE",
              "CORP", "CORP.", "CORPORATION", "LLC", "LLC.", "INC", "INC.", "CO", "CO.", "CREDIT", "UNION", "FUNDING",
              "AUTO", "LENDING", "BANK", "FCU", "GROUP", "NETWORK", "FEDERAL", "MOTOR", "TITLE", "TITTLE", "AND",
              "TRUST", "TRUS", "COMMERCIAL", "USA", "NA", "LEASING", "TITLING", "HONDA", "LTD", "FIN"}
# make names that wrap in the narrow MAKE column and land on their own line
MAKE_TAILS = {"ROMEO", "ROVER", "BENZ", "BEN", "LAND", "ALFA", "ROLLS", "ROYCE", "ASTON", "MARTIN"}
FOOTER = re.compile(r"\b\d{5}\b|NEW YORK|PARKING|DEPARTMENT|PEOPLE|STATE OF|VIOLATIONS|MOTOR VEHICLES|DATED|"
                    r"SHERIFF|MARSHAL|AUCTION|PAGE|LIENHOLDER|PLATE|VEHICLE ID|NOTICE|CITY OF")

def join_lien(cur, frag):
    first = frag.split()[0].upper()
    if first in WRAP_START or len(cur.split()) == 1:
        return cur + " " + frag
    return cur + " / " + frag

ADDR = re.compile(r"\b\d{2,5}\s+(?:[A-Z][A-Za-z']*\s+){1,3}(?:STREET|ST|AVENUE|AVE|BOULEVARD|BLVD|ROAD|RD|PLACE|PL)\b\.?"
                  r"(?:,?\s*(?:BRONX|BROOKLYN|QUEENS|STATEN ISLAND|NEW YORK|[A-Z][a-z]+(?: [A-Z][a-z]+)?))?(?:,?\s*N\.?\s?Y\.?)?(?:,?\s*\d{5})?", re.I)

def nice(s):
    s = " ".join(w if re.fullmatch(r"(N\.?Y\.?|NY)", w, re.I) else w.capitalize() for w in s.split())
    return re.sub(r"'S\b", "'s", s.replace("N.y.", "N.Y."))

def find_location(flat):
    for m in ADDR.finditer(flat):
        if re.search(r"ADAMS|JORALEMON", m.group(0), re.I):
            continue
        addr = m.group(0).strip(" ,.")
        pre = flat[max(0, m.start() - 60):m.start()]
        venue = pre.rsplit(" at ", 1)[-1].strip(" ,") if " at " in pre.lower() else ""
        venue = re.split(r"\bat\b", venue, flags=re.I)[-1].strip(" ,")
        if not venue or re.search(r"\d{1,2}:\d{2}|o.?clock|morning|noon", venue, re.I) or len(venue) > 35:
            venue = ""
        return {"location": nice((venue + ", " if venue else "") + addr)}
    return {}

def parse_pdf(blob):
    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    rows, last = {}, None
    for line in text.splitlines():
        m = ROW.match(line)
        r = split_row(m.group(3)) if m else None
        if m and r:
            n = int(m.group(1))
            r.update(n=n, year=int(m.group(2)))
            if n not in rows:              # header block repeats per page, keep first copy
                rows[n] = r
            last = rows[n]
            continue
        s = line.strip()
        ok = (last is not None and last["lien"] and s and len(s) <= 45 and s.upper() == s
              and re.fullmatch(r"[A-Z0-9&.,'/ \-]+", s) and not FOOTER.search(s) and s not in MAKE_TAILS)
        if ok:
            last["lien"] = join_lien(last["lien"], s)
        elif s:
            last = None   # anything else ends the row (footers, headers, make fragments)
    meta = {}
    m = re.search(rf"({MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})", text, re.I)
    if m:
        try:
            meta["date"] = dt.datetime.strptime(f"{m.group(1).title()} {m.group(2)} {m.group(3)}", "%B %d %Y").date().isoformat()
        except ValueError:
            pass
    flat = re.sub(r"\s+", " ", text)
    m = re.search(r"(\d{1,2}:\d{2})\s*(?:o.?clock)?\s*(?:in\s+the\s+)?(A\.?\s?M\b|P\.?\s?M\b|morning|afternoon|noon)", flat, re.I)
    if m:
        ap = m.group(2).lower()
        meta["time"] = m.group(1) + ("am" if ap.startswith("a") or ap == "morning" else "pm")
    meta.update(find_location(flat))
    return [rows[k] for k in sorted(rows)], meta

# ---------- NHTSA ----------

def decode_vins(vins, cache):
    need = [v for v in vins if v not in cache and vin_ok(v)]
    for i in range(0, len(need), 50):
        body = urllib.parse.urlencode({"format": "json", "data": ";".join(need[i:i + 50])}).encode()
        res = http("https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVINValuesBatch/", body)
        for d in res["Results"]:
            keep = ["Make", "Model", "ModelYear", "Trim", "Series", "BodyClass", "DisplacementL",
                    "EngineCylinders", "FuelTypePrimary", "ElectrificationLevel", "DriveType",
                    "TransmissionStyle", "TransmissionSpeeds", "PlantCity", "PlantCountry"]
            cache[d["VIN"]] = {k: d.get(k, "") for k in keep}
        time.sleep(1)

def model_stats(make, model, year, cache):
    k = f"{make}|{model}|{year}"
    hit = cache.get(k)
    today = dt.date.today()
    if hit and (today - dt.date.fromisoformat(hit["at"])).days < MODEL_TTL_DAYS:
        return hit
    q = urllib.parse.urlencode({"make": make, "model": model, "modelYear": year})
    try:
        rec = http(f"https://api.nhtsa.gov/recalls/recallsByVehicle?{q}").get("results", [])
        comp = http(f"https://api.nhtsa.gov/complaints/complaintsByVehicle?{q}").get("results", [])
    except Exception as e:
        print("  NHTSA lookup failed", k, e)
        return hit
    areas = {}
    for c in comp:
        for p in (c.get("components") or "").split(","):
            p = p.strip()
            if p:
                areas[p] = areas.get(p, 0) + 1
    top = sorted(areas.items(), key=lambda x: -x[1])[:3]
    cache[k] = {"at": today.isoformat(), "rc": len(rec), "c": len(comp),
                "crash": sum(1 for c in comp if c.get("crash")), "fire": sum(1 for c in comp if c.get("fire")),
                "top": ", ".join(f"{a.lower()} {n}" for a, n in top)}
    return cache[k]

BODY = {"Sport Utility Vehicle (SUV)/Multipurpose Vehicle (MPV)": "SUV", "Crossover Utility Vehicle (CUV)": "SUV",
        "Sedan/Saloon": "Sedan", "Cargo Van": "Van", "Convertible/Cabriolet": "Convertible",
        "Hatchback/Liftback/Notchback": "Hatchback", "Sport Utility Truck (SUT)": "Pickup"}
DRIVE = {"AWD/All-Wheel Drive": "AWD", "4WD/4-Wheel Drive/4x4": "4WD", "FWD/Front-Wheel Drive": "FWD",
         "RWD/Rear-Wheel Drive": "RWD", "4x2": "2WD", "4x4": "4WD"}

def body_short(b):
    b = b.replace("[", "(").replace("]", ")")
    if b in BODY: return BODY[b]
    if b in ("Minivan", "Coupe", "Wagon", "Pickup"): return b
    if "Van" in b: return "Van"
    if any(w in b for w in ("Truck", "Incomplete", "Bus")): return "Truck"
    return b or ""

def engine(d):
    parts = []
    try:
        if d["DisplacementL"]: parts.append(f'{float(d["DisplacementL"]):.1f}L')
    except ValueError:
        pass
    if d["EngineCylinders"]: parts.append(d["EngineCylinders"] + "cyl")
    if d["FuelTypePrimary"] and d["FuelTypePrimary"] != "Gasoline": parts.append(d["FuelTypePrimary"])
    el = d["ElectrificationLevel"]
    if "Strong HEV" in el: parts.append("Hybrid")
    elif "PHEV" in el: parts.append("Plug in hybrid")
    elif "BEV" in el and "Electric" not in parts: parts.append("Electric")
    return " ".join(parts)

def tidy(s):
    s = s.title() if s and s.isupper() else s
    return re.sub(r"\b(Llc|Inc|Na|Fcu|Usa|Bmw|Vw|Gm|Cps|Td|Hvt|Esl|Teg|Gfa|Jsac|Ccap|Fin|Svcs)\b",
                  lambda m: m.group(0).upper(), s or "")

# ---------- build ----------

def build_car(r, vc, mc):
    v = r["vin"]
    car = {"n": r["n"], "listYear": r["year"], "listMake": r["make"], "plate": f'{r["plate"]} {r["st"]}'.strip(),
           "vin": v, "lien": tidy(r["lien"]), "flags": []}
    if not vin_ok(v):
        car["flags"].append("VIN not listed by the city, no decode possible" if v == "VIN BLOCKED"
                            else "VIN fails its check digit, likely a typo on the city list")
        return car
    d = vc.get(v) or {}
    mk = d.get("Make", "")
    car.update(year=int(d["ModelYear"]) if d.get("ModelYear", "").isdigit() else r["year"],
               make=mk if mk in ("BMW", "GMC", "KIA", "RAM", "MINI") else mk.title(),
               model=d.get("Model", ""), trim=" ".join(x for x in [d.get("Trim", ""), d.get("Series", "")] if x),
               body=body_short(d.get("BodyClass", "")), engine=engine(d) if d else "",
               drive=DRIVE.get(d.get("DriveType", ""), d.get("DriveType", "")))
    if d.get("ModelYear", "").isdigit() and int(d["ModelYear"]) != r["year"]:
        car["flags"].append(f'City list says {r["year"]}, VIN says {d["ModelYear"]}')
    if mk and d.get("Model") and d.get("ModelYear"):
        s = model_stats(mk, d["Model"], d["ModelYear"], mc)
        if s:
            car.update(recalls=s["rc"], complaints=s["c"], crashFire=f'{s["crash"]}/{s["fire"]}', topComplaints=s["top"])
    return car

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--pdf"); ap.add_argument("--id")
    a = ap.parse_args()

    store = load(OUT, {"auctions": []})
    by_id = {x["id"]: x for x in store["auctions"]}
    vc, mc = load(VIN_CACHE, {}), load(MODEL_CACHE, {})
    today = dt.date.today()

    sources = [(a.id, None)] if a.pdf else list_pdfs()
    print(f"{len(sources)} auction PDFs on the city page")
    for aid, url in sources:
        if date_from_id(aid) and date_from_id(aid) < (today - dt.timedelta(days=KEEP_PAST_DAYS)).isoformat():
            continue
        try:
            blob = Path(a.pdf).read_bytes() if a.pdf else http(url, binary=True)
        except Exception as e:
            print(f"  {aid}: download failed, keeping previous data ({e})")
            continue
        h = hashlib.sha256(blob).hexdigest()[:16]
        old = by_id.get(aid)
        if old and old.get("hash") == h and not a.force:
            print(f"  {aid}: unchanged")
            continue
        try:
            rows, meta = parse_pdf(blob)
        except Exception as e:
            print(f"  {aid}: could not read PDF ({e})")
            continue
        if not rows:
            print(f"  {aid}: no vehicle rows found, skipped")
            continue
        decode_vins([r["vin"] for r in rows], vc)
        cars = [build_car(r, vc, mc) for r in rows]
        bad = sum(1 for c in cars if not vin_ok(c["vin"]))
        by_id[aid] = {"id": aid, "borough": borough_of(aid), "date": meta.get("date") or date_from_id(aid),
                      "time": meta.get("time", ""), "location": meta.get("location", ""), "pdf": url or "",
                      "hash": h, "fetched": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
                      "cars": cars}
        print(f"  {aid}: {len(cars)} lots, {bad} without a valid VIN, {meta}")

    cutoff = (today - dt.timedelta(days=KEEP_PAST_DAYS)).isoformat()
    auctions = sorted((x for x in by_id.values() if (x.get("date") or "9999") >= cutoff),
                      key=lambda x: (x.get("date") or "", x["borough"]))
    # cars that come back on another list
    seen = {}
    for x in auctions:
        for c in x["cars"]:
            if vin_ok(c["vin"]):
                seen.setdefault(c["vin"], []).append((x["date"], x["borough"], c["n"]))
    for x in auctions:
        for c in x["cars"]:
            c["flags"] = [f for f in c["flags"] if not f.startswith("Also on")]
            other = [o for o in seen.get(c["vin"], []) if (o[0], o[1]) != (x["date"], x["borough"])]
            if other:
                c["flags"].append("Also on " + ", ".join(
                    f'{dt.date.fromisoformat(d).strftime("%-m/%-d")} {b} lot {n}' for d, b, n in other))
    DATA.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
                               "auctions": auctions}, separators=(",", ":")))
    VIN_CACHE.write_text(json.dumps(vc, separators=(",", ":"), sort_keys=True))
    MODEL_CACHE.write_text(json.dumps(mc, separators=(",", ":"), sort_keys=True))
    print(f"wrote {len(auctions)} auctions")

if __name__ == "__main__":
    sys.exit(main())
