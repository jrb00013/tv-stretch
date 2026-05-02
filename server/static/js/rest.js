import { setBadge } from "./badges.js";
import { savePrefs } from "./storage.js";

/**
 * @param {ReturnType<import('./context.js').bootUi>} ctx
 */
export async function pingApi(ctx) {
  const { $, log, apiBase } = ctx;
  const base = apiBase();
  if (!base) {
    setBadge($, "badge-api", "API —", null);
    log("Set API base URL first");
    return;
  }
  try {
    const r = await fetch(base + "/health/ready");
    const j = await r.json().catch(() => ({}));
    if (r.ok) {
      setBadge($, "badge-api", "API v" + (j.version || "?"), true);
      const chip = $("apiVersion");
      if (chip) {
        chip.textContent = j.version ? "v" + j.version : "";
        chip.hidden = !j.version;
      }
      const foot = $("footerApiHint");
      if (foot && j.version) foot.textContent = "v" + j.version + " · SQLite coordinator";
      log("GET /health/ready →", j.status || j);
    } else {
      setBadge($, "badge-api", "API error " + r.status, false);
      const chip = $("apiVersion");
      if (chip) chip.hidden = true;
      log("GET /health/ready failed", r.status);
    }
  } catch (e) {
    setBadge($, "badge-api", "API unreachable", false);
    const chip = $("apiVersion");
    if (chip) chip.hidden = true;
    log("Ping failed:", String(e));
  }
}

/** @param {ReturnType<import('./context.js').bootUi>} ctx */
export async function loadMe(ctx) {
  const { $, log, apiBase, authHeaders } = ctx;
  const base = apiBase();
  const tok = /** @type {HTMLInputElement} */ ($("token")).value.trim();
  if (!base || !tok) {
    log("Need API URL + control token for /homes/me");
    return;
  }
  try {
    const r = await fetch(base + "/homes/me", { headers: authHeaders(false) });
    const j = await r.json().catch(() => ({}));
    if (r.ok) {
      /** @type {HTMLInputElement} */ ($("home")).value = j.id || /** @type {HTMLInputElement} */ ($("home")).value;
      /** @type {HTMLElement} */ ($("sessionLabel")).textContent =
        j.name + " · " + (j.room_count ?? "?") + " rooms · " + (j.node_count ?? "?") + " nodes";
      /** @type {HTMLElement} */ ($("dotSession")).classList.add("on");
      /** @type {HTMLElement} */ ($("dotSession")).classList.remove("off");
      log("GET /homes/me →", JSON.stringify(j));
    } else {
      log("GET /homes/me failed", r.status, JSON.stringify(j));
    }
  } catch (e) {
    log("/homes/me error:", String(e));
  }
}

/** @param {ReturnType<import('./context.js').bootUi>} ctx */
export async function fetchRooms(ctx) {
  const { $, log, apiBase, authHeaders } = ctx;
  const base = apiBase();
  if (!base) return log("Set API base URL");
  const sel = /** @type {HTMLSelectElement} */ ($("roomSelect"));
  sel.innerHTML = "";
  try {
    const r = await fetch(base + "/rooms", { headers: authHeaders(false) });
    const rows = await r.json().catch(() => []);
    if (!r.ok) {
      log("GET /rooms failed", r.status, JSON.stringify(rows));
      return;
    }
    if (!Array.isArray(rows) || rows.length === 0) {
      sel.appendChild(new Option("— no rooms —", ""));
      log("GET /rooms → []");
      return;
    }
    for (const row of rows) {
      sel.appendChild(new Option(row.name + " · " + row.id.slice(0, 8) + "…", row.id));
    }
    log("GET /rooms →", rows.length, "room(s)");
  } catch (e) {
    log("GET /rooms error:", String(e));
  }
}

