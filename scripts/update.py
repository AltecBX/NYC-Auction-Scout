"""Pull NYC Finance vehicle auction lists, decode every VIN, write data/auctions.json.

Run: python scripts/update.py            (normal daily run)
     python scripts/update.py --force    (re-parse every PDF even if unchanged)
     python scripts/update.py --pdf FILE --id auction-100826-bronx   (parse a local PDF, for testing)
"""
import argparse, datetime as dt, hashlib, io, json, os, re, sys, time
import urllib.error, urllib.parse, urllib.request
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
import view_check  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "auctions.json"
VIN_CACHE = DATA / "vin_cache.json"
MODEL_CACHE = DATA / "model_cache.json"
PHOTO_CACHE = DATA / "photo_cache.json"
NCAP_CACHE = DATA / "ncap_cache.json"
RAW = DATA / "raw.json"

PAGE = "https://www.nyc.gov/site/finance/vehicles/auctions.page"
BASE = "https://www.nyc.gov"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
KEEP_PAST_DAYS = 14
MODEL_TTL_DAYS = 30
PHOTO_RETRY_DAYS = 21          # look again for models that had no photo
PHOTO_BUDGET = 450             # max new photo lookups per run, keeps runs short
VIN_CACHE_VERSION = 2
WIKI_UA = "NYCAuctionScout/1.0 (https://github.com/AltecBX/NYC-Auction-Scout)"

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

ADDR = re.compile(r"\b\d{2,5}\s+(?:[A-Z][A-Za-z']*\s+){1,3}(?:STREET|ST|AVENUE|AVE|BOULEVARD|BLVD|ROAD|RD|PLACE|PL|PARKWAY|PKWY|DRIVE|DR|LOOP|LANE|LN|HIGHWAY|HWY)\b\.?"
                  r"(?:,?\s*(?:BRONX|BROOKLYN|QUEENS|STATEN ISLAND|NEW YORK|[A-Z][a-z]+(?: [A-Z][a-z]+)?))?(?:,?\s*N\.?\s?Y\.?)?(?:,?\s*\d{5})?", re.I)

def nice(s):
    s = " ".join(w if re.fullmatch(r"(N\.?Y\.?|NY)", w, re.I) else w.capitalize() for w in s.split())
    return re.sub(r"'S\b", "'s", s.replace("N.y.", "N.Y."))

SALE_AT = re.compile(r"(?:o.?clock\s+in\s+the\s+(?:morning|afternoon)|\d{1,2}:\d{2}\s*[AP]\.?\s?M\.?|noon)"
                     r"(?:\s*\([^)]{0,40}\))?\s*,?\s+at\s+"
                     r"(.{6,140}?\b(?:N\.?\s?Y\.?|NEW YORK)\.?,?\s*\d{5})\b", re.I)
CITY = r"(BRONX|BROOKLYN|QUEENS|STATEN ISLAND|NEW YORK|FAR ROCKAWAY|ARVERNE|FLUSHING|JAMAICA|LONG ISLAND CITY|ASTORIA|MASPETH|COLLEGE POINT|WOODSIDE|CORONA)"

def tidy_place(p):
    p = re.sub(r"\s+", " ", p).strip(" ,.")
    p = re.sub(r"\s+(\d[\d\-]*\s+[A-Za-z0-9])", r", \1", p, count=1)              # venue, street number
    p = re.sub(rf",?\s+{CITY},?\s+(N\.?\s?Y\.?|NEW YORK)\.?,?\s*(\d{{5}})$", r", \1, NY \3", p, flags=re.I)
    p = re.sub(r"\s*,\s*,", ",", p)
    p = re.sub(r"\bN\.?\s?Y\.?(?=,? \d{5})|\bNew York(?=,? \d{5}$)", "NY", p, flags=re.I)
    return nice(p).replace(", Ny ", ", NY ")

def find_location(flat):
    m = SALE_AT.search(flat)
    if m and not re.search(r"ADAMS|JORALEMON", m.group(1), re.I):
        return {"location": tidy_place(m.group(1))}
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

