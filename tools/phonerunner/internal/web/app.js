// PhoneRunner page: polls the status every 2 seconds. textContent only, never innerHTML,
// so nothing the PC reports can run as code on the phone.
"use strict";
const $ = (id) => document.getElementById(id);
function el(tag, text, cls) { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; }
let lastShot = "";
async function tick() {
  try {
    const r = await fetch("/api/status", { cache: "no-store" });
    if (!r.ok) throw new Error("status " + r.status);
    const s = await r.json();
    $("mode").textContent = "· " + s.mode + " · v" + s.version;
    $("seen").textContent = "Last update from the PC: " + new Date(s.at).toLocaleTimeString();
    $("seen").className = "muted";
    const pl = $("plist"); pl.replaceChildren();
    (s.problems || []).forEach((p) => pl.appendChild(el("li", p)));
    $("problems").hidden = !(s.problems && s.problems.length);
    const ss = s.session;
    $("lock").replaceChildren(ss.locked ? el("b", "The PC is locked. Pictures are not possible until it is unlocked.", "bad") : el("span", ss.connected ? "Unlocked" : "", "ok"));
    $("win").textContent = ss.window && ss.window.title ? ss.window.title : "—";
    $("exe").textContent = ss.window && ss.window.exe ? "(" + ss.window.exe.split("\\").pop() + ")" : "";
    $("paused").textContent = ss.shot_paused || "";
    $("sessnote").textContent = ss.last_error ? "Watcher problem: " + ss.last_error : ss.note;
    if (ss.last_shot_at && ss.last_shot_at !== lastShot && !ss.last_shot_at.startsWith("0001")) {
      lastShot = ss.last_shot_at;
      $("shot").src = "/api/shot?t=" + encodeURIComponent(lastShot);
      $("shot").hidden = false;
      $("shotat").textContent = "Picture taken " + new Date(lastShot).toLocaleTimeString() + " · kept on the PC (not copied to the share yet)";
    }
    const logs = $("logs"); logs.replaceChildren();
    (s.logs || []).forEach((l) => {
      const c = el("div", undefined, "card"); c.appendChild(el("h2", l.label));
      c.appendChild(l.error ? el("div", "Cannot read: " + l.error, "warn") : el("pre", (l.lines || []).join("\n")));
      logs.appendChild(c);
    });
    const co = s.copy_off;
    $("copy").replaceChildren(el("span", co.fresh && !co.problem ? "Copying normally (" + Math.round(co.age_seconds) + " s ago, reported by " + (co.copier || "copier") + ")" : (co.problem || "Not copying"), co.fresh && !co.problem ? "ok" : "bad"));
  } catch (e) {
    $("seen").textContent = "Cannot reach the PC (" + e.message + "). It may be off, asleep, or offline.";
    $("seen").className = "bad";
  }
}
async function settings() {
  try {
    const r = await fetch("/api/settings", { cache: "no-store" });
    const rows = await r.json();
    const box = $("settings"); box.replaceChildren();
    rows.forEach((s) => {
      const d = el("details"); const sum = el("summary");
      sum.appendChild(el("span", s.name + ": ")); sum.appendChild(el("b", String(s.value))); sum.appendChild(el("span", "  ⓘ", "muted"));
      d.appendChild(sum); d.appendChild(el("div", s.info, "muted")); box.appendChild(d);
    });
  } catch (e) { /* status tick reports reachability */ }
}
tick(); settings(); setInterval(tick, 2000);
