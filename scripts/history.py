"""Free VIN history: past auction listings of the exact VIN, from public pages that need no account, payment or CAPTCHA.
Runs inside update.py. Results are cached per VIN in data/history_cache.json and shown under "Vehicle history" on cards.

Checked automatically (robots.txt allows these pages for every agent, rechecked Oct 2026):
  AmericaMotors  americamotors.com/<make>/<model>/<VIN>   One page per VIN, HTTP 410 when unknown. Copart or IAAI lot,
                 mileage, damage, title document, yard, keys. The page shows no listing date.
  autousa.pro    vehicles.autousa.pro/search/?vin=<VIN>   Manheim run dates with odometer and condition grade. Detail
                 pages carry condition report notes in their photo captions (Front Bumper | Prev Repair).
  BidHistory     bidhistory.info/vin/<VIN>                 HTTP 404 when unknown. Its terms forbid reproducing its data,
                 so only "a record exists" and the link are kept, nothing from the page.
Photos stay on the source sites (Copart and Manheim pictures, no license to copy them). Cards link to the gallery.
Manual links only: Bid.Cars (Cloudflare bot challenge), NICB VINCheck (CAPTCHA), Google.

Rules: the exact 17 character VIN must appear on the page or nothing from it is used. An empty result or a failed
request never means a clean history. A failed source keeps what was found before. Evidence a source later drops
(AmericaMotors sells history removal) is kept and marked as gone.
"""
import datetime as dt, html as htmllib, json, re, time
import urllib.error, urllib.parse, urllib.request

UA = "NYCAuctionScout/1.0 (+https://github.com/AltecBX/NYC-Auction-Scout)"
GAP = 3.0                  # seconds between two requests to the same site
SITE_GAP = {"vehicles.autousa.pro": 6.0}   # it dropped connections from GitHub's runners at 3s, Oct 8 2026
TRIES = 2                  # per request, only for timeouts and 5xx
BREAKER = 3                # failed requests in a row before a site is skipped for the rest of the run
RECHECK = {"found": 30, "none": 10, "error": 0}     # days before a source is asked again about a VIN
AUTOUSA_DETAILS = 2        # detail pages read per VIN (newest and oldest run)

SOURCES = {"americamotors": "AmericaMotors", "autousa": "autousa.pro", "bidhistory": "BidHistory"}
VIN_RX = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
BRAND = re.compile(r"SALVAGE|\bSLVG\b|REBUILT|\bREBLD\b|\bRBLT\b|REBUILDABLE|RECONSTRUCTED|FLOOD|JUNK|NON ?REPAIRABLE|"
                   r"NONREPAIRABLE|DESTRUCTION|DISMANTL|PARTS ONLY|SCRAP|TOTAL LOSS|CERT OF DESTR|LEMON", re.I)
NO_DAMAGE = re.compile(r"^(?:-|NONE|N/?A|NORMAL WEAR(?: ?& ?TEAR)?|UNKNOWN)?$", re.I)


class Unavailable(Exception):
    pass


class Fetcher:
    """GET with a polite gap per site, bounded retries, and a breaker that stops asking a site that keeps failing."""

    def __init__(self, gap=GAP, opener=None, sleep=time.sleep, clock=time.time):
        self.gap, self.sleep, self.clock = gap, sleep, clock
        self.open = opener or self._urlopen
        self.last, self.fails, self.err = {}, {}, {}

    @staticmethod
    def _urlopen(url):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def down(self, host):
        return self.fails.get(host, 0) >= BREAKER

    def get(self, url):
        """(status, body) for 200, 404 and 410. Anything else raises Unavailable."""
        host = urllib.parse.urlparse(url).netloc
        if self.down(host):
            raise Unavailable("skipped after repeated failures this run")
        err = "no response"
        for i in range(TRIES):
            wait = self.last.get(host, 0) + max(self.gap, SITE_GAP.get(host, 0) if self.gap else 0) - self.clock()
            if wait > 0:
                self.sleep(wait)
            self.last[host] = self.clock()
            try:
                code, body = self.open(url)
            except Exception as e:                          # timeout, DNS, reset
                why = getattr(e, "reason", None) or e
                err = f"{type(e).__name__}: {why}"[:80]
            else:
                if "<title>Just a moment" in body[:3000] or "challenges.cloudflare.com" in body[:3000]:
                    err = "bot challenge"                   # never try to get past it
                    break
                if code in (200, 404, 410):
                    self.fails[host] = 0
                    return code, body
                err = f"HTTP {code}"
                if code in (401, 403, 429) or code < 500:   # blocked or rate limited: stop, do not push
                    break
            self.sleep(4 * (i + 1))
        self.fails[host] = self.fails.get(host, 0) + 1
        self.err[host] = err
        raise Unavailable(err)


