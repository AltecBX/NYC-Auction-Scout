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

const ICON = {
  star: '<svg viewBox="0 0 24 24"><path d="M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.8z" stroke-linejoin="round"/></svg>',
  pin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg>',
  doc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M10 13h6M10 17h6"/></svg>',
  lock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
};

let DATA = { auctions: [] };
const st = { q: "", sort: "n", filter: "all", body: "all", boro: get("boro", "Bronx"), auc: null };
let saved = get("notes", {});
const key = n => `${st.auc}-${n}`;
const note = n => saved[key(n)] || (saved[key(n)] = {});

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

function renderHeader(list, A) {
  const boros = [...new Set(DATA.auctions.map(a => a.borough))].sort((a, b) => (a !== "Bronx") - (b !== "Bronx") || a.localeCompare(b));
  seg($("boro"), boros.map(b => ({ v: b, label: b })), st.boro, v => {
    st.boro = v; st.auc = null; st.filter = "all"; st.body = "all"; put("boro", v); render(true);
  });
  seg($("auc"), list.map(a => {
    const d = parse(a.date);
    return { v: a.id, cls: a.date < today ? "past" : "", html:
      `<span class="dw">${a.date === today ? "Today" : DOW[d.getDay()]}</span><span class="dn">${d.getDate()}</span><span class="dl">${a.cars.length} lots</span>` };
  }), st.auc, v => { st.auc = v; st.filter = "all"; st.body = "all"; render(true); }, true);
  const d = parse(A.date);
  $("saleWhen").textContent = `${A.borough}, ${DOWL[d.getDay()]} ${MON[d.getMonth()]} ${d.getDate()}${A.time ? " at " + A.time : ""}`;
  $("saleWhere").textContent = A.location || "";
  const clear = A.cars.filter(c => !c.lien).length;
  const acts = [];
  if (A.location) acts.push(`<a class="btn btn-light" target="_blank" rel="noopener" href="https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(A.location)}">${ICON.pin}Directions</a>`);
  if (A.pdf) acts.push(`<a class="btn btn-ghost" target="_blank" rel="noopener" href="${esc(A.pdf)}">${ICON.doc}City list</a>`);
  $("saleActs").innerHTML = acts.join("") +
    `<div class="tally"><span><b>${A.cars.length}</b> lots</span><span class="ok"><b>${clear}</b> no lien</span></div>`;
  // keep the chosen date in view
  const on = $("auc").querySelector('[aria-pressed="true"]');
  if (on && on.scrollIntoView) on.scrollIntoView({ block: "nearest", inline: "center" });
}

function renderChips(A) {
  const C = A.cars;
  const starred = C.filter(c => (saved[key(c.n)] || {}).s).length;
  const bodies = Object.entries(C.reduce((m, c) => (c.body && (m[c.body] = (m[c.body] || 0) + 1), m), {})).sort((a, b) => b[1] - a[1]);
  const el = $("chips");
  el.innerHTML = "";
  const add = (label, n, on, fn) => {
    const b = document.createElement("button");
    b.type = "button"; b.setAttribute("aria-pressed", String(on));
    b.innerHTML = `${esc(label)}${n != null ? `<b>${n}</b>` : ""}`;
    b.onclick = fn; el.appendChild(b);
  };
  add("No lien", C.filter(c => !c.lien).length, st.filter === "clear", () => { st.filter = st.filter === "clear" ? "all" : "clear"; render(); });
  add("Starred", starred, st.filter === "star", () => { st.filter = st.filter === "star" ? "all" : "star"; render(); });
  add("Has lien", C.filter(c => c.lien).length, st.filter === "lien", () => { st.filter = st.filter === "lien" ? "all" : "lien"; render(); });
  const s = document.createElement("span"); s.className = "sep"; el.appendChild(s);
  for (const [b, n] of bodies) add(b, n, st.body === b, () => { st.body = st.body === b ? "all" : b; render(); });
}

function starsHTML(n) {
  return `<span class="stars" aria-label="${n} of 5 stars">${"★".repeat(n)}<span class="off">${"★".repeat(5 - n)}</span></span>`;
}

function card(c) {
  const s = saved[key(c.n)] || {};
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
  const feats = (c.features || []);
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
  return `<article class="car${c.lien ? " lien" : ""}">
    <div class="shot">
      <div class="lotno"><small>Lot</small>${c.n}</div>
      <button class="star" type="button" data-n="${c.n}" aria-pressed="${!!s.s}" aria-label="Star lot ${c.n}">${ICON.star}</button>
      ${shot}
    </div>
    <div class="body">
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
        <input id="note-${esc(st.auc)}-${c.n}" data-n="${c.n}" value="${esc(s.t || "")}" placeholder="Max bid, condition, notes" enterkeyhint="done"></label>
    </div>
  </article>`;
}

function render(scrollTop) {
  const list = DATA.auctions.filter(a => a.borough === st.boro);
  if (!list.length) {
    const any = DATA.auctions[0];
    if (any) { st.boro = any.borough; return render(); }
    $("saleWhen").textContent = "No auction lists are posted right now.";
    return;
  }
  if (!st.auc || !list.some(a => a.id === st.auc)) st.auc = (list.find(a => a.date >= today) || list[list.length - 1]).id;
  const A = list.find(a => a.id === st.auc);
  renderHeader(list, A);
  renderChips(A);
  const q = st.q.toLowerCase().trim();
  const r = A.cars.filter(c => {
    if (st.filter === "clear" && c.lien) return false;
    if (st.filter === "lien" && !c.lien) return false;
    if (st.filter === "star" && !(saved[key(c.n)] || {}).s) return false;
    if (st.body !== "all" && c.body !== st.body) return false;
    if (q && ![c.n, c.year, c.make, c.model, c.trim, c.vin, c.plate, c.listMake, c.lien].join(" ").toLowerCase().includes(q)) return false;
    return true;
  });
  const big = x => x ?? 1e9;
  r.sort({
    n: (a, b) => a.n - b.n,
    y: (a, b) => (b.year || 0) - (a.year || 0) || a.n - b.n,
    s: (a, b) => (b.stars || 0) - (a.stars || 0) || big(a.complaints) - big(b.complaints) || a.n - b.n,
    c: (a, b) => big(a.complaints) - big(b.complaints) || a.n - b.n,
    r: (a, b) => big(a.recalls) - big(b.recalls) || a.n - b.n,
  }[st.sort]);
  $("count").textContent = r.length === A.cars.length ? `${r.length} lots` : `${r.length} of ${A.cars.length} lots`;
  $("list").innerHTML = r.length ? r.map(card).join("") : `<div class="empty">No lots match these filters.</div>`;
  if (scrollTop && window.scrollY > $("tools").offsetTop) window.scrollTo({ top: $("tools").offsetTop });
}

$("q").addEventListener("input", e => { st.q = e.target.value; render(); });
$("sort").addEventListener("change", e => { st.sort = e.target.value; render(); });
$("list").addEventListener("click", e => {
  const b = e.target.closest(".star"); if (!b) return;
  const o = note(b.dataset.n); o.s = !o.s; put("notes", saved);
  b.setAttribute("aria-pressed", String(o.s)); renderChips(DATA.auctions.find(a => a.id === st.auc));
  if (st.filter === "star") render();
});
$("list").addEventListener("change", e => {
  if (!e.target.matches(".note input")) return;
  note(e.target.dataset.n).t = e.target.value; put("notes", saved);
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
    render();
  })
  .catch(() => { $("saleWhen").textContent = "Couldn't load the auction lists. Pull down to try again."; });
