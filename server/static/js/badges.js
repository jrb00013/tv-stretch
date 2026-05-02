/**
 * @param {(id: string) => HTMLElement | null} $
 */
export function setBadge($, id, text, ok) {
  const el = $(id);
  if (!el) return;
  el.textContent = text;
  el.classList.remove("ok", "err");
  if (ok === true) el.classList.add("ok");
  if (ok === false) el.classList.add("err");
}

/** @param {(id: string) => HTMLElement | null} $ */
export function setWsBadge($, state) {
  if (state === "open") setBadge($, "badge-ws", "app WS live", true);
  else if (state === "closed") setBadge($, "badge-ws", "app WS idle", null);
  else setBadge($, "badge-ws", "app WS …", null);
}

/** @param {(id: string) => HTMLElement | null} $ */
export function setDevBadge($, state) {
  if (state === "open") setBadge($, "badge-dev", "device WS live", true);
  else if (state === "closed") setBadge($, "badge-dev", "device WS idle", null);
  else setBadge($, "badge-dev", "device WS …", null);
}
