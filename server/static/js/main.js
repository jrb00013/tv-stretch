import { bootUi } from "./context.js";
import { loadPrefs, savePrefs } from "./storage.js";
import * as Rest from "./rest.js";
import * as WsApp from "./ws-app.js";
import * as WsDev from "./ws-device.js";

const ctx = bootUi();
const { $, log, clearLog, apiBase } = ctx;

loadPrefs($);

function syncDocsLink() {
  const b = apiBase();
  /** @type {HTMLAnchorElement} */ ($("linkDocs")).href =
    (b || window.location.origin || "") + "/docs";
}

if (!/** @type {HTMLInputElement} */ ($("apiOrigin")).value && window.location.origin) {
  /** @type {HTMLInputElement} */ ($("apiOrigin")).value = window.location.origin;
}

$("btnPingApi").onclick = () => Rest.pingApi(ctx);
$("btnLoadMeta").onclick = () => Rest.loadMe(ctx);
$("btnSave").onclick = () => savePrefs($, log);
$("btnBootstrap").onclick = () => Rest.doBootstrap(ctx);
$("btnRooms").onclick = () => Rest.fetchRooms(ctx);
$("btnSession").onclick = () => Rest.fetchSession(ctx);
$("btnHandoff").onclick = () => Rest.doHandoff(ctx);
$("btnEvents").onclick = () => Rest.fetchEvents(ctx);
$("btnHealth").onclick = () => Rest.fetchHealth(ctx);
$("btnDiagOverview").onclick = () => Rest.fetchDiagnosticsOverview(ctx);
$("btnDiagLive").onclick = () => Rest.fetchDiagnosticsLive(ctx);
$("btnRegisterNode").onclick = () => Rest.registerNodeForRoom(ctx);

$("connect").onclick = () => WsApp.connectApp(ctx);
$("disconnect").onclick = () => WsApp.disconnectApp(ctx);
$("send").onclick = () => WsApp.sendPresence(ctx);
$("ping").onclick = () => WsApp.pingApp(ctx);
$("btnWsSession").onclick = () => WsApp.getSessionWs(ctx);

$("devConnect").onclick = () => WsDev.connectDevice(ctx);
$("devDisconnect").onclick = () => WsDev.disconnectDevice(ctx);
$("devHello").onclick = () => WsDev.sendDeviceHello(ctx);
$("devHb").onclick = () => WsDev.sendDeviceHeartbeat(ctx);

function downloadLogFile() {
  const text = /** @type {HTMLElement} */ ($("log")).textContent || "";
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "tv-stretch-log-" + new Date().toISOString().slice(0, 19).replace(/:/g, "") + ".txt";
  a.click();
  URL.revokeObjectURL(a.href);
  log("(exported log file)");
}

$("clearLog").onclick = () => clearLog();
$("copyLog").onclick = async () => {
  try {
    await navigator.clipboard.writeText(/** @type {HTMLElement} */ ($("log")).textContent || "");
    log("(copied log to clipboard)");
  } catch (e) {
    log("copy failed", String(e));
  }
};
$("btnDownloadLog").onclick = () => downloadLogFile();

$("apiOrigin").addEventListener("input", syncDocsLink);

document.addEventListener("keydown", (e) => {
  if (!(e.ctrlKey || e.metaKey) || !e.shiftKey) return;
  const k = e.key.toLowerCase();
  if (k === "l") {
    e.preventDefault();
    clearLog();
  }
  if (k === "s") {
    e.preventDefault();
    downloadLogFile();
  }
});

syncDocsLink();
Rest.pingApi(ctx);
