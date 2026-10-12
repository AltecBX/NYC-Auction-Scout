// Jerry's NYC Auction Scout. Reads data/auctions.json written by scripts/update.py.
const $ = id => document.getElementById(id);
const pad = n => String(n).padStart(2, "0");
const now = new Date();
const today = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const DOWL = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const parse = iso => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); };
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const get = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } };
const put = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} };
const plural = (n, w, p) => `${n} ${n === 1 ? w : (p || w + "s")}`;
const shortDate = a => { const d = parse(a.date); return `${a.date === today ? "Today" : DOW[d.getDay()]} ${MON[d.getMonth()]} ${d.getDate()}`; };

const ICON = {
  star: '<svg viewBox="0 0 24 24"><path d="M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.8z" stroke-linejoin="round"/></svg>',
  pin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg>',
  doc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M10 13h6M10 17h6"/></svg>',
  lock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  cal: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/></svg>',
};

let DATA = { auctions: [] };
const st = { view: "sale", q: "", sort: "n", filter: "all", body: "all", where: "all", boro: get("boro", "Bronx"), auc: null };
let saved = get("notes", {});
const keyOf = (aid, n) => `${aid}-${n}`;
const noteOf = (aid, n) => saved[keyOf(aid, n)] || (saved[keyOf(aid, n)] = {});
const isFav = (a, c) => !!(saved[keyOf(a.id, c.n)] || {}).s;

function seg(el, items, cur, pick, html) {
  el.innerHTML = "";
  for (const it of items) {
    const b = document.createElement("button");
    b.type = "button";
    b.setAttribute("aria-pressed", String(it.v === cur));
    if (it.cls) b.className = it.cls;
    b.innerHTML = html ? it.html : esc(it.label);
    b.onclick = () => pick(it.v);
    el.appendChild(b);
  }
}

function saleList() { return DATA.auctions.filter(a => a.borough === st.boro); }
function currentSale() { return DATA.auctions.find(a => a.id === st.auc); }
function favCount() { let n = 0; for (const a of DATA.auctions) for (const c of a.cars) if (isFav(a, c)) n++; return n; }

function renderHeader() {
  const boros = [...new Set(DATA.auctions.map(a => a.borough))].sort((a, b) => (a !== "Bronx") - (b !== "Bronx") || a.localeCompare(b));
  seg($("boro"), boros.map(b => ({ v: b, label: b })), st.boro, v => {
    st.boro = v; st.auc = null; st.view = "sale"; resetFilters(); put("boro", v); render(true);
  });
  const list = saleList();
  if (!st.auc || !list.some(a => a.id === st.auc)) st.auc = (list.find(a => a.date >= today) || list[list.length - 1]).id;
  const A = currentSale();
  seg($("auc"), list.map(a => {
    const d = parse(a.date);
    return { v: a.id, cls: a.date < today ? "past" : "", html:
      `<span class="dw">${a.date === today ? "Today" : DOW[d.getDay()]}</span><span class="dn">${d.getDate()}</span><span class="dl">${a.cars.length} lots</span>` };
  }), st.view === "sale" ? st.auc : null, v => { st.auc = v; st.view = "sale"; resetFilters(); render(true); }, true);
  const d = parse(A.date);
  $("saleWhen").textContent = `${A.borough}, ${DOWL[d.getDay()]} ${MON[d.getMonth()]} ${d.getDate()}${A.time ? " at " + A.time : ""}`;
  $("saleWhere").textContent = A.location || "";
  const clear = A.cars.filter(c => !c.lien).length;
  const acts = [];
  if (A.location) acts.push(`<a class="btn btn-light" target="_blank" rel="noopener" href="https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(A.location)}">${ICON.pin}Directions</a>`);
  if (A.pdf) acts.push(`<a class="btn btn-ghost" target="_blank" rel="noopener" href="${esc(A.pdf)}">${ICON.doc}City list</a>`);
  $("saleActs").innerHTML = acts.join("") +
    `<div class="tally"><span><b>${A.cars.length}</b> lots</span><span class="ok"><b>${clear}</b> no lien</span></div>`;
  const rail = $("auc"), on = rail.querySelector('[aria-pressed="true"]');
  if (on && (on.offsetLeft + on.offsetWidth > rail.scrollLeft + rail.clientWidth || on.offsetLeft < rail.scrollLeft))
    rail.scrollLeft = on.offsetLeft - 16;
}

