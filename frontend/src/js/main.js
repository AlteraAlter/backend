// main.js
import { apiFetch } from "./api.js";
import { ensureUploadSocket } from "./sockets/uploadSocket.js";
import { ensureDeleteSocket } from "./sockets/deleteSocket.js";
import {
  handleDeleteProgress,
  resetDeleteProgress,
} from "./delete/deleteController.js";
import { updateLoginUI } from "./auth/auth.js";

document.addEventListener("DOMContentLoaded", () => {
  updateLoginUI();
});

// =========================
// FILE UPLOAD HANDLER
// =========================
export async function uploadHandler(
  pond,
  url,
  modeId,
  controllerId,
  messageId,
) {
  const files = pond.getFiles();
  const msg = document.getElementById(messageId);
  if (!files.length) {
    msg.textContent = "Выберите файл!";
    return;
  }

  const mode = document.getElementById(modeId).value;
  const controller = document.getElementById(controllerId).value;

  // 🔑 Ensure observers
  ensureUploadSocket(showUploadProgress);

  if (mode === "delete") {
    resetDeleteProgress();
    ensureDeleteSocket(handleDeleteProgress);
  }

  msg.textContent = "Отправляю...";

  const formData = new FormData();
  files.forEach((f) =>
    formData.append("file", f.file, f.filename.replace(/[^\w.-]/g, "_")),
  );

  formData.append("mode", mode);
  formData.append("controller", controller);

  try {
    const resp = await apiFetch(url, {
      method: "POST",
      body: formData,
    });

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.message || "Server error");
    }

    const result = mode === "checker" ? await resp.blob() : await resp.json();

    msg.textContent = "Готово!";
    pond.removeFiles();
    return result;
  } catch (err) {
    console.error(err);
    msg.textContent = err.message || "Ошибка";
  }
}

// =========================
// UPLOAD PROGRESS VIEW
// =========================
function showUploadProgress(data) {
  const container = document.getElementById("upload-progress");
  if (!container) return;

  const row = document.createElement("div");
  row.textContent = `EAN ${data.ean} → ${data.stage}`;
  container.appendChild(row);
}