VPIC_KEEP = ["Make", "Model", "ModelYear", "Trim", "Series", "BodyClass", "DisplacementL", "EngineCylinders",
             "EngineHP", "Turbo", "FuelTypePrimary", "ElectrificationLevel", "DriveType", "TransmissionStyle",
             "TransmissionSpeeds", "Doors", "Seats", "PlantCity", "PlantState", "PlantCountry",
             "RearVisibilitySystem", "BlindSpotMon", "AdaptiveCruiseControl", "ForwardCollisionWarning", "CIB",
             "LaneDepartureWarning", "LaneKeepSystem", "RearCrossTrafficAlert", "KeylessIgnition", "ParkAssist"]
FEATURES = [("RearVisibilitySystem", "Backup camera"), ("BlindSpotMon", "Blind spot"),
            ("AdaptiveCruiseControl", "Adaptive cruise"), ("CIB", "Auto braking"),
            ("ForwardCollisionWarning", "Collision warning"), ("LaneKeepSystem", "Lane keep"),
            ("LaneDepartureWarning", "Lane departure"), ("RearCrossTrafficAlert", "Rear cross traffic"),
            ("ParkAssist", "Park assist"), ("KeylessIgnition", "Push start")]

def decode_vins(vins, cache):
    need = [v for v in dict.fromkeys(vins)
            if vin_ok(v) and (v not in cache or cache[v].get("_v") != VIN_CACHE_VERSION)]
    for i in range(0, len(need), 50):
        body = urllib.parse.urlencode({"format": "json", "data": ";".join(need[i:i + 50])}).encode()
        res = http("https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVINValuesBatch/", body)
        for d in res["Results"]:
            cache[d["VIN"]] = {**{k: d.get(k, "") for k in VPIC_KEEP}, "_v": VIN_CACHE_VERSION}
        time.sleep(1)
    if need:
        print(f"decoded {len(need)} VINs")

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

# ---------- NCAP stars ----------

def ncap(make, model, year, body, drive, cache):
    k = f"{make}|{model}|{year}"
    if k in cache and (dt.date.today() - dt.date.fromisoformat(cache[k]["at"])).days < 90:
        return cache[k]
    out = {"at": dt.date.today().isoformat()}
    try:
        path = "/".join(urllib.parse.quote(str(x)) for x in (year, "make", make, "model", model))
        res = http(f"https://api.nhtsa.gov/SafetyRatings/modelyear/{path}").get("Results", [])
        if res:
            want = {"SUV": "SUV", "Pickup": "PU", "Minivan": "VAN", "Van": "VAN", "Sedan": "4 DR",
                    "Coupe": "2 DR", "Convertible": "C", "Hatchback": "HB"}.get(body, "")
            def score(r):
                desc = r["VehicleDescription"].upper()
                return 2 * bool(want and want in desc) + bool(drive and drive in desc)
            pickr = max(res, key=score)
            det = http(f'https://api.nhtsa.gov/SafetyRatings/VehicleId/{pickr["VehicleId"]}').get("Results", [{}])[0]
            out.update(stars=det.get("OverallRating", ""), desc=pickr["VehicleDescription"])
    except Exception as e:
        print("  NCAP lookup failed", k, e)
        return cache.get(k)
    cache[k] = out
    return out

# ---------- stock photo (Wikimedia Commons, then Wikipedia) ----------

PHOTO_VERSION = 4
PHOTO_BAD = re.compile(r"interior|\bengine|\bdash|cockpit|\brear\b|(?<!hatch)\bback\b|badge|emblem|\blogo|\bwheels?\b(?!base)|"
                       r"\brims?\b|\bseats?\b|\btrunk|\bboot\b|crash|wreck|damag|tail ?light|head ?light|steering|odometer|"
                       r"gauge|instrument|\bconsole|detail|\bgrille|\bhood\b|mirror|police|taxi|\bfire\b|ambulance|"
                       r"\brac(?:e|ing)\b|\brally|nascar|\bdrift|modified|tuned|concept|prototype|interieur|innenraum|\bheck\b|"
                       r"\bmotor\b|cutaway|chassis|model car|\btoys?\b|\blego\b|diecast|die.cast|\bscale\b|sketch|drawing|"
                       r"\binside\b|\bcabin\b|\bcargo\b|armatur|salpicadero|habitacle|intérieur|interno|\binnen|tachometer|"
                       r"speedometer|\bkeys?\b|door panel|underside|\btires?\b|\btyres?\b", re.I)