function resetFilters() { st.filter = "all"; st.body = "all"; st.where = "all"; }

function renderViews() {
  const upcoming = DATA.auctions.filter(a => a.date >= today);
  const total = upcoming.reduce((n, a) => n + a.cars.length, 0);
  seg($("views"), [
    { v: "sale", html: `This sale` },
    { v: "all", html: `All sales <b>${total}</b>` },
    { v: "fav", html: `${ICON.star}Favorites <b>${favCount()}</b>` },
  ], st.view, v => { st.view = v; resetFilters(); render(true); }, true);
  $("sort").querySelector('option[value="n"]').textContent = st.view === "sale" ? "Lot order" : "Sale date";
}

// all lots the current view covers, as {a, c}
function pool() {
  if (st.view === "sale") { const A = currentSale(); return A.cars.map(c => ({ a: A, c })); }
  const out = [];
  for (const a of DATA.auctions) {
    if (st.view === "all" && a.date < today) continue;
    for (const c of a.cars) if (st.view === "all" || isFav(a, c)) out.push({ a, c });
  }
  return out;
}

function renderChips(P) {
  const el = $("chips");
  el.innerHTML = "";
  const add = (label, n, on, fn) => {
    const b = document.createElement("button");
    b.type = "button"; b.setAttribute("aria-pressed", String(on));
    b.innerHTML = `${esc(label)}${n != null ? `<b>${n}</b>` : ""}`;
    b.onclick = fn; el.appendChild(b);
  };
  const sep = () => { const s = document.createElement("span"); s.className = "sep"; el.appendChild(s); };
  add("No lien", P.filter(x => !x.c.lien).length, st.filter === "clear", () => { st.filter = st.filter === "clear" ? "all" : "clear"; render(); });
  if (st.view === "sale") add("Starred", P.filter(x => isFav(x.a, x.c)).length, st.filter === "star", () => { st.filter = st.filter === "star" ? "all" : "star"; render(); });
  add("Has lien", P.filter(x => x.c.lien).length, st.filter === "lien", () => { st.filter = st.filter === "lien" ? "all" : "lien"; render(); });
  const nl = P.filter(x => !isLease(x.c)).length;
  if (nl < P.length) add("No lease", nl, st.filter === "nolease", () => { st.filter = st.filter === "nolease" ? "all" : "nolease"; render(); });
  const nh = P.filter(x => hasHist(x.c)).length;
  if (nh) add("History found", nh, st.filter === "hist", () => { st.filter = st.filter === "hist" ? "all" : "hist"; render(); });
  if (st.view !== "sale") {
    const boros = Object.entries(P.reduce((m, x) => (m[x.a.borough] = (m[x.a.borough] || 0) + 1, m), {}));
    if (boros.length > 1) {
      sep();
      for (const [b, n] of boros.sort((p, q) => (p[0] !== "Bronx") - (q[0] !== "Bronx") || q[1] - p[1]))
        add(b, n, st.where === b, () => { st.where = st.where === b ? "all" : b; render(); });
    }
  }
  const bodies = Object.entries(P.reduce((m, x) => (x.c.body && (m[x.c.body] = (m[x.c.body] || 0) + 1), m), {})).sort((p, q) => q[1] - p[1]);
  if (bodies.length) sep();
  for (const [b, n] of bodies) add(b, n, st.body === b, () => { st.body = st.body === b ? "all" : b; render(); });
}

function starsHTML(n) {
  return `<span class="stars" aria-label="${n} of 5 stars">${"★".repeat(n)}<span class="off">${"★".repeat(5 - n)}</span></span>`;
}

// Vehicle history: past listings of this exact VIN found by scripts/history.py during the update run
const fmtD = iso => { const d = parse(iso); return `${MON[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`; };
const HIST = {
  found: "History found", none: "No records found", partial: "No records found, some sources down",
  unavailable: "Sources unavailable", unchecked: "Not checked",
};
const hasHist = c => (c.history || {}).st === "found";

function histChip(h) {
  const bad = (h.flags || []).filter(f => f.lvl === "bad").length, n = (h.flags || []).length;
  const cls = h.st !== "found" ? "" : bad ? " bad" : " warn";
  return `<span class="hchip${cls}">${HIST[h.st] || "Not checked"}${h.st === "found" && n ? `, ${plural(n, "alert")}` : ""}</span>`;
}

