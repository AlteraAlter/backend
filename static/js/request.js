import { refreshToken, logout } from "./auth.js";

const API_URL = "http://localhost:8000"; // поменяй на свой backend URL

export async function apiRequest(endpoint, method = "GET", body = null) {
    let access = localStorage.getItem("access");

    let headers = {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${access}`
    };

    let options = {
        method,
        headers
    };

    if (body) {
        options.body = JSON.stringify(body);
    }

    let response = await fetch(`${API_URL}${endpoint}`, options);

    // ===========================
    // Если токен просрочен → 401
    // ===========================
    if (response.status === 401) {
        console.warn("Access token expired. Refreshing...");

        const newAccess = await refreshToken();
        if (!newAccess) {
            logout();
            throw new Error("Session expired. Login required.");
        }

        // повторяем запрос с новым токеном
        headers["Authorization"] = `Bearer ${newAccess}`;

        response = await fetch(`${API_URL}${endpoint}`, {
            method,
            headers,
            body: body ? JSON.stringify(body) : null
        });
    }

    if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`API error: ${errorText}`);
    }

    return await response.json();
}
