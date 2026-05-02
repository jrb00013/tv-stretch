/** @param {(id: string) => HTMLElement | null} $ */
export function buildAppWsUrl($) {
  const host = /** @type {HTMLInputElement} */ ($("wshost")).value.trim().replace(/^\/+/, "");
  const home = /** @type {HTMLInputElement} */ ($("home")).value.trim();
  const token = /** @type {HTMLInputElement} */ ($("token")).value.trim();
  const proto = host.startsWith("localhost") || host.startsWith("127.") ? "ws" : "wss";
  const u = new URL(proto + "://" + host.replace(/^https?:\/\//i, ""));
  u.pathname = "/ws/app";
  u.searchParams.set("home_id", home);
  u.searchParams.set("token", token);
  return u.toString();
}

/** @param {(id: string) => HTMLElement | null} $ */
export function buildDeviceWsUrl($) {
  const host = /** @type {HTMLInputElement} */ ($("wshost")).value.trim().replace(/^\/+/, "");
  const home = /** @type {HTMLInputElement} */ ($("home")).value.trim();
  const apiKey = /** @type {HTMLInputElement} */ ($("deviceApiKey")).value.trim();
  const proto = host.startsWith("localhost") || host.startsWith("127.") ? "ws" : "wss";
  const u = new URL(proto + "://" + host.replace(/^https?:\/\//i, ""));
  u.pathname = "/ws/device";
  u.searchParams.set("home_id", home);
  u.searchParams.set("token", apiKey);
  return u.toString();
}
