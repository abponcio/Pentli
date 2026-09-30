// Shared helpers for every Plenty screen: language, live events, alerts.

const STRINGS = {
  en: {
    switch: "عربي", plenty: "Plenty", online: "rescue agent, online",
    placeholder: "What\u2019s left over?", send: "Send", photo: "Add photo", mic: "Voice note",
    listening: "Listening…", thinking: "Plenty is working on it…",
    try1: "50 chicken biryani, has cashews, cooked at 6", try2: "عندنا خمسين وجبة برياني دجاج، فيها كاجو، مطبوخة الساعة ٦",
    try3: "30 trays of pasta with cheese",
    offer: "New food offer", accept: "Accept", decline: "Decline", accepted: "You accepted", declined: "You declined",
    expired: "Offer closed", portions: "Portions", dish: "Dish", allergens: "Allergens", arrives: "Arrives about",
    serve_by: "Serve before", received: "Mark received", arrived: "The food has arrived. Please check it and confirm.",
    alerts_on: "Turn on alerts", alerts_ready: "Alerts on", waiting: "No offers yet. Keep this page open; new offers pop up here.",
    pick_org: "Which organisation are you?", driver_idle: "No job yet. New pickups appear here.",
    pickup: "Pickup", picked_up: "Picked up", mark_picked: "Picked up", delivered: "Delivered", navigate: "Navigate",
    mark_delivered: "Delivered", done: "Done", job: "Pickup job", portions_short: "portions",
  },
  ar: {
    switch: "English", plenty: "بلنتي", online: "وكيل إنقاذ الطعام، متصل",
    placeholder: "ما الطعام المتبقي؟", send: "إرسال", photo: "إضافة صورة", mic: "رسالة صوتية",
    listening: "جارٍ الاستماع…", thinking: "بلنتي يعمل على ذلك…",
    try1: "50 chicken biryani, has cashews, cooked at 6", try2: "عندنا خمسين وجبة برياني دجاج، فيها كاجو، مطبوخة الساعة ٦",
    try3: "30 trays of pasta with cheese",
    offer: "عرض طعام جديد", accept: "قبول", decline: "رفض", accepted: "قبلت العرض", declined: "رفضت العرض",
    expired: "انتهى العرض", portions: "عدد الوجبات", dish: "الطبق", allergens: "مسببات الحساسية", arrives: "الوصول حوالي",
    serve_by: "التقديم قبل", received: "تأكيد الاستلام", arrived: "وصل الطعام. يُرجى فحصه وتأكيد الاستلام.",
    alerts_on: "تفعيل التنبيهات", alerts_ready: "التنبيهات مفعلة", waiting: "لا توجد عروض بعد. أبقِ هذه الصفحة مفتوحة؛ ستظهر العروض الجديدة هنا.",
    pick_org: "ما هي جهتك؟", driver_idle: "لا توجد مهمة بعد. ستظهر عمليات الاستلام الجديدة هنا.",
    pickup: "الاستلام", picked_up: "تم الاستلام", mark_picked: "تم الاستلام", delivered: "تم التوصيل", navigate: "الاتجاهات",
    mark_delivered: "تم التوصيل", done: "تم", job: "مهمة استلام", portions_short: "وجبة",
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
  try { return localStorage.getItem("plenty-lang") || "en"; } catch { return "en"; }
}

let LANG = getLang();

function t(key) { return (STRINGS[LANG] && STRINGS[LANG][key]) || STRINGS.en[key] || key; }

function applyLang() {
  document.documentElement.lang = LANG;
  document.documentElement.dir = LANG === "ar" ? "rtl" : "ltr";
  document.querySelectorAll("[data-t]").forEach((el) => { el.textContent = t(el.dataset.t); });
  document.querySelectorAll("[data-t-placeholder]").forEach((el) => { el.placeholder = t(el.dataset.tPlaceholder); });
  document.querySelectorAll("[data-t-label]").forEach((el) => { el.setAttribute("aria-label", t(el.dataset.tLabel)); });
}

function toggleLang() {
  LANG = LANG === "ar" ? "en" : "ar";
  try { localStorage.setItem("plenty-lang", LANG); } catch {}
  applyLang();
  document.dispatchEvent(new CustomEvent("langchange"));
}

function pickText(texts) {
  if (!texts) return "";
  return texts[LANG] || texts.en || Object.values(texts)[0] || "";
}

function allergenText(list) {
  if (!list || !list.length) return LANG === "ar" ? "لا يوجد" : "none listed";
  return list.map((a) => (ALLERGENS[a] ? ALLERGENS[a][LANG === "ar" ? 1 : 0] : a)).join(LANG === "ar" ? "، " : ", ");
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) node.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined) node.append(c.nodeType ? c : document.createTextNode(c));
  return node;
}

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
    try { new Notification(title, { body, tag: "plenty" }); } catch {}
  }
}

async function enableAlerts(button) {
  if (!("Notification" in window)) { button.hidden = true; return; }
  if (Notification.permission === "granted") { button.textContent = t("alerts_ready"); button.disabled = true; return; }
  const result = await Notification.requestPermission();
  if (result === "granted") { button.textContent = t("alerts_ready"); button.disabled = true; }
}

function initAlertsButton(button) {
  if (!button) return;
  if (!("Notification" in window)) { button.hidden = true; return; }
  if (Notification.permission === "granted") { button.textContent = t("alerts_ready"); button.disabled = true; }
  button.addEventListener("click", () => enableAlerts(button));
}

document.addEventListener("DOMContentLoaded", () => {
  applyLang();
  document.querySelectorAll(".lang-toggle").forEach((b) => b.addEventListener("click", toggleLang));
});
