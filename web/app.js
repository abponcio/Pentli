// Shared helpers for every Plentli screen: brand header, language, live events, alerts.

const STRINGS = {
  en: {
    tagline: "Good food. More people.", lang_label: "EN / العربية", demo: "Demo",
    footer: "Demo data · Simulated messaging", demo_rule: "Demo rule",
    nav_chat: "Donor chat", nav_live: "Live rescue", nav_impact: "Impact",
    meals: "meals", portions: "portions", serve_by: "Serve by", eta: "ETA", pickup: "Pickup",
    contains: "Contains", no_allergens: "No declared allergens", halal: "Halal", donor_declared: "Donor declared",
    alerts_on: "Turn on alerts", alerts_ready: "Alerts on",
    from_kitchen: "From HelloChef kitchen", rescue: "Rescue",
  },
  ar: {
    tagline: "Good food. More people.", lang_label: "EN / العربية", demo: "تجريبي",
    footer: "بيانات تجريبية · رسائل محاكاة", demo_rule: "قاعدة تجريبية",
    nav_chat: "محادثة المتبرع", nav_live: "الإنقاذ المباشر", nav_impact: "الأثر",
    meals: "وجبة", portions: "وجبة", serve_by: "التقديم قبل", eta: "الوصول", pickup: "الاستلام",
    contains: "يحتوي على", no_allergens: "لا توجد مسببات حساسية معلنة", halal: "حلال", donor_declared: "بحسب المتبرع",
    alerts_on: "تفعيل التنبيهات", alerts_ready: "التنبيهات مفعلة",
    from_kitchen: "من مطبخ HelloChef", rescue: "عملية الإنقاذ",
  },
};

const ALLERGENS = {
  tree_nuts: ["tree nuts", "مكسرات"], peanuts: ["peanuts", "فول سوداني"], dairy: ["dairy", "ألبان"],
  eggs: ["eggs", "بيض"], gluten: ["gluten", "غلوتين"], shellfish: ["shellfish", "مأكولات بحرية"],
  fish: ["fish", "سمك"], sesame: ["sesame", "سمسم"], soy: ["soy", "صويا"],
};

function getLang() {
  const fromUrl = new URLSearchParams(location.search).get("lang");
  if (fromUrl === "ar" || fromUrl === "en") return fromUrl;
  try { return localStorage.getItem("plentli-lang") || "en"; } catch { return "en"; }
}

let LANG = getLang();
const AR = () => LANG === "ar";

function t(key) { return (STRINGS[LANG] && STRINGS[LANG][key]) || STRINGS.en[key] || key; }
function addStrings(en, ar) { Object.assign(STRINGS.en, en); Object.assign(STRINGS.ar, ar); }

function applyLang() {
  document.documentElement.lang = LANG;
  document.documentElement.dir = AR() ? "rtl" : "ltr";
  document.querySelectorAll("[data-t]").forEach((node) => { node.textContent = t(node.dataset.t); });
  document.querySelectorAll("[data-t-placeholder]").forEach((node) => { node.placeholder = t(node.dataset.tPlaceholder); });
  document.querySelectorAll("[data-t-label]").forEach((node) => { node.setAttribute("aria-label", t(node.dataset.tLabel)); });
}

function toggleLang() {
  LANG = AR() ? "en" : "ar";
  try { localStorage.setItem("plentli-lang", LANG); } catch {}
  applyLang();
  document.dispatchEvent(new CustomEvent("langchange"));
}

function pickText(texts) {
  if (!texts) return "";
  return texts[LANG] || texts.en || Object.values(texts)[0] || "";
}

function allergenList(list) {
  return (list || []).map((a) => (ALLERGENS[a] ? ALLERGENS[a][AR() ? 1 : 0] : a)).join(AR() ? "، " : ", ");
}
function allergenText(list) {
  if (!list || !list.length) return t("no_allergens");
  return `${t("contains")} ${allergenList(list)}`;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) node.append(c.nodeType ? c : document.createTextNode(c));
  return node;
}

// Times, ids and Latin names inside Arabic text stay left-to-right.
function ltr(text) { return el("bdi", { dir: "ltr", class: "tabular" }, text ?? ""); }

// A recipient or stop name in the current language.
function localName(obj) { return (AR() && obj && obj.name_ar) || (obj && obj.name) || ""; }
function dishName(obj) { return (AR() && obj && obj.dish_ar) || (obj && obj.dish) || ""; }
function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error((await res.text()) || res.statusText);
  return res.json();
}