# ---------- parsing helpers ----------

def text(s):
    return re.sub(r"\s+", " ", htmllib.unescape(htmllib.unescape(re.sub(r"<[^>]+>", " ", s or "")))).strip()

def miles_of(s):
    d = re.sub(r"[^\d]", "", s or "")
    return int(d) if d and len(d) <= 7 else None

def iso8(s):
    try:
        return dt.datetime.strptime(s, "%Y%m%d").date().isoformat()
    except (TypeError, ValueError):
        return None

def nice_date(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d.strftime('%b')} {d.day}, {d.year}"

def place(s):
    """MD - BALTIMORE EAST -> Baltimore East, MD"""
    s = text(s)
    m = re.match(r"^([A-Z]{2})\s*-\s*(.+)$", s)
    return f"{m.group(2).title()}, {m.group(1)}" if m else s.replace(" - ", ", ")

def classify_price(label):
    """sale only when the page says the vehicle sold for that amount. Bids, buy now, asking prices and estimates
    are never sale prices. Unlabeled amounts are dropped by the callers."""
    l = (label or "").lower()
    if re.search(r"\bsold (?:for|price)\b|\bsale price\b|\bfinal sale\b", l):
        return "sale"
    if re.search(r"estimat|value|acv|retail|mmr", l):
        return "estimate"
    if re.search(r"buy ?now|asking|list price|\bprice\b", l):
        return "ask"
    if re.search(r"bid|ставк", l):
        return "bid"
    return None


# ---------- sources ----------

AM_COND = {"Заводится и едет": "Runs and drives", "Заводится": "Starts", "Не заводится": "Does not start",
           "Стационарный": "Stationary", "Run and Drive": "Runs and drives"}

def parse_americamotors(page, vin, url):
    """[] unless the lot card names this exact VIN."""
    lot_vin = re.search(r"<li><span>VIN:</span>\s*([A-Z0-9]{17})\s*</li>", page)
    if not lot_vin or lot_vin.group(1) != vin:
        return []
    opts = {text(k).rstrip(":"): text(v) for k, v in re.findall(
        r'card1__category">([^<]+)</div>\s*<div class="card1__value"[^>]*>([^<]*)</div>', page)}
    rec = {"src": "americamotors", "url": url}
    lot = re.search(r"<span>Лот:</span>\s*#?(\d{5,10})", page)
    if lot:
        rec["lot"] = lot.group(1)
    desc = re.search(r'<meta name="description" content="([^"]*)"', page)
    auc = re.search(r"\b(Copart|IAAI|Insurance Auto Auctions)\b", desc.group(1) if desc else "")
    if auc:
        rec["auction"] = "IAAI" if auc.group(1) != "Copart" else "Copart"
    if opts.get("Пробег") and miles_of(opts["Пробег"]) is not None:
        rec["miles"] = miles_of(opts["Пробег"])
    dmg = [opts.get(k, "") for k in ("Основ. поврежд", "Втор. поврежд")]
    dmg = [d for d in dmg if not NO_DAMAGE.match(d)]
    if dmg:
        rec["damage"] = dmg
    if opts.get("Тип документа", "-") not in ("-", ""):
        rec["doc"] = opts["Тип документа"]
    if opts.get("Место стоянки", "-") != "-":
        rec["where"] = place(opts["Место стоянки"])
    if opts.get("Состояние") in AM_COND:
        rec["cond"] = AM_COND[opts["Состояние"]]
    if opts.get("Ключи") in ("Есть", "Нет"):
        rec["keys"] = "yes" if opts["Ключи"] == "Есть" else "no"
    if opts.get("Статус продажи") == "Продан":
        rec["status"] = "Listed as sold"
    bid = miles_of(opts.get("Текущая ставка", ""))
    if bid and classify_price("Текущая ставка") == "bid":
        rec["bid"] = bid                                     # a bid shown on the page, never a sale price
    if re.search(r"cs\.copart\.com|/storage/|iaai", page) and re.search(r'property="og:image" content="https?://', page):
        rec["photos"] = url
    return [rec]