# checked against the file's categories and description, where words like "rear-wheel drive" are harmless
VIEW_BAD = re.compile(r"interior|interieur|intérieur|innen|cockpit|dashboard|armaturen|steering wheel|\bseats?\b|"
                      r"trunk|cargo area|boot space|engine bay|engine compartment|motorraum|under the hood|"
                      r"rear view|rear-view|rear three|rear 3/4|rear quarter|rear left|rear right|from behind|"
                      r"back view|heckansicht|rückansicht|arrière|tail ?lights?|wheels? of|close.?up|detail", re.I)
ABROAD = re.compile(r"\bin (?:the )?(?:United Kingdom|England|Scotland|Wales|Ireland|Japan|Germany|France|Italy|Spain|"
                    r"Netherlands|Belgium|Poland|Russia|China|Taiwan|Hong Kong|Korea|South Korea|Thailand|Malaysia|Indonesia|"
                    r"Philippines|India|Australia|New Zealand|Brazil|Mexico|Argentina|Chile|Colombia|Israel|Turkey|Austria|"
                    r"Switzerland|Sweden|Norway|Denmark|Finland|Czech Republic|Hungary|Portugal|Greece|Ukraine|South Africa|"
                    r"Singapore|Vietnam|Pakistan|Egypt|Iran|Saudi Arabia|United Arab Emirates|Romania|Bulgaria|Serbia|Croatia)\b")
FRONT = re.compile(r"front|frontal|frontansicht|vorne|avant|delantera|three.quarter|3/4|\bFL\b|\bFR\b", re.I)
WIKI_HEADERS = {"User-Agent": WIKI_UA}
# US market photos look like the cars at a NYC auction; overseas versions of the same name can differ a lot
US_CUES = re.compile(r"NHTSA|\b\d\d-\d\d-\d{4}\b|NYIAS|NYAS|New York|Washington|\bDC\b|Chicago|Detroit|NAIAS|LA Auto|"
                     r"\bUS\b|USA|America|front (?:left|right)", re.I)
NON_US = re.compile(r"Euro|JDM|\bcc\b|\d{3,4}cc|\(\d+ ?PS\)|TDCi|\bTDI\b|diesel|Indonesia|Jakarta|Japan|Thailand|Malaysia|"
                    r"Philippines|India|China|Chinese|Sanming|Australia|\bUK\b|Taiwan|Korea|Brazil|Mexico|Russia|Europe|"
                    r"Germany|France|Italy|Spain|Netherlands|Poland|Norway|Sweden|Automatic \d|Manual \d|SIAM|Bangkok|"
                    r"Kuala|Manila|Tokyo|Beijing|Shanghai|Seoul|RHD|Argentina|Chile|Colombia|Peru|South Africa", re.I)

def wm_api(host, params):
    req = urllib.request.Request(f"https://{host}/w/api.php?" + urllib.parse.urlencode({"format": "json", **params}),
                                 headers=WIKI_HEADERS)
    for i in range(6):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(int(e.headers.get("Retry-After") or 0) or 5 * (i + 1))
    return {}

def commons_search(q):
    d = wm_api("commons.wikimedia.org", {
        "action": "query", "generator": "search", "gsrnamespace": 6, "gsrlimit": 30,
        "gsrsearch": q + " filetype:bitmap", "prop": "imageinfo|categories", "clshow": "!hidden", "cllimit": "max",
        "iiprop": "url|extmetadata|size", "iiurlwidth": 800,
        "iiextmetadatafilter": "Artist|LicenseShortName|ImageDescription"})
    return list(d.get("query", {}).get("pages", {}).values())

def strip_html(x):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x or "")).strip()

def photo_entry(ii, y, t, kind):
    m = ii.get("extmetadata", {})
    return {"img": ii["thumburl"], "page": ii["descriptionurl"], "y": y, "by": strip_html(m.get("Artist", {}).get("value"))[:60],
            "lic": m.get("LicenseShortName", {}).get("value", ""), "t": t[:120], "k": kind, "v": PHOTO_VERSION}

