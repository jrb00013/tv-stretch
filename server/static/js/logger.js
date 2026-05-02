/**
 * @param {HTMLElement | null} logEl
 */
export function createLogger(logEl) {
  function ts() {
    return new Date().toISOString().slice(11, 23);
  }
  function log(...a) {
    if (!logEl) return;
    logEl.textContent += "[" + ts() + "] " + a.join(" ") + "\n";
    logEl.scrollTop = logEl.scrollHeight;
  }
  function clear() {
    if (logEl) logEl.textContent = "";
  }
  return { log, clear };
}
