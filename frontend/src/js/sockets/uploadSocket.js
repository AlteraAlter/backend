import { setSocket, isSocketOpen } from "./socketManager.js";

export function ensureUploadSocket(onMessage) {
  if (isSocketOpen("upload")) return;

  const protocol = location.protocol === "https:" ? "wss//" : "ws://";
  const socket = new WebSocket(
    `${protocol}${location.host}/ws/upload-progress/`,
  );

  socket.onopen = () => console.log("✅ Upload socket connected");
  socket.onMessage = (e) => onMessage(JSON.parse(e.data));
  socket.onerror = (e) => console.log("Upload socket error", e);

  setSocket("upload", socket);
}
