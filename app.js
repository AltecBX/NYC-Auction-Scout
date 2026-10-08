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

function card({ a, c }) {
  const s = saved[keyOf(a.id, c.n)] || {};
  const yr = c.year || c.listYear;
  const name = c.model ? `${c.year} ${esc(c.make)} ${esc(c.model)}` : `${esc(c.listYear || "")} ${esc(c.listMake || "Vehicle")}`;
  const ph = c.photo;
  const shot = ph
    ? `<img src="${esc(ph.img)}" alt="Stock photo of a ${ph.y} ${esc(c.make)} ${esc(c.model)}" loading="lazy" decoding="async">
       <div class="cap">${ph.y === c.year ? "Stock photo" : `Stock photo of a ${ph.y}, closest year found`}</div>`
    : `<div class="nophoto"><img src="assets/emblem-128.webp" alt=""><span>No stock photo yet</span></div>`;
  const specs = [c.body, c.engine, c.drive, yr ? `${now.getFullYear() - yr} yrs old` : ""].filter(Boolean);
  const safety = c.recalls == null ? "" : `<div class="safety">
      <div><div class="v">${c.stars ? starsHTML(c.stars) : "Not rated"}</div><div class="k">NHTSA crash rating</div></div>
      <div><div class="v">${c.recalls}</div><div class="k">Recalls</div></div>
      <div><div class="v">${c.complaints}</div><div class="k">Complaints</div></div></div>`;
  const feats = c.features || [];
  const kv = [
    ["Trim", c.trim], ["Transmission", c.trans], ["Power", c.hp ? `${c.hp} hp` : ""], ["Seats", c.seats],
    ["Built in", c.plant], ["Plate", c.plate], ["VIN", c.vin ? `<span class="vin">${esc(c.vin)}</span>` : ""],
    ["Crash, fire", c.crashFire ? `${esc(c.crashFire)} complaints` : ""], ["Most complaints", c.topComplaints],
    ["Stars for", c.starsFor],
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
      <div class="lienbar ${c.lien ? "l" : "c"}">${c.lien ? ICON.lock + `<span>Lien held by <b>${esc(c.lien)}</b></span>` : ICON.check + "<span>No lienholder listed</span>"}</div>
      ${safety}
      ${feats.length ? `<div class="feats">${feats.map(f => `<span>${esc(f)}</span>`).join("")}</div>` : ""}
      <details class="more"><summary>Details and links</summary>
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