/** @param {ReturnType<import('./context.js').bootUi>} ctx */
export async function fetchSession(ctx) {
  const { $, log, apiBase, authHeaders } = ctx;
  const base = apiBase();
  if (!base) return;
  const prev = /** @type {HTMLElement} */ ($("sessionPreview"));
  try {
    const r = await fetch(base + "/sessions", { headers: authHeaders(false) });
    const j = await r.json().catch(() => null);
    if (!r.ok) {
      log("GET /sessions failed", r.status);
      prev.hidden = true;
      return;
    }
    prev.textContent = JSON.stringify(j, null, 2);
    prev.hidden = false;
    if (j && j.active_room_id) {
      /** @type {HTMLSelectElement} */ ($("roomSelect")).value = j.active_room_id;
      /** @type {HTMLElement} */ ($("sessionLabel")).textContent = "Active room set in DB";
      /** @type {HTMLElement} */ ($("dotSession")).classList.add("on");
    }
    log("GET /sessions →", j ? "ok" : "null");
  } catch (e) {
    log("GET /sessions error:", String(e));
  }
}

/** @param {ReturnType<import('./context.js').bootUi>} ctx */
export async function doHandoff(ctx) {
  const { $, log, apiBase, authHeaders } = ctx;
  const base = apiBase();
  const room = /** @type {HTMLSelectElement} */ ($("roomSelect")).value;
  if (!base || !room) {
    log("Select a room after loading /rooms");
    return;
  }
  const cref = /** @type {HTMLInputElement} */ ($("cref")).value.trim();
  const body = {
    active_room_id: room,
    standby_others: /** @type {HTMLInputElement} */ ($("standbyRest")).checked,
  };
  if (cref) body.content_ref = cref;
  try {
    const r = await fetch(base + "/sessions/handoff", {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify(body),
    });
    const j = await r.json().catch(() => ({}));
    if (r.ok) {
      /** @type {HTMLElement} */ ($("sessionPreview")).textContent = JSON.stringify(j, null, 2);
      /** @type {HTMLElement} */ ($("sessionPreview")).hidden = false;
      log("POST /sessions/handoff → batch", j.batch_id, "cmds:", (j.commands || []).length);
    } else {
      log("handoff failed", r.status, JSON.stringify(j));
    }
  } catch (e) {
    log("handoff error:", String(e));
  }
}

/** @param {ReturnType<import('./context.js').bootUi>} ctx */
export async function fetchEvents(ctx) {
  const { $, log, apiBase, authHeaders } = ctx;
  const base = apiBase();
  if (!base) return;
  try {
    const r = await fetch(base + "/sessions/events?limit=20", { headers: authHeaders(false) });
    const j = await r.json().catch(() => []);
    log("GET /sessions/events →", Array.isArray(j) ? j.length + " events" : j);
    if (Array.isArray(j) && j.length) {
      /** @type {HTMLElement} */ ($("sessionPreview")).textContent = JSON.stringify(j, null, 2);
      /** @type {HTMLElement} */ ($("sessionPreview")).hidden = false;
    }
  } catch (e) {
    log("events error:", String(e));
  }
}

/** @param {ReturnType<import('./context.js').bootUi>} ctx */
export async function fetchHealth(ctx) {
  const { $, log, apiBase, authHeaders } = ctx;
  const base = apiBase();
  if (!base) return;
  const box = /** @type {HTMLElement} */ ($("healthPreview"));
  try {
    const r = await fetch(base + "/sessions/health", { headers: authHeaders(false) });
    const j = await r.json().catch(() => ({}));
    if (r.ok) {
      box.textContent = JSON.stringify(j, null, 2);
      box.hidden = false;
      log("GET /sessions/health → nodes:", (j.nodes || []).length);
    } else {
      log("health failed", r.status);
    }
  } catch (e) {
    log("health error:", String(e));
  }
}