function evHTML(e) {
  const d = e.dates || [];
  const when = !d.length ? "Listing date unknown"
    : d.length > 3 ? `Listed ${d.length} times, ${fmtD(d[0])} to ${fmtD(d[d.length - 1])}` : `Listed ${d.map(fmtD).join(", ")}`;
  const at = [e.auction && `${e.auction}${e.lot ? " lot " + e.lot : ""}`, e.where].filter(Boolean).join(", ");
  const facts = [
    e.miles === 0 ? "Mileage listed as 0 (treated as unknown)" : e.miles ? `${e.miles.toLocaleString("en-US")} miles` : "",
    e.doc ? `Title document: ${e.doc}` : "", ...(e.damage || []).map(x => `Damage: ${x}`), ...(e.notes || []),
    e.cond ? `${e.cond} (as listed)` : "", e.keys ? `Keys: ${e.keys}` : "", e.grade ? `Condition grade ${e.grade}` : "",
    e.status || "", e.bid ? `Bid shown $${e.bid.toLocaleString("en-US")}, not a confirmed sale price` : "",
  ].filter(Boolean);
  const name = { americamotors: "AmericaMotors", autousa: "autousa.pro" }[e.src] || e.src;
  return `<div class="hev">
    <div class="when">${esc(when)}</div>${at ? `<div class="at">${esc(at)}</div>` : ""}
    ${facts.length ? `<ul>${facts.map(f => `<li>${esc(f)}</li>`).join("")}</ul>` : ""}
    <div class="hbtns"><a href="${esc(e.url)}" target="_blank" rel="noopener">Listing on ${esc(name)}</a>${e.photos ? `<a href="${esc(e.photos)}" target="_blank" rel="noopener">Photos</a>` : ""}</div>
    <div class="seen">From ${esc(name)}, first seen by this site ${fmtD(e.seen)}.${e.gone ? ` No longer on the source as of ${fmtD(e.gone)}, saved copy shown.` : ""}${e.photos ? " Photos stay on the source site." : ""}</div>
  </div>`;
}

function histHTML(c) {
  const h = c.history || { st: "unchecked" };
  const flags = (h.flags || []).map(f => `<li class="${esc(f.lvl)}">${esc(f.t)}</li>`).join("");
  const srcTxt = s => s.st === "found" ? "Record found" : s.st === "none" ? "No match"
    : `Unavailable${s.fail ? ` (${s.fail.err})` : ""}`;
  const srcs = (h.src || []).map(s => `<li><b>${esc(s.n)}</b>: ${esc(srcTxt(s))}. Checked ${fmtD(s.at)}.${s.fail && s.st !== "error" ? ` Last try ${fmtD(s.fail.at)} failed (${esc(s.fail.err)}).` : ""}</li>`).join("");
  // BidHistory's terms do not allow copying its data, so only its link is shown
  const linkOnly = (h.src || []).filter(s => s.id === "bidhistory" && s.st === "found" && s.url).map(s => `<div class="hev">
    <div class="when">Record on ${esc(s.n)}</div><div class="seen">Its terms do not allow copying the details here. Open it to see dates, mileage, damage and any sale price.</div>
    <div class="hbtns"><a href="${esc(s.url)}" target="_blank" rel="noopener">Open ${esc(s.n)} record</a></div></div>`).join("");
  const msg = {
    found: "Past listings from other sites, matched on the full VIN. They show the car as it was then, not today.",
    none: "No matching records in the sources checked. That is not a clean history: most cars never pass through these sites, and sellers can pay some sites to remove listings.",
    partial: "No matching records in the sources that answered. Not a clean history, and some sources could not be checked.",
    unavailable: "The history sources could not be reached on the last try. Nothing is known yet.",
    unchecked: h.novin ? "No valid VIN on the city list, so no exact VIN search is possible." : "Not checked yet. Upcoming sales are checked soonest first.",
  }[h.st] || "Not checked yet.";
  const manual = c.vin && c.vin.length === 17 && !h.novin ? `<div class="hman"><div class="k">Search yourself, free</div><div class="links">
      <a href="https://www.google.com/search?q=site%3Abid.cars+${esc(c.vin)}" target="_blank" rel="noopener">Bid.Cars via Google</a>
      <a href="https://vehicles.autousa.pro/search/?vin=${esc(c.vin)}" target="_blank" rel="noopener">autousa.pro</a>
      <a href="https://www.google.com/search?q=%22${esc(c.vin)}%22" target="_blank" rel="noopener">Google</a>
      <a href="https://www.nicb.org/vincheck" target="_blank" rel="noopener">NICB</a></div></div>` : "";
  return `<details class="hist"><summary><span>Vehicle history</span>${histChip(h)}</summary><div class="hin">
    ${flags ? `<ul class="hflags">${flags}</ul>` : ""}
    <p class="hnote">${esc(msg)}</p>
    ${(h.ev || []).map(evHTML).join("")}${linkOnly}
    ${srcs ? `<ul class="hsrc">${srcs}</ul>` : ""}
    ${manual}</div></details>`;
}

