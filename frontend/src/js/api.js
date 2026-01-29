import {
  getAccessToken,
  getRefreshToken,
  setTokens,
  clearTokens,
} from "./auth/auth.js";

export async function apiFetch(url, options = {}) {
  const token = getAccessToken();

  if (!token) {
    throw new Error("Not authenticated");
  }

  options.headers = options.headers || {};
  options.headers.Authorization = "Bearer " + token;

  let resp = await fetch(url, options);

  if (resp.status === 401) {
    // try refresh
    const refresh = getRefreshToken();
    if (!refresh) {
      clearTokens();
      throw new Error("Session expired");
    }

    const refreshResp = await fetch("/api/token/refresh/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh }),
    });

    if (!refreshResp.ok) {
      clearTokens();
      throw new Error("Session expired");
    }

    const data = await refreshResp.json();
    setTokens(data);

    options.headers.Authorization = "Bearer " + data.access;
    resp = await fetch(url, options);
  }

  return resp;
}