def word_rx(s):
    parts = [re.escape(x) for x in re.split(r"[^A-Za-z0-9]+", s) if x]
    return re.compile(r"(?<![a-z0-9])" + r"[\s\-_]?".join(parts) + r"(?![a-z0-9])", re.I) if parts else None

_MAKE_MODELS = {}

def other_models(make, model):
    """Longer model names from the same make that start with this model, e.g. Rogue Sport for Rogue,
    Accord Crosstour for Accord. A photo titled with one of those is a different vehicle."""
    mk = make.lower()
    if mk not in _MAKE_MODELS:
        try:
            res = http(f"https://vpic.nhtsa.dot.gov/api/vehicles/GetModelsForMake/{urllib.parse.quote(mk)}?format=json")
            _MAKE_MODELS[mk] = {r["Model_Name"].strip() for r in res.get("Results", [])}
        except Exception:
            _MAKE_MODELS[mk] = set()
    base = model.lower()
    return [m for m in _MAKE_MODELS[mk] if m.lower().startswith(base + " ") and len(m) > len(model)]

def title_ok(t, make, model, allow_overseas):
    if PHOTO_BAD.search(t):
        return False
    if not allow_overseas and NON_US.search(t):
        return False
    for om in other_models(make, model):
        rx = word_rx(om)
        if rx and rx.search(t):
            return False
    return True

_SPLIT_MARKET = {}

def split_market(make, model):
    """True when Wikipedia keeps a separate North America article, e.g. Honda Odyssey, whose overseas
    namesake is a different vehicle. Those photos must show a US car."""
    k = f"{make}|{model}"
    if k not in _SPLIT_MARKET:
        mk = make if make.upper() in ("BMW", "GMC") else make.title()
        d = wm_api("en.wikipedia.org", {"action": "query", "titles": f"{mk} {model} (North America)", "redirects": 1})
        pages = list(d.get("query", {}).get("pages", {}).values())
        _SPLIT_MARKET[k] = (mk, bool(pages) and "missing" not in pages[0] and "invalid" not in pages[0])
        time.sleep(1)
    return _SPLIT_MARKET[k][1]

US_CAT = re.compile(r"in the United States|in (?:New York|California|Texas|Florida|Virginia|Maryland|Washington|"
                    r"Illinois|Michigan|Ohio|Pennsylvania|New Jersey|Massachusetts|Georgia|North Carolina|Arizona|"
                    r"Colorado|Oregon|Minnesota|Wisconsin|Tennessee|Indiana|Missouri|Connecticut)|North America", re.I)

DEBUG = bool(os.environ.get("PHOTO_DEBUG"))
BODY_CLASH = {"Sedan": r"wagon|tourer|touring|estate|avant|sportback|kombi|variant|hatch|coupe|convertible|cabrio",
              "SUV": r"pickup|pick-up|\bute\b|convertible", "Minivan": r"pickup|cargo van",
              "Coupe": r"sedan|saloon|wagon|estate|tourer", "Hatchback": r"sedan|saloon|wagon|estate",
              "Pickup": r"\bsuv\b|van\b", "Convertible": r"sedan|saloon|wagon"}