def check_americamotors(f, vin, make, model):
    slug = lambda s: re.sub(r"[^a-z0-9]+", "", (s or "x").lower()) or "x"
    url = f"https://americamotors.com/{slug(make)}/{slug(model)}/{vin}"
    code, page = f.get(url)
    if code != 200:
        return "none", [], url                            # 410 is how it says it has no page for this VIN
    if "card1__category" not in page:
        raise Unavailable("page layout changed")          # never read an unknown page as "no record"
    recs = parse_americamotors(page, vin, url)
    return ("found" if recs else "none"), recs, url

def parse_autousa_search(page, vin):
    runs = []
    for block in page.split("product-default")[1:]:
        m = re.search(r'href="(/(\d{8})/\d{4}/[^/"]+/[^/"]+/([A-Z0-9]{17}))"', block)
        if not m or m.group(3) != vin:
            continue
        run = {"src": "autousa", "url": "https://vehicles.autousa.pro" + m.group(1)}
        if iso8(m.group(2)):
            run["date"] = iso8(m.group(2))
        a = re.search(r"Auction:\s*([A-Za-z][A-Za-z .]{1,30}?)\s*<", block)
        if a:
            run["auction"] = a.group(1).strip().title()
        mi = re.search(r'fa-tachometer-alt"></i>\s*<span>([\d,]+)</span>', block)
        if mi and miles_of(mi.group(1)) is not None:
            run["miles"] = miles_of(mi.group(1))
        g = re.search(r"\bCR\s*([0-5](?:\.\d)?)\b", text(block))
        if g:
            run["grade"] = g.group(1)
        runs.append(run)
    return runs

def parse_autousa_detail(page, vin):
    """Condition report notes from photo captions like 'Front Bumper | Prev Repair ∙ SubStd Panel Gaps/Misaligned'."""
    ld = re.search(r'"vehicleIdentificationNumber":\s*"([A-Z0-9]{17})"', page)
    if not ld or ld.group(1) != vin:
        return None
    notes = []
    for alt in re.findall(r'alt="([^"]*\|[^"]*)"', page):
        part, _, what = text(alt).partition("|")
        what = re.sub(r"\s*∙\s*", ", ", what.strip())
        what = re.sub(r"\bprev\b", "previous", re.sub(r"\bsubstd\b", "substandard", what.lower()))
        note = f"{part.strip()}: {what}" if part.strip() else what           # RF Fender: replaced, acceptable
        if what and note not in notes:
            notes.append(note)
    return {"notes": notes, "photos": "/image/" in page}

def check_autousa(f, vin):
    url = f"https://vehicles.autousa.pro/search/?vin={vin}"
    code, page = f.get(url)
    if code != 200 or not re.search(r"No results found|vehicles? in search result", page):
        raise Unavailable(f"HTTP {code}" if code != 200 else "page layout changed")
    runs = parse_autousa_search(page, vin)
    if not runs:
        return "none", [], url
    runs.sort(key=lambda r: r.get("date") or "")
    picks = list(dict.fromkeys([runs[-1]["url"], runs[0]["url"]]))[:AUTOUSA_DETAILS]
    for r in runs:
        if r["url"] not in picks:
            continue
        try:
            c, p = f.get(r["url"])
        except Unavailable:
            continue                       # the run itself is still evidence
        det = parse_autousa_detail(p, vin) if c == 200 else None
        if det:
            if det["notes"]:
                r["notes"] = det["notes"]
            if det["photos"]:
                r["photos"] = r["url"]
    return "found", runs, url

