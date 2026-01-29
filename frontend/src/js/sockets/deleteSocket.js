import { isSocketOpen, setSocket } from "./socketManager.js";

export function ensureDeleteSocket(onMessage) {
  if (isSocketOpen("delete")) return;

  const protocol = location.protocol === "https:" ? "wss://" : "ws://";
  const socket = new WebSocket(`${protocol}${location.host}/ws/delete/`);

  socket.onopen = () => console.log("🗑 Delete socket connected");
  socket.onmessage = (e) => onMessage(JSON.parse(e.data));
  socket.onerror = (e) => console.error("Delete socket error", e);

  setSocket("delete", socket);
}