def find_photo(year, make, model, body=""):
    """Exterior photo of this make, model and year, front view whenever one exists. Order of preference:
    1. Commons file named with this model year right before the make or model, US version, then up to 2 years
       away, then overseas versions. Photo dates in titles never count as model years. Interior, rear and
       detail shots are rejected using the title, the file's categories and its description.
    2. The lead photo of the model's Wikipedia article (labeled: year may differ).
    Each pick is looked at by a small image model (view_check.py) and only a front view is accepted.
    If no front view exists anywhere, the best side or rear exterior is used rather than no photo."""
    checks = {"n": 0}
    fallback = []          # exterior shots that are not a front view, best first

    def judge(entry):
        """True to accept now. Saves non front exteriors as a fallback."""
        if not view_check.available():
            return True
        if checks["n"] >= 10:
            return False
        checks["n"] += 1
        v = view_check.view_of(entry["img"], WIKI_UA)
        time.sleep(1)
        if DEBUG:
            print("      view:", v and (v[0], {k: x for k, x in v[1].items() if x > .05}), entry["t"])
        if v is None:
            return False
        top, pr = v
        entry["view"] = top
        if top == "front":
            return True
        # a front three quarter shot often scores as "side"; the file name saying front settles it
        if top == "side" and pr["front"] > pr["rear"] and FRONT.search(entry["t"]):
            entry["view"] = "front"
            return True
        if top == "side":
            fallback.append((0 if pr["front"] > pr["rear"] else 1, entry))
        elif top == "rear":
            fallback.append((2, entry))
        return False

    mk = make.replace("-Benz", "")
    md_rx = word_rx(model)
    if md_rx:
        lead = r"(?:%s|%s)" % (r"[\s\-_]?".join(map(re.escape, re.split(r"[^A-Za-z0-9]+", mk))),
                               r"[\s\-_]?".join(map(re.escape, re.split(r"[^A-Za-z0-9]+", model))))
        results = {}
        us_only = split_market(make, model)
        for allow in ((False,) if us_only else (False, True)):
            for y in (year, year - 1, year + 1, year - 2, year + 2):
                if y not in results:
                    results[y] = commons_search(f'"{y}" {make} {model}')
                    time.sleep(1)
                yr = re.compile(rf"(?<![\d\-.])(?:(?:19|20)\d\d\s*[\-–]\s*{y}|{y}(?:\s*[\-–]\s*(?:19|20)?\d\d)?)"
                                rf"(?![\d.])[\s_,]+(?:[A-Za-z\-]+[\s_]+)?{lead}", re.I)
                cands = []
                for p in results[y]:
                    t = p["title"][5:].rsplit(".", 1)[0]
                    why = ("year" if not yr.search(t) else "model" if not md_rx.search(t)
                           else "title" if not title_ok(t, make, model, allow)
                           else "body" if body in BODY_CLASH and re.search(BODY_CLASH[body], t, re.I) else "")
                    if DEBUG:
                        print(f"    {y} {'abroad ok' if allow else 'us'} {why or 'pass'}: {t}")
                    if why:
                        continue
                    ii = p["imageinfo"][0]
                    if ii.get("width", 0) < ii.get("height", 1) * 1.15 or ii.get("width", 0) < 640:
                        continue
                    cats = " ".join(c["title"] for c in p.get("categories", []))
                    desc = strip_html(ii.get("extmetadata", {}).get("ImageDescription", {}).get("value"))[:400]
                    if VIEW_BAD.search(cats) or VIEW_BAD.search(desc):
                        continue
                    if not allow and (ABROAD.search(cats) or NON_US.search(desc)):
                        continue
                    if us_only and not (US_CUES.search(t) or US_CAT.search(cats) or US_CUES.search(desc)):
                        continue
                    lic = ii.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "")
                    if re.search(r"fair use|non.free", lic, re.I):
                        continue
                    sc = (5 * bool(FRONT.search(t) or FRONT.search(desc)) + 2 * bool(re.match(rf"\W*{y}", t))
                          + 2 * bool(US_CUES.search(t)) + 1.5 * bool(re.search(r"\b0?1\)?$", t))
                          - 2 * bool(re.search(r"\b0?2\)?$", t)) - len(t) / 60)
                    cands.append((sc, photo_entry(ii, y, t, "near" if y != year else "exact")))
                for sc, entry in sorted(cands, key=lambda x: -x[0])[:3]:
                    if judge(entry):
                        return entry
    alias = series_alias(make, model)
    if alias:
        got = find_photo(year, make, alias, body)
        if got:
            return got
    wiki = wiki_lead_photo(make, model)
    if wiki and judge(wiki):
        return wiki
    if fallback:
        return sorted(fallback, key=lambda x: x[0])[0][1]
    return wiki