def check_bidhistory(f, vin):
    url = f"https://bidhistory.info/vin/{vin}"
    code, page = f.get(url)
    if code == 200 and not re.search(rf"<title>[^<]*{vin}", page):
        raise Unavailable("page layout changed")
    hit = code == 200 and f"VIN {vin}" in page
    # Its terms forbid reproducing its data: keep only the fact that a record exists and the link
    return ("found", [{"src": "bidhistory", "url": url, "linkOnly": True}], url) if hit else ("none", [], url)


# ---------- research and cache ----------

def rec_key(r):
    return (r["src"], r.get("url"), r.get("date"), r.get("lot"))

def merge(entry, src, status, recs, url, today):
    """Store one source's answer. A failure keeps the previous answer. A source that no longer shows a record
    keeps the saved record, marked gone, because sellers can pay to remove history."""
    s = entry.setdefault("src", {})
    old = [r for r in entry.get("recs", []) if r["src"] == src]
    others = [r for r in entry.get("recs", []) if r["src"] != src]
    if status == "error":
        prev = s.get(src, {})
        s[src] = {**prev, "st": prev.get("st", "error"), "at": prev.get("at", today), "url": url or prev.get("url", ""),
                  "fail": {"at": today, "err": recs}}
        if prev.get("st") in (None, "error"):
            s[src].update(st="error", at=today)
        return
    seen = {rec_key(r): r for r in old}
    new = []
    for r in recs:
        r = dict(r)
        r["seen"] = seen.pop(rec_key(r), {}).get("seen", today)
        new.append(r)
    for r in seen.values():                                # was on the source before, not now
        if not r.get("linkOnly"):
            new.append({**r, "gone": r.get("gone") or today})
    s[src] = {"st": "found" if new else status, "at": today, "url": url}
    entry["recs"] = others + new

def due(entry, src, today):
    s = entry.get("src", {}).get(src)
    if not s:
        return True
    last = s.get("fail", {}).get("at") if s["st"] == "error" else s["at"]
    days = RECHECK.get(s["st"], 0)
    return (dt.date.fromisoformat(today) - dt.date.fromisoformat(last or s["at"])).days >= days

def research(cars, cache, minutes=20, fetcher=None, today=None, log=print):
    """cars: [(vin, make, model)] best first. Checks each due source within the time budget. Never raises."""
    f = fetcher or Fetcher()
    today = today or dt.date.today().isoformat()
    stop = time.time() + 60 * minutes
    asked = found = 0
    for vin, make, model in cars:
        if time.time() > stop:
            log(f"history: time budget used, {asked} VINs checked")
            break
        if not VIN_RX.match(vin or ""):
            continue
        entry = cache.setdefault(vin, {})
        todo = [s for s in SOURCES if due(entry, s, today)]
        if not todo:
            continue
        asked += 1
        for src in todo:
            host = {"americamotors": "americamotors.com", "autousa": "vehicles.autousa.pro",
                    "bidhistory": "bidhistory.info"}[src]
            try:
                if f.down(host):
                    raise Unavailable("skipped after repeated failures this run")
                if src == "americamotors":
                    st, recs, url = check_americamotors(f, vin, make, model)
                elif src == "autousa":
                    st, recs, url = check_autousa(f, vin)
                else:
                    st, recs, url = check_bidhistory(f, vin)
                merge(entry, src, st, recs, url, today)
                found += st == "found"
            except Unavailable as e:
                merge(entry, src, "error", str(e), entry.get("src", {}).get(src, {}).get("url", ""), today)
            except Exception as e:                       # a parser bug must not stop the update
                merge(entry, src, "error", f"parse error {type(e).__name__}", "", today)
    if asked:
        down = [f"{h} ({f.err.get(h, '')})" for h in f.fails if f.down(h)]
        log(f"history: {asked} VINs checked, {found} source hits" + (f", unavailable: {', '.join(down)}" if down else ""))
    return cache


# ---------- what a card shows ----------

