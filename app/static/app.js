const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

const initData = tg?.initData || "";
const statusEl = document.getElementById("status");
const providerEl = document.getElementById("provider");
const devicesEl = document.getElementById("devices");
const daysLeftEl = document.getElementById("daysLeft");
const accessUrlEl = document.getElementById("accessUrl");
const connectBtn = document.getElementById("connectBtn");
const refreshBtn = document.getElementById("refreshBtn");
const copyBtn = document.getElementById("copyBtn");

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Telegram-Init-Data": initData,
      ...(options.headers || {})
    }
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || data.message || `HTTP ${response.status}`);
  }
  return data;
}

function renderSubscription(sub) {
  if (!sub) {
    statusEl.textContent = "Нет активной подписки";
    devicesEl.textContent = "—";
    daysLeftEl.textContent = "—";
    accessUrlEl.value = "";
    return;
  }
  statusEl.textContent = sub.status === "active" ? "Активна" : "Истекла";
  devicesEl.textContent = `до ${sub.devices || 3}`;
  daysLeftEl.textContent = `${sub.days_left ?? 0} дн.`;
  accessUrlEl.value = sub.access_url || "";
}

async function load() {
  try {
    const data = await api("/api/bootstrap");
    providerEl.textContent = `${data.default_devices || 3} устройства`;
    renderSubscription(data.subscription);
  } catch (e) {
    statusEl.textContent = e.message;
  }
}

async function withLoading(button, text, fn) {
  const old = button.textContent;
  button.disabled = true;
  button.textContent = text;
  try {
    const sub = await fn();
    renderSubscription(sub);
  } catch (e) {
    alert(e.message);
  } finally {
    button.disabled = false;
    button.textContent = old;
  }
}

connectBtn.addEventListener("click", () => withLoading(connectBtn, "Создаю доступ…", () => api("/api/connect", { method: "POST" })));
refreshBtn.addEventListener("click", () => withLoading(refreshBtn, "Обновляю…", () => api("/api/subscription/refresh", { method: "POST" })));
copyBtn.addEventListener("click", async () => {
  const value = accessUrlEl.value.trim();
  if (!value) return alert("Сначала создайте подписку");
  await navigator.clipboard.writeText(value);
  if (tg?.showPopup) tg.showPopup({ title: "Готово", message: "Ссылка скопирована" });
  else alert("Ссылка скопирована");
});

load();