def series_alias(make, model):
    """BMW and Mercedes VINs decode to model numbers (740i, 328xi, E350) that photos rarely use."""
    m = re.match(r"^(\d)\d\d", model)
    if make.upper() == "BMW" and m:
        return f"{m.group(1)} Series"
    m = re.match(r"^([A-Z]{1,3})\d{2,3}", model)
    if make.lower().startswith("mercedes") and m and "Class" not in model:
        return f"{m.group(1)}-Class"
    return None

def wiki_lead_photo(make, model):
    mk = make if make.upper() in ("BMW", "GMC") else make.title()
    first = f"{mk} {model} (North America)" if split_market(make, model) else None
    for title in (first, f"{mk} {model}", f"{mk} {model.split()[0]}" if " " in model else None):
        if not title:
            continue
        d = wm_api("en.wikipedia.org", {"action": "query", "titles": title, "redirects": 1,
                                        "prop": "pageimages", "piprop": "name", "pilicense": "free"})
        time.sleep(1)
        pages = list(d.get("query", {}).get("pages", {}).values())
        name = pages[0].get("pageimage") if pages and "missing" not in pages[0] else None
        if DEBUG: print("    wiki", title, "->", name)
        if not name or PHOTO_BAD.search(name):
            continue
        info = wm_api("commons.wikimedia.org", {"action": "query", "titles": "File:" + name, "prop": "imageinfo",
                                                "iiprop": "url|extmetadata|size", "iiurlwidth": 800,
                                                "iiextmetadatafilter": "Artist|LicenseShortName"})
        time.sleep(1)
        ip = list(info.get("query", {}).get("pages", {}).values())
        if not ip or "imageinfo" not in ip[0]:
            continue
        ii = ip[0]["imageinfo"][0]
        if ii.get("width", 0) < ii.get("height", 1):
            continue
        t = name.rsplit(".", 1)[0].replace("_", " ")
        m = re.match(r"\W*((?:19|20)\d\d)\b(?!-\d\d-)", t)
        return photo_entry(ii, int(m.group(1)) if m else None, t, "model")
    return None

def photo_still_good(hit, mk, md):
    return (hit.get("v") == PHOTO_VERSION and "img" in hit)

def photos_for(combos, cache):
    today = dt.date.today()
    budget = int(os.environ.get("PHOTO_BUDGET") or PHOTO_BUDGET)
    stop_at = time.time() + 60 * float(os.environ.get("PHOTO_MINUTES") or 80)   # leave time to save the run
    done = 0
    for y, mk, md, body in combos:
        k = f"{y}|{mk}|{md}"
        hit = cache.get(k)
        if hit and photo_still_good(hit, mk, md):
            continue
        if hit and hit.get("v") == PHOTO_VERSION and "none" in hit \
                and (today - dt.date.fromisoformat(hit["none"])).days < PHOTO_RETRY_DAYS:
            continue
        if done >= budget or time.time() > stop_at:
            break
        done += 1
        try:
            ph = find_photo(y, mk, md, body)
        except Exception as e:
            print("  photo lookup failed", k, e)
            continue
        cache[k] = ph if ph else {"none": today.isoformat(), "v": PHOTO_VERSION}
        if ph and view_check.available() and not ph.get("view"):
            ph["view"] = "unchecked"
    if done:
        found = sum(1 for y, mk, md, _ in combos if cache.get(f"{y}|{mk}|{md}", {}).get("v") == PHOTO_VERSION
                    and "img" in cache[f"{y}|{mk}|{md}"])
        print(f"photo lookups this run: {done}, models with a checked photo: {found}/{len(combos)}")

# ---------- formatting ----------

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
        if d.get("DisplacementL"): parts.append(f'{float(d["DisplacementL"]):.1f}L')
    except ValueError:
        pass
    if d.get("EngineCylinders"): parts.append(d["EngineCylinders"] + "cyl")
    if d.get("Turbo") == "Yes": parts.append("Turbo")
    if d.get("FuelTypePrimary") and d["FuelTypePrimary"] != "Gasoline": parts.append(d["FuelTypePrimary"])
    el = d.get("ElectrificationLevel", "")
    if "Strong HEV" in el: parts.append("Hybrid")
    elif "PHEV" in el: parts.append("Plug in hybrid")
    elif "BEV" in el and "Electric" not in parts: parts.append("Electric")
    return " ".join(parts)

