import { $ } from "./dom.js";
import { createLogger } from "./logger.js";

export function bootUi() {
  const logEl = $("log");
  const { log, clear } = createLogger(logEl);
  return {
    $,
    log,
    clearLog: clear,
    apiBase() {
      return /** @type {HTMLInputElement} */ ($("apiOrigin")).value.trim().replace(/\/+$/, "");
    },
    authHeaders(/** @type {boolean} */ json) {
      const h = {
        "X-Control-Token": /** @type {HTMLInputElement} */ ($("token")).value.trim(),
      };
      if (json) h["Content-Type"] = "application/json";
      return h;
    },
  };
}