def mileage_flags(recs):
    """Readings with dates in order. A later lower reading is a possible discrepancy, never proof of rollback.
    Zero or missing mileage is treated as unknown."""
    flags = []
    zero = [r for r in recs if r.get("miles") == 0]
    if zero:
        flags.append({"lvl": "info", "t": f"Mileage listed as 0 on {SOURCES[zero[0]['src']]}. Treated as unknown, "
                                          "often means the odometer was not read."})
    dated = sorted([r for r in recs if r.get("miles") and r.get("date")], key=lambda r: r["date"])
    for a, b in zip(dated, dated[1:]):
        if b["miles"] < a["miles"] - 50:
            flags.append({"lvl": "bad", "t": f"Possible mileage discrepancy: {a['miles']:,} miles on {nice_date(a['date'])} "
                                             f"({SOURCES[a['src']]}), then {b['miles']:,} on {nice_date(b['date'])} "
                                             f"({SOURCES[b['src']]}). Could be a typo or a replaced cluster, not proof of tampering."})
    undated = [r for r in recs if r.get("miles") and not r.get("date")]
    readings = sorted({r["miles"] for r in recs if r.get("miles")})
    if undated and len(readings) > 1 and readings[-1] - readings[0] > 100:
        flags.append({"lvl": "warn", "t": "Mileage readings differ: " + ", ".join(
            f"{r['miles']:,} ({SOURCES[r['src']]}, {nice_date(r['date']) if r.get('date') else 'date unknown'})"
            for r in sorted(recs, key=lambda r: r.get('miles') or 0) if r.get("miles")) + ". Order unknown."})
    return flags

def flags_of(recs):
    out = []
    for r in recs:
        where = ", ".join(x for x in (r.get("auction") and f"{r['auction']} lot {r['lot']}" if r.get("lot") else r.get("auction"),
                                      SOURCES[r["src"]]) if x)
        if r.get("doc") and BRAND.search(r["doc"]):
            out.append({"lvl": "bad", "t": f"Prior listing reported title document {r['doc']} ({where})."})
        for d in r.get("damage", []):
            lvl = "bad" if re.search(r"flood|water|burn|fire|frame|biohazard|undercarriage", d, re.I) else "warn"
            out.append({"lvl": lvl, "t": f"Prior listing reported damage: {d.lower()} ({where})."})
        for n in r.get("notes", []):
            if re.search(r"repair|replac|frame|flood|water|structural", n, re.I):
                out.append({"lvl": "warn", "t": f"Condition report note: {n} ({where})."})
    out += mileage_flags(recs)
    return list({f["t"]: f for f in out}.values())

def group(recs):
    """Weekly reruns of the same car at one auction with the same reading become one event with several dates."""
    out = []
    for r in sorted(recs, key=lambda r: (r.get("date") or "9999", r["src"])):
        same = next((e for e in out if e["src"] == r["src"] == "autousa" and e.get("miles") == r.get("miles")
                     and e.get("auction") == r.get("auction") and not e.get("gone") and not r.get("gone")), None)
        if same:
            same["dates"].append(r["date"]) if r.get("date") else None
            same["url"] = r["url"]
            for k in ("notes", "grade", "photos"):
                if r.get(k) and not same.get(k):
                    same[k] = r[k]
            continue
        e = {k: v for k, v in r.items() if k != "date"}
        e["dates"] = [r["date"]] if r.get("date") else []
        out.append(e)
    return out

def card(vin, cache, valid):
    """History payload for one car in auctions.json."""
    if not valid:
        return {"st": "unchecked", "novin": True}
    entry = cache.get(vin) or {}
    srcs = entry.get("src", {})
    if not srcs:
        return {"st": "unchecked"}
    recs = entry.get("recs", [])
    sts = [s["st"] for s in srcs.values()]
    st = ("found" if recs else "unavailable" if all(x == "error" for x in sts)
          else "partial" if "error" in sts or len(srcs) < len(SOURCES) else "none")
    out = {"st": st, "src": [{"id": k, "n": SOURCES[k], "st": v["st"], "at": v["at"], "url": v.get("url", ""),
                               **({"fail": v["fail"]} if v.get("fail") else {})} for k, v in srcs.items()]}
    facts = [r for r in recs if not r.get("linkOnly")]
    if facts:
        out["flags"] = flags_of(facts)
        out["ev"] = group(facts)
    return out