// Value. Book value: the median NADA or Kelley Blue Book value lenders recorded on used cars of this make, model and
// year financed in the last 12 months (SEC loan filings, scripts/balances.py). One line on the card; tap for the range,
// estimated miles (10,000 to 20,000 a year, or from a dated reading in Vehicle history) and KBB at those miles.
const round1k = n => Math.round(n / 1000) * 1000;
const round100 = n => Math.round(n / 100) * 100;
const fmtN = n => n.toLocaleString("en-US");
const ymLabel = ym => `${MON[+ym.slice(5, 7) - 1]} ${ym.slice(0, 4)}`;
function milesEst(c) {
  const ev = ((c.history || {}).ev || []).filter(e => e.miles > 0);
  const dated = ev.filter(e => (e.dates || []).length)
    .map(e => ({ miles: e.miles, date: e.dates[e.dates.length - 1] })).sort((p, q) => (p.date < q.date ? 1 : -1))[0];
  if (dated) {
    const yrs = Math.max(0, (now - parse(dated.date)) / 3.156e10);
    return { lo: round1k(dated.miles + yrs * 10000), hi: round1k(dated.miles + yrs * 20000),
      why: `${fmtN(dated.miles)} recorded ${fmtD(dated.date)}, plus 10,000 to 20,000 a year since` };
  }
  const yr = c.year || c.listYear;
  if (!yr) return null;
  const age = Math.max(1, now.getFullYear() - yr), seen = Math.max(0, ...ev.map(e => e.miles));
  return { lo: Math.max(age * 10000, seen), hi: Math.max(age * 20000, seen),
    why: `${plural(age, "year")} at 10,000 to 20,000 a year${seen > age * 10000 ? `, and at least the ${fmtN(seen)} on a past listing` : ""}` };
}
const kbbSlug = s => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
function kbbURL(c, miles) {
  if (!c.model || !c.year) return null;
  let m = c.model.toLowerCase();
  if (c.make === "BMW" && /^\d\d\d/.test(m)) m = m[0] + " series";                        // 330i is the 3 Series
  m = m.replace(/^([a-z]{2,})-class$/, "$1").replace(/^f-(\d{3})$/, "f$1");                  // GLE-Class is gle, F-150 is f150
  if (/^(silverado|sierra)$/.test(m) && /1500/.test(c.trim || "")) m += " 1500";
  return `https://www.kbb.com/${kbbSlug(c.make)}/${kbbSlug(m)}/${c.year}/styles/?intent=trade-in-sell&mileage=${miles}`;
}
function valueHTML(c) {
  if (!c.model) return "";
  const v = c.val, m = milesEst(c), mid = m && round1k((m.lo + m.hi) / 2), url = m && kbbURL(c, mid);
  const what = `a used ${c.year} ${esc(c.make)} ${esc(c.model)}`;
  const about = v
    ? `<p><b>${usd(round100(v.p25))} to ${usd(round100(v.p75))}</b> for the middle half. NADA or Kelley Blue Book value lenders recorded on ${fmtN(v.n)} loans for ${what}, ${ymLabel(v.from)} to ${ymLabel(v.to)}, from public SEC loan filings.</p>
       <p class="why">Cars dealers sold, at their own miles and condition, any trim. Not this car: no keys, sold as is.</p>`
    : `<p class="why">Fewer than 10 loans for ${what} in public SEC loan filings from the last 12 months.</p>`;
  return `<details class="valx"><summary><span class="k">Book value</span>${v ? `<b>${usd(round100(v.p50))}</b>` : `<span class="none">No data</span>`}</summary>
    <div class="valin">${about}
      ${m ? `<div class="vr"><span class="k">Miles, estimate</span><b>${m.lo === m.hi ? `At least ${fmtN(m.lo)}` : `${fmtN(m.lo)} to ${fmtN(m.hi)}`}</b><span class="why">${esc(m.why)}</span></div>` : ""}
      ${url ? `<a class="kbb" href="${esc(url)}" target="_blank" rel="noopener">KBB value at ${fmtN(mid)} miles</a>` : ""}
    </div></details>`;
}