def trans(d):
    t = d.get("TransmissionStyle", "")
    t = re.sub(r"\s*\(.*?\)", "", t).replace("Continuously Variable", "CVT").replace("Electronic CVT", "eCVT")
    sp = d.get("TransmissionSpeeds", "")
    return f"{sp} speed {t.lower()}".strip() if sp and t else t

def hp(d):
    try:
        return int(float(d.get("EngineHP") or 0)) or None
    except ValueError:
        return None

def tidy(s):
    s = s.title() if s and s.isupper() else s
    return re.sub(r"\b(Llc|Inc|Na|Fcu|Usa|Bmw|Vw|Gm|Cps|Td|Hvt|Esl|Teg|Gfa|Jsac|Ccap|Fin|Svcs)\b",
                  lambda m: m.group(0).upper(), s or "")

def plant(d):
    c = d.get("PlantCountry", "")
    c = re.sub(r"\s*\(.*?\)", "", c).title().replace("Of", "of")
    city = d.get("PlantCity", "").title()
    return ", ".join(x for x in (city, c) if x)

# ---------- build ----------

def make_name(mk):
    return mk if mk in ("BMW", "GMC", "KIA", "RAM", "MINI") else mk.title()

def build_car(r, vc, mc, pc, nc):
    v = r["vin"]
    car = {"n": r["n"], "listYear": r["year"], "listMake": r["make"], "plate": f'{r["plate"]} {r["st"]}'.strip(),
           "vin": v, "lien": tidy(r["lien"]), "flags": []}
    if not vin_ok(v):
        car["flags"].append("VIN not listed by the city, no decode possible" if v == "VIN BLOCKED"
                            else "VIN fails its check digit, likely a typo on the city list")
        return car
    d = vc.get(v) or {}
    mk = d.get("Make", "")
    year = int(d["ModelYear"]) if d.get("ModelYear", "").isdigit() else r["year"]
    car.update(year=year, make=make_name(mk), model=d.get("Model", ""),
               trim=" ".join(x for x in [d.get("Trim", ""), d.get("Series", "")] if x),
               body=body_short(d.get("BodyClass", "")), engine=engine(d), hp=hp(d),
               drive=DRIVE.get(d.get("DriveType", ""), d.get("DriveType", "")), trans=trans(d),
               seats=d.get("Seats", ""), plant=plant(d),
               features=[lab for f, lab in FEATURES if d.get(f) == "Standard"])
    if d.get("ModelYear", "").isdigit() and int(d["ModelYear"]) != r["year"]:
        car["flags"].append(f'City list says {r["year"]}, VIN says {d["ModelYear"]}')
    if mk and d.get("Model") and d.get("ModelYear"):
        s = model_stats(mk, d["Model"], d["ModelYear"], mc)
        if s:
            car.update(recalls=s["rc"], complaints=s["c"], crashFire=f'{s["crash"]}/{s["fire"]}', topComplaints=s["top"])
        st = nc.get(f'{mk}|{d["Model"]}|{d["ModelYear"]}')
        if st and st.get("stars") and st["stars"].isdigit():
            car["stars"] = int(st["stars"]); car["starsFor"] = st["desc"]
        ph = pc.get(f'{year}|{car["make"]}|{car["model"]}')
        if ph and "img" in ph:
            car["photo"] = {k: ph[k] for k in ("img", "page", "y", "by", "lic", "k", "view") if k in ph}
    car = {k: v for k, v in car.items() if v not in ("", None, [])}
    car.setdefault("lien", ""); car.setdefault("flags", [])
    return car

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--pdf"); ap.add_argument("--id")
    ap.add_argument("--no-photos", action="store_true")
    ap.add_argument("--photo-test", help='comma list like "2011|Volvo|XC90,2025|Nissan|Rogue"')
    a = ap.parse_args()
    if a.photo_test:
        for item in a.photo_test.split(","):
            parts = item.strip().split("|")
            print(item, "->", json.dumps(find_photo(int(parts[0]), parts[1], parts[2], parts[3] if len(parts) > 3 else "")))
        return

    raw = load(RAW, {})
    vc, mc = load(VIN_CACHE, {}), load(MODEL_CACHE, {})
    pc, nc = load(PHOTO_CACHE, {}), load(NCAP_CACHE, {})
    today = dt.date.today()
    cutoff = (today - dt.timedelta(days=KEEP_PAST_DAYS)).isoformat()

    sources = [(a.id, None)] if a.pdf else list_pdfs()
    print(f"{len(sources)} auction PDFs on the city page")
    for aid, url in sources:
        if date_from_id(aid) and date_from_id(aid) < cutoff:
            continue
        try:
            blob = Path(a.pdf).read_bytes() if a.pdf else http(url, binary=True)
        except Exception as e:
            print(f"  {aid}: download failed, keeping previous data ({e})")
            continue
        h = hashlib.sha256(blob).hexdigest()[:16]
        if aid in raw and raw[aid].get("hash") == h and not a.force:
            continue
        try:
            rows, meta = parse_pdf(blob)
        except Exception as e:
            print(f"  {aid}: could not read PDF ({e})")
            continue
        if not rows:
            print(f"  {aid}: no vehicle rows found, skipped")
            continue
        raw[aid] = {"id": aid, "borough": borough_of(aid), "date": meta.get("date") or date_from_id(aid),
                    "time": meta.get("time", ""), "location": meta.get("location", ""), "pdf": url or "",
                    "hash": h, "fetched": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "rows": rows}
        print(f"  {aid}: {len(rows)} lots, {sum(1 for r in rows if not vin_ok(r['vin']))} without a valid VIN, {meta}")

    raw = {k: x for k, x in raw.items() if (x.get("date") or "9999") >= cutoff}
    order = sorted(raw.values(), key=lambda x: (x["borough"] != "Bronx", x["date"] < today.isoformat(), x["date"]))
    decode_vins([r["vin"] for x in order for r in x["rows"]], vc)

    combos = []
    for x in order:
        for r in x["rows"]:
            d = vc.get(r["vin"])
            if d and d.get("Make") and d.get("Model") and d.get("ModelYear", "").isdigit():
                combos.append((d["Make"], d["Model"], d["ModelYear"], body_short(d.get("BodyClass", "")),
                               DRIVE.get(d.get("DriveType", ""), "")))
    combos = list(dict.fromkeys(combos))
    for mk, md, y, b, dr in combos:
        model_stats(mk, md, y, mc)
        ncap(mk, md, y, b, dr, nc)
    if not a.no_photos:
        photos_for(list(dict.fromkeys((int(y), make_name(mk), md, b) for mk, md, y, b, dr in combos)), pc)

    auctions = []
    for x in sorted(raw.values(), key=lambda x: (x["date"], x["borough"])):
        meta = {k: v for k, v in x.items() if k not in ("rows", "hash")}
        auctions.append({**meta, "cars": [build_car(r, vc, mc, pc, nc) for r in x["rows"]]})
    seen = {}
    for x in auctions:
        for c in x["cars"]:
            if vin_ok(c["vin"]):
                seen.setdefault(c["vin"], []).append((x["date"], x["borough"], c["n"]))
    for x in auctions:
        for c in x["cars"]:
            other = [o for o in seen.get(c["vin"], []) if (o[0], o[1]) != (x["date"], x["borough"])]
            if other:
                c["flags"].append("Also on " + ", ".join(
                    f'{dt.date.fromisoformat(d).strftime("%-m/%-d")} {b} lot {n}' for d, b, n in other))

    DATA.mkdir(exist_ok=True)
    def dump(p, obj): p.write_text(json.dumps(obj, separators=(",", ":"), sort_keys=p != OUT))
    dump(OUT, {"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"), "auctions": auctions})
    dump(RAW, raw); dump(VIN_CACHE, vc); dump(MODEL_CACHE, mc); dump(PHOTO_CACHE, pc); dump(NCAP_CACHE, nc)
    print(f"wrote {len(auctions)} auctions, {sum(len(x['cars']) for x in auctions)} lots")

if __name__ == "__main__":
    sys.exit(main())