function postJSON(path, body) {
  return api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

// Live events. Replays everything since the page opened the stream (since=0), so a refresh rebuilds state.
function listen(viewer, onEvent) {
  const source = new EventSource(`/api/events?viewer=${encodeURIComponent(viewer)}&since=0`);
  source.onmessage = (msg) => {
    try { onEvent(JSON.parse(msg.data)); } catch (err) { console.error(err); }
  };
  return source;
}

// Alerts: system notification when allowed and the page is hidden, plus vibration and an in-page toast.
// Pass the event so replayed history (on page load) does not re-alert.
const OPENED_AT = Date.now() / 1000;
let toastTimer;
function alertUser(title, body, event) {
  if (event && event.ts < OPENED_AT - 1) return;
  const toast = document.getElementById("toast");
  if (toast) {
    toast.textContent = body ? `${title}: ${body}` : title;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; }, 5000);
  }
  if (navigator.vibrate && navigator.userActivation?.hasBeenActive) navigator.vibrate([120, 60, 120]);
  if ("Notification" in window && Notification.permission === "granted" && document.visibilityState === "hidden") {
    try { new Notification(title, { body, tag: "plentli" }); } catch {}
  }
}

function alertsButton() {
  const button = el("button", { class: "btn quiet block small", type: "button" }, icon("message-circle", 18), el("span", {}, t("alerts_on")));
  if (!("Notification" in window)) { button.hidden = true; return button; }
  const done = () => { button.querySelector("span").textContent = t("alerts_ready"); button.disabled = true; };
  if (Notification.permission === "granted") done();
  button.addEventListener("click", async () => { if ((await Notification.requestPermission()) === "granted") done(); });
  return button;
}

// Food photo, or a placeholder once we know a rescue has none (avoids re-requesting a 404 on every render).
const MISSING_PHOTOS = new Set();
function foodPhoto(rescueId, attrs, placeholder) {
  if (MISSING_PHOTOS.has(rescueId)) return placeholder();
  const img = el("img", { ...attrs, src: `/api/photo/${rescueId}` });
  img.addEventListener("error", () => { MISSING_PHOTOS.add(rescueId); img.replaceWith(placeholder()); });
  return img;
}

// Brand -----------------------------------------------------------------------
// Concept mark from the brand boards (a looped leaf in a ring). Placeholder until the designer's vector lands.
function brandMark() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 32 32"); svg.setAttribute("class", "mark"); svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = '<circle cx="16" cy="16" r="12.5" fill="none" stroke="currentColor" stroke-width="3.2"/>'
    + '<path d="M8.5 24.5 C 11 15, 16 10.5, 24.5 8.5 C 23.5 17, 18 22.5, 8.5 24.5 Z" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/>';
  return svg;
}

// Header: wordmark, optional section nav, language toggle, demo status.
function mountHeader({ nav = null, tagline = true } = {}) {
  const brand = el("a", { class: "brand", href: "/", "aria-label": "Plentli home" }, brandMark(),
    el("span", {}, el("span", { class: "word" }, "Plentli"), tagline ? el("span", { class: "tag" }, "Good food. More people.") : null));
  const links = nav ? el("nav", { class: "topnav", "aria-label": "Sections" },
    [["chat", "/kitchen", "message-circle", "nav_chat"], ["live", "/ops", "map-pin", "nav_live"], ["impact", "/ops#impact", "chart-column", "nav_impact"]]
      .map(([id, href, ic, key]) => el("a", { href, "data-nav": id, "aria-current": nav === id ? "page" : null }, icon(ic, 18), el("span", { "data-t": key }, t(key))))) : null;
  const lang = el("button", { class: "lang-toggle", type: "button", "aria-label": "Switch language" }, icon("globe", 20), el("span", { dir: "ltr" }, "EN / العربية"));
  lang.addEventListener("click", toggleLang);
  const header = el("header", { class: "topbar" }, brand, links, el("div", { class: "spacer" }), lang, el("span", { class: "demo-pill", "data-t": "demo" }, t("demo")));
  document.body.prepend(header);
  return header;
}

function mountFooter(key = "footer") {
  document.body.append(el("footer", { class: "footnote", "data-t": key }, t(key)));
}

function setNavCurrent(id) {
  document.querySelectorAll(".topnav a").forEach((a) => a.toggleAttribute("aria-current", a.dataset.nav === id));
  document.querySelectorAll(".topnav a[aria-current]").forEach((a) => a.setAttribute("aria-current", "page"));
}

document.addEventListener("DOMContentLoaded", applyLang);