// Lien heads up. The payoff is private, so the card explains the risk and does the underwater math with Jerry's numbers.
// Lease names checked Oct 2026: Toyota Lease Trust, Honda Lease Trust and its trustee HVT Inc, Hyundai Lease Titling
// Trust, Nissan Infiniti LT, VW Credit Leasing, Ford Credit's CAB East, CAB West and HTD Leasing, Chrysler Capital's
// CCAP Auto Lease. Each is the owner of record of a leased car, not a lender.
const LIEN_KIND = [
  [/\bLEASE\b|\bLEASING\b|TITLING TRUST|\bHVT\b|\bCAB (?:EAST|WEST)\b|NISSAN.?INFINITI LT/i, "Lease company",
   "A leased car is owned by the leasing company, not by the person it was seized from. Treat it as likely to be taken back. Its payoff is the lease buyout: the remaining payments plus the residual value set when the lease was signed."],
  [/TITLE ?LOANS?\b|TITLEMAX/i, "Title loan", "A title loan company holds this lien. The loan is secured by this car's title."],
  [/AUTO SALES|MOTOR CARS|AUTO GROUP|AUTO MALL|CHRYSLER LLC|\bMOTORS? (?:INC|LLC)\b/i, "Dealer loan",
   "A car dealer holds this lien, so the dealer itself financed the car."],
];
const lienKind = name => LIEN_KIND.find(([rx]) => rx.test((name || "").split("/")[0]));   // the first name is the main lienholder
const isLease = c => !!c.lien && (lienKind(c.lien) || [])[1] === "Lease company";
const money = s => {
  const m = String(s || "").replace(/[$,\s]/g, "").match(/^(\d+(?:\.\d+)?)(k)?$/i);
  return m ? Math.round(parseFloat(m[1]) * (m[2] ? 1000 : 1)) : null;
};
const usd = n => "$" + n.toLocaleString("en-US");

function lienMath(o, bal) {
  const v = money(o.v), b = money(o.b), x = money(o.x) || 0;
  if (v == null || b == null) return "Enter the car's value and your bid to see the most the lien can be before you lose money.";
  const room = v - b - x;
  if (room <= 0) return `Underwater before any lien: ${usd(b + x)} in for a ${usd(v)} car.`;
  const at = (amt, label) => room - amt >= 0 ? `At ${label} of ${usd(amt)} you come out ${usd(room - amt)} ahead.`
    : `At ${label} of ${usd(amt)} you are ${usd(amt - room)} underwater.`;
  const typ = bal && bal.p50 ? ` ${at(bal.p50, "the typical balance")} ${at(bal.p75, "a high balance")}` : "";
  return `It only works if the payoff is under ${usd(room)}.${typ} If the lender repossesses instead, you lose ${usd(b + x)}.`;
}
const carOf = (aid, n) => { const a = DATA.auctions.find(x => x.id === aid); return a && a.cars.find(c => String(c.n) === String(n)); };
const monthYear = iso => { const d = parse(iso); return `${MON[d.getMonth()]} ${d.getFullYear()}`; };

