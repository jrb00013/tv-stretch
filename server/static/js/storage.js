import { LS_PREFIX } from "./config.js";

/** @param {(id: string) => HTMLElement | null} $ */
export function loadPrefs($) {
  try {
    const raw = localStorage.getItem(LS_PREFIX + "prefs");
    if (raw) {
      const o = JSON.parse(raw);
      if (o.apiOrigin) /** @type {HTMLInputElement} */ ($("apiOrigin")).value = o.apiOrigin;
      if (o.wshost) /** @type {HTMLInputElement} */ ($("wshost")).value = o.wshost;
      if (o.home) /** @type {HTMLInputElement} */ ($("home")).value = o.home;
      if (o.originTip) /** @type {HTMLInputElement} */ ($("originTip")).value = o.originTip;
      if (typeof o.standbyRest === "boolean")
        /** @type {HTMLInputElement} */ ($("standbyRest")).checked = o.standbyRest;
      if (typeof o.standbyWs === "boolean")
        /** @type {HTMLInputElement} */ ($("standbyWs")).checked = o.standbyWs;
      if (o.deviceApiKey) /** @type {HTMLInputElement} */ ($("deviceApiKey")).value = o.deviceApiKey;
    }
    const tok = localStorage.getItem(LS_PREFIX + "token");
    if (tok) {
      /** @type {HTMLInputElement} */ ($("token")).value = tok;
      /** @type {HTMLInputElement} */ ($("remember")).checked = true;
    }
  } catch (_) {
    /* ignore */
  }
}

/**
 * @param {(id: string) => HTMLElement | null} $
 * @param {(...a: unknown[]) => void} log
 */
export function savePrefs($, log) {
  const o = {
    apiOrigin: /** @type {HTMLInputElement} */ ($("apiOrigin")).value,
    wshost: /** @type {HTMLInputElement} */ ($("wshost")).value,
    home: /** @type {HTMLInputElement} */ ($("home")).value,
    originTip: /** @type {HTMLInputElement} */ ($("originTip")).value,
    standbyRest: /** @type {HTMLInputElement} */ ($("standbyRest")).checked,
    standbyWs: /** @type {HTMLInputElement} */ ($("standbyWs")).checked,
    deviceApiKey: /** @type {HTMLInputElement} */ ($("deviceApiKey")).value,
  };
  try {
    localStorage.setItem(LS_PREFIX + "prefs", JSON.stringify(o));
    if (/** @type {HTMLInputElement} */ ($("remember")).checked) {
      localStorage.setItem(LS_PREFIX + "token", /** @type {HTMLInputElement} */ ($("token")).value);
    } else {
      localStorage.removeItem(LS_PREFIX + "token");
    }
    log("Saved preferences" + (/** @type {HTMLInputElement} */ ($("remember")).checked ? " + token" : ""));
  } catch (e) {
    log("localStorage error:", String(e));
  }
}
