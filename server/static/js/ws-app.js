import { setWsBadge } from "./badges.js";
import { buildAppWsUrl } from "./ws-urls.js";

/** @type {WebSocket | null} */
let sock = null;

/** @param {ReturnType<import('./context.js').bootUi>} ctx */
export function connectApp(ctx) {
  const { $, log } = ctx;
  const url = buildAppWsUrl($);
  if (sock) {
    try {
      sock.close();
    } catch (e) {
      /* ignore */
    }
  }
  log("Connecting", url.replace(/token=[^&]+/, "token=***"));
  sock = new WebSocket(url);
  setWsBadge($, "conn");
  sock.onopen = () => {
    log("ws open");
    setWsBadge($, "open");
  };
  sock.onclose = () => {
    log("ws closed");
    setWsBadge($, "closed");
  };
  sock.onerror = () => log("ws error");
  sock.onmessage = (ev) => log("<<", ev.data);
}

/** @param {ReturnType<import('./context.js').bootUi>} ctx */
export function disconnectApp(ctx) {
  const { $, log } = ctx;
  if (sock) {
    try {
      sock.close();
    } catch (e) {
      /* ignore */
    }
    sock = null;
  }
  setWsBadge($, "closed");
  log("disconnect requested");
}

/** @param {ReturnType<import('./context.js').bootUi>} ctx */
export function sendPresence(ctx) {
  const { $, log } = ctx;
  const rid = /** @type {HTMLSelectElement} */ ($("roomSelect")).value;
  if (!rid) {
    log("Pick a room in the dropdown after GET /rooms");
    return;
  }
  const cref = /** @type {HTMLInputElement} */ ($("cref")).value.trim();
  const origin = /** @type {HTMLInputElement} */ ($("originTip")).value.trim();
  if (!sock || sock.readyState !== WebSocket.OPEN) {
    connectApp(ctx);
  }
  setTimeout(() => {
    if (!sock || sock.readyState !== WebSocket.OPEN) {
      log("WS not open");
      return;
    }
    /** @type {{ v: number, type: string, active_room_id: string, standby_others: boolean, content_ref?: string }} */
    const msg = {
      v: 1,
      type: "presence",
      active_room_id: rid,
      standby_others: /** @type {HTMLInputElement} */ ($("standbyWs")).checked,
    };
    if (cref) msg.content_ref = cref;
    sock.send(JSON.stringify(msg));
    log(">>", JSON.stringify(msg));
    log("Tip: set TV_STRETCH_PUBLIC_BASE_URL=" + origin + " on the server for LAN OTA URLs.");
  }, 350);
}

/** @param {ReturnType<import('./context.js').bootUi>} ctx */
export function pingApp(ctx) {
  const { log } = ctx;
  if (!sock || sock.readyState !== WebSocket.OPEN) {
    connectApp(ctx);
  }
  setTimeout(() => {
    if (!sock || sock.readyState !== WebSocket.OPEN) {
      log("WS not open");
      return;
    }
    sock.send(JSON.stringify({ v: 1, type: "ping" }));
    log(">> ping");
  }, 250);
}

/** @param {ReturnType<import('./context.js').bootUi>} ctx */
export function getSessionWs(ctx) {
  const { log } = ctx;
  if (!sock || sock.readyState !== WebSocket.OPEN) {
    connectApp(ctx);
  }
  setTimeout(() => {
    if (!sock || sock.readyState !== WebSocket.OPEN) {
      log("WS not open");
      return;
    }
    sock.send(JSON.stringify({ v: 1, type: "get_session" }));
    log(">> get_session");
  }, 250);
}