// What public loans like this one still owe: SEC loan level filings, same lender, make, model and year. No VINs in
// that data, so it is never this car's payoff.
function balHTML(c, k) {
  if (k && k[1] === "Lease company") return "";
  const b = c.bal;
  if (!b) return `<p class="bal none">No public loan data for this lender, model and year. Lenders that sell loans privately, like Westlake, Credit Acceptance and Lendbuzz, file nothing.</p>`;
  const what = `${c.year} ${esc(c.make)} ${esc(c.model)}`;
  return `<div class="bal"><div class="k">What similar loans still owe, SEC filings ${b.asOf ? monthYear(b.asOf) : ""}</div>
    <p><b>${usd(b.p25)} to ${usd(b.p75)}</b> for the middle half of ${fmtN(b.n)} public ${esc(b.fam)} loans on a ${what}. Median ${usd(b.p50)}${b.pay ? `, about ${usd(b.pay)} a month` : ""}${b.left ? ` with ${b.left} months left` : ""}.</p>
    ${b.ny ? `<p>New York loans only: ${fmtN(b.ny.n)}, median ${usd(b.ny.p50)} (${usd(b.ny.p25)} to ${usd(b.ny.p75)}).</p>` : ""}
    <p class="why">Typical for this lender, model and year, not this car's payoff: the public data has no VINs. Filed as ${esc(b.name)}.</p></div>`;
}

