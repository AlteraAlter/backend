// auth/auth.js

const ACCESS_KEY = "jwt_access";
const REFRESH_KEY = "jwt_refresh";
const BACKEND_URL = "http://127.0.0.1:8050";
// =====================
// TOKEN STORAGE
// =====================
export function setTokens({ access, refresh }) {
  localStorage.setItem(ACCESS_KEY, access);
  if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
}

export function getAccessToken() {
  return localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken() {
  return localStorage.getItem(REFRESH_KEY);
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

// =====================
// AUTH ACTIONS
// =====================
export async function login(username, password) {
  const resp = await fetch(`${BACKEND_URL}/api/token/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });

  const data = await resp.json();

  if (!resp.ok) {
    throw new Error(data.detail || "Login failed");
  }

  

  setTokens(data);
  updateLoginUI();
}

export function logout() {
  clearTokens();
  updateLoginUI();
  alert("Вы вышли");
}

// =====================
// UI
// =====================
export function promptLogin() {
  const u = prompt("Логин:");
  if (!u) return;
  const p = prompt("Пароль:");
  if (!p) return;

  login(u, p).catch((err) => alert(err.message));
}

export function updateLoginUI() {
  const containers = document.querySelectorAll(".auth-buttons");
  const isLoggedIn = !!getAccessToken();

  const html = isLoggedIn
    ? `<button class="auth-btn" id="logout-btn">Выйти</button>`
    : `<button class="auth-btn login-btn" id="login-btn">Войти</button>`;

  containers.forEach((c) => (c.innerHTML = html));

  if (isLoggedIn) {
    document.getElementById("logout-btn")?.addEventListener("click", logout);
  } else {
    document
      .getElementById("login-btn")
      ?.addEventListener("click", promptLogin);
  }
}
