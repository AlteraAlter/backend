const API_URL = "http://localhost:8000"; // поменяй на свой backend URL

// ==========================
// Login — получаем токены
// ==========================
export async function login(username, password) {
    const response = await fetch(`${API_URL}/auth/login/`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ username, password }),
    });

    if (!response.ok) {
        throw new Error("Invalid credentials");
    }

    const data = await response.json();

    // сохраняем токены
    localStorage.setItem("access", data.access);
    localStorage.setItem("refresh", data.refresh);

    return data;
}

// ===================================
// Refresh токен — получаем новый access
// ===================================
export async function refreshToken() {
    const refresh = localStorage.getItem("refresh");

    if (!refresh) return null;

    const response = await fetch(`${API_URL}/auth/refresh/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh }),
    });

    if (!response.ok) {
        // refresh протух → надо логиниться
        logout();
        return null;
    }

    const data = await response.json();
    localStorage.setItem("access", data.access);
    return data.access;
}

// ===============================
// Logout
// ===============================
export function logout() {
    localStorage.removeItem("access");
    localStorage.removeItem("refresh");
}