function lienHTML(a, c) {
  if (!c.lien) return `<div class="lienbar c">${ICON.check}<span>No lienholder listed</span></div>`;
  const k = lienKind(c.lien), o = saved[keyOf(a.id, c.n)] || {};
  const fld = (f, label, ph) => `<label><span>${label}</span><input inputmode="decimal" autocomplete="off" data-f="${f}" data-a="${esc(a.id)}" data-n="${c.n}" value="${esc(o[f] || "")}" placeholder="${ph}"></label>`;
  const q = encodeURIComponent([c.year || c.listYear, c.make || c.listMake, c.model, c.trim, "value"].filter(Boolean).join(" "));
  const est = c.model && milesEst(c), kbb = est && kbbURL(c, round1k((est.lo + est.hi) / 2));
  return `<details class="lienx"><summary class="lienbar l">${ICON.lock}<span>Lien held by <b>${esc(c.lien)}</b>${k ? ` <em>${k[1]}</em>` : ""}</span></summary>
    <div class="lienin">
      ${k ? `<p class="lk">${esc(k[2])}</p>` : ""}
      <p>You buy it subject to this lien. The lienholder can repossess it from you, and the Sheriff does not tell bidders about liens.</p>
      <p>The amount owed is private. Lenders give a payoff only to the borrower or someone the borrower authorizes in writing, so it cannot be looked up before the sale.</p>
      ${balHTML(c, k)}
      <div class="calc"><div class="k">Underwater check, your numbers</div>
        <div class="row">${fld("v", "Car value", "$")}${fld("b", "Your bid", "$")}${fld("x", "Other costs", "Reg, key")}</div>
        <p class="out">${esc(lienMath(o, c.bal))}</p>
        <a class="val" href="${esc(kbb || `https://www.google.com/search?q=${q}`)}" target="_blank" rel="noopener">${kbb ? "KBB value" : "Look up value"}</a>
      </div>
    </div></details>`;
}

function card({ a, c }) {
  const s = saved[keyOf(a.id, c.n)] || {};
  const yr = c.year || c.listYear;
  const name = c.model ? `${c.year} ${esc(c.make)} ${esc(c.model)}` : `${esc(c.listYear || "")} ${esc(c.listMake || "Vehicle")}`;
  const ph = c.photo;
  const shot = ph
    ? `<img src="${esc(ph.img)}" alt="Stock photo of a ${esc(c.make)} ${esc(c.model)}" loading="lazy" decoding="async">
       <div class="cap">${!ph.y ? "Stock photo of this model, year may differ" : ph.y === c.year ? "Stock photo" : `Stock photo of a ${ph.y}, closest year found`}</div>`
    : `<div class="nophoto"><img src="assets/emblem-128.webp" alt=""><span>No stock photo yet</span></div>`;
  const specs = [c.body, c.engine, c.drive, yr ? `${now.getFullYear() - yr} yrs old` : ""].filter(Boolean);
  const safety = !c.model ? "" : `<div class="safety">
      <div><div class="v">${c.stars ? starsHTML(c.stars) : "Not rated"}</div><div class="k">NHTSA crash rating</div></div>
      <div><div class="v">${c.recalls ?? "No data"}</div><div class="k">Recalls</div></div>
      <div><div class="v">${c.complaints ?? "No data"}</div><div class="k">Complaints</div></div></div>`;
  const feats = c.features || [];
  const kv = [
    ["Trim", c.trim], ["Transmission", c.trans], ["Power", c.hp ? `${c.hp} hp` : ""], ["Seats", c.seats],
    ["Built in", c.plant], ["Plate", c.plate], ["VIN", c.vin ? `<span class="vin">${esc(c.vin)}</span>` : ""],
    ["Crash, fire", c.crashFire ? `${esc(c.crashFire)} complaints` : ""], ["Most complaints", c.topComplaints],
    ["Stars for", c.starsFor], ["NHTSA files as", c.nhtsaAs],
  ].filter(x => x[1]).map(([k, v]) => `<dt>${k}</dt><dd>${k === "VIN" ? v : esc(v)}</dd>`).join("");
  const ok = c.vin && c.vin.length === 17 && c.model;
  const links = ok ? `<div class="links">
      <a href="https://www.google.com/search?q=%22${c.vin}%22" target="_blank" rel="noopener">History</a>
      <a href="https://www.nhtsa.gov/recalls?vin=${c.vin}" target="_blank" rel="noopener">Recalls</a>
      <a href="https://www.nicb.org/vincheck" target="_blank" rel="noopener">NICB</a></div>` : "";
  const credit = ph ? `<p class="credit">Photo: <a href="${esc(ph.page)}" target="_blank" rel="noopener">${esc(ph.by || "Wikimedia Commons")}</a>${ph.lic ? `, ${esc(ph.lic)}` : ""}</p>` : "";
  const sale = st.view === "sale" ? "" :
    `<button class="salebadge${a.date < today ? " past" : ""}" type="button" data-go="${esc(a.id)}">${ICON.cal}<span><b>${esc(a.borough)}</b> ${shortDate(a)}${a.time ? ", " + esc(a.time) : ""}${a.date < today ? ", sale passed" : ""}</span></button>`;
  return `<article class="car${c.lien ? " lien" : ""}">
    <div class="shot">
      <div class="lotno"><small>Lot</small>${c.n}</div>
      <button class="star" type="button" data-a="${esc(a.id)}" data-n="${c.n}" aria-pressed="${!!s.s}" aria-label="Favorite lot ${c.n}">${ICON.star}</button>
      ${shot}
    </div>
    <div class="body">
      ${sale}
      <div class="title-row"><h2 class="title">${name}</h2>${c.trim ? `<div class="trim">${esc(c.trim)}</div>` : ""}</div>
      ${specs.length ? `<div class="specs">${specs.map(x => `<span>${esc(x)}</span>`).join("")}</div>` : ""}
      ${(c.flags || []).map(f => `<div class="flag">${esc(f)}</div>`).join("")}
      ${valueHTML(c)}
      ${lienHTML(a, c)}
      ${histHTML(c)}
      <details class="more"><summary>Safety and details</summary>
        <div class="morein">${safety}
        ${feats.length ? `<div class="feats">${feats.map(f => `<span>${esc(f)}</span>`).join("")}</div>` : ""}</div>
        <dl class="kv">${kv}</dl>${links}${credit}
      </details>
      <label class="note"><span class="sr">Notes for lot ${c.n}</span>
        <input id="note-${esc(a.id)}-${c.n}" data-a="${esc(a.id)}" data-n="${c.n}" value="${esc(s.t || "")}" placeholder="Max bid, condition, notes" enterkeyhint="done"></label>
    </div>
  </article>`;
}

function render(scrollTop) {
  if (!DATA.auctions.length) { $("saleWhen").textContent = "No auction lists are posted right now."; return; }
  if (!DATA.auctions.some(a => a.borough === st.boro)) st.boro = DATA.auctions.some(a => a.borough === "Bronx") ? "Bronx" : DATA.auctions[0].borough;
  renderHeader();
  renderViews();
  const P = pool();
  renderChips(P);
  const q = st.q.toLowerCase().trim();
  const r = P.filter(({ a, c }) => {
    if (st.filter === "clear" && c.lien) return false;
    if (st.filter === "lien" && !c.lien) return false;
    if (st.filter === "hist" && !hasHist(c)) return false;
    if (st.filter === "nolease" && isLease(c)) return false;
    if (st.filter === "star" && !isFav(a, c)) return false;
    if (st.body !== "all" && c.body !== st.body) return false;
    if (st.where !== "all" && a.borough !== st.where) return false;
    if (q && ![c.n, c.year, c.make, c.model, c.trim, c.vin, c.plate, c.listMake, c.lien, c.body].join(" ").toLowerCase().includes(q)) return false;
    return true;
  });
  const big = x => x ?? 1e9;
  const bySale = (p, q) => (p.a.date < q.a.date ? -1 : p.a.date > q.a.date ? 1 : 0) || p.a.borough.localeCompare(q.a.borough) || p.c.n - q.c.n;
  r.sort({
    n: bySale,
    y: (p, q) => (q.c.year || 0) - (p.c.year || 0) || bySale(p, q),
    s: (p, q) => (q.c.stars || 0) - (p.c.stars || 0) || big(p.c.complaints) - big(q.c.complaints) || bySale(p, q),
    c: (p, q) => big(p.c.complaints) - big(q.c.complaints) || bySale(p, q),
    r: (p, q) => big(p.c.recalls) - big(q.c.recalls) || bySale(p, q),
  }[st.sort]);
  const sales = new Set(r.map(x => x.a.id)).size;
  $("count").textContent = st.view === "sale"
    ? (r.length === P.length ? plural(r.length, "lot") : `${r.length} of ${plural(P.length, "lot")}`)
    : `${plural(r.length, "lot")} across ${plural(sales, "sale")}${st.view === "all" ? ", upcoming only" : ""}`;
  $("list").innerHTML = r.length ? r.map(card).join("")
    : `<div class="empty">${st.view === "fav" && !P.length ? "Tap the star on any car to save it here. Favorites from every borough and date show up together." : "No lots match these filters."}</div>`;
  if (scrollTop && window.scrollY > $("tools").offsetTop) window.scrollTo({ top: $("tools").offsetTop });
}

$("q").addEventListener("input", e => {
  st.q = e.target.value;
  if (st.q && st.view === "sale" && st.q.length > 2 && !currentSale().cars.some(c => [c.make, c.model, c.vin].join(" ").toLowerCase().includes(st.q.toLowerCase()))) {
    // nothing in this sale, so look across every sale
    st.view = "all";
  }
  render();
});
$("sort").addEventListener("change", e => { st.sort = e.target.value; render(); });
$("list").addEventListener("click", e => {
  const go = e.target.closest(".salebadge");
  if (go) {
    const A = DATA.auctions.find(a => a.id === go.dataset.go);
    st.boro = A.borough; st.auc = A.id; st.view = "sale"; resetFilters(); st.q = ""; $("q").value = "";
    render(true); return;
  }
  const b = e.target.closest(".star"); if (!b) return;
  const o = noteOf(b.dataset.a, b.dataset.n); o.s = !o.s; put("notes", saved);
  b.setAttribute("aria-pressed", String(o.s));
  renderViews();
  if (st.view === "fav" || st.filter === "star") render(); else renderChips(pool());
});
$("list").addEventListener("input", e => {
  const f = e.target.dataset.f;
  if (!f) return;
  const o = noteOf(e.target.dataset.a, e.target.dataset.n);
  o[f] = e.target.value; put("notes", saved);
  e.target.closest(".calc").querySelector(".out").textContent = lienMath(o, (carOf(e.target.dataset.a, e.target.dataset.n) || {}).bal);
});
$("list").addEventListener("change", e => {
  if (!e.target.matches(".note input")) return;
  noteOf(e.target.dataset.a, e.target.dataset.n).t = e.target.value; put("notes", saved);
});
$("list").addEventListener("error", e => {
  if (e.target.tagName !== "IMG" || !e.target.closest(".shot")) return;
  e.target.closest(".shot").insertAdjacentHTML("beforeend", '<div class="nophoto"><img src="assets/emblem-128.webp" alt=""><span>Photo unavailable</span></div>');
  e.target.remove();
}, true);

fetch(`data/auctions.json?t=${Date.now()}`, { cache: "no-store" })
  .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then(d => {
    DATA = d;
    DATA.auctions.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
    if (d.updated) $("upd").textContent = "Last checked " + new Date(d.updated).toLocaleString([], { month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit" }) + ".";
    if (location.hash === "#favorites") st.view = "fav";
    render();
  })
  .catch(() => { $("saleWhen").textContent = "Couldn't load the auction lists. Pull down to try again."; });
