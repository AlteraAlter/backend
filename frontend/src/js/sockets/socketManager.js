const socket = {};

export function getSocket(name) {
  return socket[name] || null;
}

export function setSocket(name, socket) {
  socket[name] = socket;
}

export function isSocketOpen(name) {
  return socket[name]?.readyState === WebSocket.OPEN;
}
