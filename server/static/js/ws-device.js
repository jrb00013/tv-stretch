import { setDevBadge } from "./badges.js";
import { buildDeviceWsUrl } from "./ws-urls.js";

/** @type {WebSocket | null} */
let devSock = null;

/** @param {ReturnType<import('./context.js').bootUi>} ctx */
export function connectDevice(ctx) {
  const { $, log } = ctx;
  const url = buildDeviceWsUrl($);
  if (devSock) {
    try {
      devSock.close();
    } catch (e) {
      /* ignore */
    }
  }
  log("[device] connecting", url.replace(/token=[^&]+/, "token=***"));
  devSock = new WebSocket(url);
  setDevBadge($, "conn");
  devSock.onopen = () => {
    log("[device] ws open");
    setDevBadge($, "open");
  };
  devSock.onclose = () => {
    log("[device] ws closed");
    setDevBadge($, "closed");
  };
  devSock.onerror = () => log("[device] ws error");
  devSock.onmessage = (ev) => {
    log("[device]<<", ev.data);
    if (!(/** @type {HTMLInputElement} */ ($("devAutoAck")).checked)) return;
    try {
      const j = JSON.parse(ev.data);
      if (j.type === "command_batch" && j.batch_id && devSock) {
        devSock.send(JSON.stringify({ v: 1, type: "ack", batch_id: j.batch_id, ok: true }));
        log("[device]>> ack", j.batch_id);
      }
    } catch (_) {
      /* ignore */
    }
  };
}

/** @param {ReturnType<import('./context.js').bootUi>} ctx */
export function disconnectDevice(ctx) {
  const { $, log } = ctx;
  if (devSock) {
    try {
      devSock.close();
    } catch (e) {
      /* ignore */
    }
    devSock = null;
  }
  setDevBadge($, "closed");
  log("[device] disconnect");
}

/** @param {ReturnType<import('./context.js').bootUi>} ctx */
export function sendDeviceHello(ctx) {
  const { $, log } = ctx;
  const home = /** @type {HTMLInputElement} */ ($("home")).value.trim();
  const room = /** @type {HTMLSelectElement} */ ($("roomSelect")).value;
  if (!devSock || devSock.readyState !== WebSocket.OPEN) {
    connectDevice(ctx);
  }
  setTimeout(() => {
    if (!devSock || devSock.readyState !== WebSocket.OPEN) {
      log("[device] WS not open");
      return;
    }
    const payload = {
      v: 1,
      type: "hello",
      node: { room_id: room || "", home_id: home, fw: "ui-simulator" },
    };
    devSock.send(JSON.stringify(payload));
    log("[device]>> hello");
  }, 300);
}

/** @param {ReturnType<import('./context.js').bootUi>} ctx */
export function sendDeviceHeartbeat(ctx) {
  const { log } = ctx;
  if (!devSock || devSock.readyState !== WebSocket.OPEN) {
    connectDevice(ctx);
  }
  setTimeout(() => {
    if (!devSock || devSock.readyState !== WebSocket.OPEN) {
      log("[device] WS not open");
      return;
    }
    devSock.send(JSON.stringify({ v: 1, type: "heartbeat" }));
    log("[device]>> heartbeat");
  }, 250);
}