/** @param {ReturnType<import('./context.js').bootUi>} ctx */
export async function doBootstrap(ctx) {
  const { $, log, apiBase, authHeaders } = ctx;
  const base = apiBase();
  if (!base) {
    log("Set API base URL first");
    return;
  }
  const names = /** @type {HTMLInputElement} */ ($("bootRooms")).value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const body = {
    home_name: /** @type {HTMLInputElement} */ ($("bootHomeName")).value.trim() || "Home",
    room_names: names.length ? names : ["Room A"],
  };
  try {
    const r = await fetch(base + "/bootstrap/home-with-rooms", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      log("bootstrap failed", r.status, JSON.stringify(j));
      return;
    }
    /** @type {HTMLInputElement} */ ($("home")).value = j.home.id;
    /** @type {HTMLInputElement} */ ($("token")).value = j.home.control_token;
    /** @type {HTMLInputElement} */ ($("remember")).checked = true;
    savePrefs($, log);
    await fetchRooms(ctx);
    /** @type {HTMLElement} */ ($("sessionLabel")).textContent = j.home.name + " · bootstrapped";
    /** @type {HTMLElement} */ ($("dotSession")).classList.add("on");
    log(
      "Bootstrap ok — home",
      j.home.name,
      "rooms:",
      (j.rooms || []).map((/** @type {{ name: string }} */ x) => x.name).join(", ")
    );
  } catch (e) {
    log("bootstrap error:", String(e));
  }
}

/** @param {ReturnType<import('./context.js').bootUi>} ctx */
export async function registerNodeForRoom(ctx) {
  const { $, log, apiBase, authHeaders } = ctx;
  const base = apiBase();
  const room = /** @type {HTMLSelectElement} */ ($("roomSelect")).value;
  if (!base || !room) {
    log("Select a room (GET /rooms) first");
    return;
  }
  try {
    const r = await fetch(base + "/nodes/register", {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({ room_id: room, name: "ui-" + Date.now().toString(36) }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      log("POST /nodes/register failed", r.status, JSON.stringify(j));
      return;
    }
    /** @type {HTMLInputElement} */ ($("deviceApiKey")).value = j.api_key || "";
    savePrefs($, log);
    log("Registered node", j.node_id, "— api_key filled (stored if you Save)");
  } catch (e) {
    log("register node error:", String(e));
  }
}

/** @param {ReturnType<import('./context.js').bootUi>} ctx */
export async function fetchDiagnosticsOverview(ctx) {
  const { $, log, apiBase } = ctx;
  const base = apiBase();
  if (!base) return log("Set API base URL");
  const box = /** @type {HTMLElement} */ ($("diagPreview"));
  try {
    const r = await fetch(base + "/diagnostics/overview");
    const j = await r.json().catch(() => ({}));
    if (r.ok) {
      box.textContent = JSON.stringify(j, null, 2);
      box.hidden = false;
      log("GET /diagnostics/overview → ok");
    } else {
      log("diagnostics overview failed", r.status);
    }
  } catch (e) {
    log("diagnostics overview error:", String(e));
  }
}

/** @param {ReturnType<import('./context.js').bootUi>} ctx */
export async function fetchDiagnosticsLive(ctx) {
  const { $, log, apiBase } = ctx;
  const base = apiBase();
  const hid = /** @type {HTMLInputElement} */ ($("home")).value.trim();
  if (!base || !hid) {
    log("Set API URL and home UUID first");
    return;
  }
  const box = /** @type {HTMLElement} */ ($("diagPreview"));
  try {
    const r = await fetch(base + "/diagnostics/homes/" + encodeURIComponent(hid) + "/live");
    const j = await r.json().catch(() => ({}));
    if (r.ok) {
      box.textContent = JSON.stringify(j, null, 2);
      box.hidden = false;
      log("GET /diagnostics/homes/…/live → ok");
    } else {
      log("diagnostics live failed", r.status, JSON.stringify(j));
    }
  } catch (e) {
    log("diagnostics live error:", String(e));
  }
}

