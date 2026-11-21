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
    $("button").textContent = "Run button: " + (s.run_button || "unknown");
    $("button").className = s.run_button === "on" ? "ok" : "muted";
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
    const st = $("stext");
    if (st) {
      st.textContent = ss.text_paused ? ss.text_paused : (ss.screen_text && ss.screen_text.length ? ss.screen_text.join("\n") : "—");
    }
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

// ---- Run button. Every Run or Stop is one passkey signature over a challenge the
// PC bound to this exact item, its files' fingerprint, the action and this phone.
const b64u = {
  enc: (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""),
  dec: (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), (c) => c.charCodeAt(0)).buffer,
};
async function postJSON(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), cache: "no-store" });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || ("error " + r.status));
  return j;
}
async function tap(item, action, msgEl) {
  msgEl.textContent = "Unlock your phone when it asks…";
  try {
    const opts = await postJSON("/api/tap/begin", { item: item, action: action });
    const pk = opts.publicKey;
    pk.challenge = b64u.dec(pk.challenge);
    (pk.allowCredentials || []).forEach((c) => { c.id = b64u.dec(c.id); });
    const cred = await navigator.credentials.get({ publicKey: pk });
    const res = await postJSON("/api/tap/finish", {
      id: cred.id, rawId: b64u.enc(cred.rawId), type: cred.type,
      response: { clientDataJSON: b64u.enc(cred.response.clientDataJSON), authenticatorData: b64u.enc(cred.response.authenticatorData),
        signature: b64u.enc(cred.response.signature), userHandle: cred.response.userHandle ? b64u.enc(cred.response.userHandle) : undefined },
    });
    msgEl.textContent = (action === "run" ? "Run " : "Stop ") + item + ": " + res.done;
    msgEl.className = "ok";
  } catch (e) {
    msgEl.textContent = "Refused: " + e.message;
    msgEl.className = "bad";
  }
  runTick(); items();
}
function badges(list, box) { box.replaceChildren(); (list || []).forEach((b) => box.appendChild(el("span", b, "badge"))); }
async function runTick() {
  try {
    const v = await (await fetch("/api/run", { cache: "no-store" })).json();
    if (!v.item_id) return;
    let s = v.item_id + (v.running ? " is running since " + new Date(v.started).toLocaleTimeString() : " ended");
    if (!v.running) s += v.stopped ? " (stopped by you)" : (v.exit_code === null || v.exit_code === undefined ? "" : " with exit code " + v.exit_code);
    if (v.error) s += " · problem: " + v.error;
    s += " · " + v.line_count + " lines" + (v.masked ? ", " + v.masked + " key-like parts blanked" : "");
    $("runstate").textContent = s;
    $("runstate").className = v.running ? "warn" : "muted";
    badges(v.running ? v.badges : [], $("runbadges"));
    $("runlines").textContent = (v.lines || []).join("\n");
    const sb = $("stopbtn"); sb.hidden = !v.running; sb.onclick = () => tap(v.item_id, "stop", $("runmsg"));
  } catch (e) { /* status tick reports reachability */ }
}
async function showFile(item, path, box) {
  box.replaceChildren(el("div", "Loading " + path + "…", "muted"));
  try {
    const r = await fetch("/api/items/" + encodeURIComponent(item) + "/file?path=" + encodeURIComponent(path), { cache: "no-store" });
    const v = await r.json();
    if (!r.ok) throw new Error(v.error);
    box.replaceChildren();
    if (v.has_previous) { box.appendChild(el("div", "Difference from the last approved version:", "muted")); box.appendChild(el("pre", v.diff.join("\n"))); }
    box.appendChild(el("div", path + (v.masked ? " (" + v.masked + " key-like parts blanked)" : ""), "muted"));
    box.appendChild(el("pre", v.text));
  } catch (e) { box.replaceChildren(el("div", "Cannot show: " + e.message, "bad")); }
}
async function items() {
  try {
    const r = await fetch("/api/items", { cache: "no-store" });
    const list = await r.json();
    if (!r.ok) throw new Error(list.error);
    const box = $("items"); box.replaceChildren();
    if (!list.length) box.appendChild(el("div", "Nothing staged.", "muted"));
    list.forEach((it) => {
      const c = el("div", undefined, "card");
      c.appendChild(el("h2", it.header.title || it.id));
      c.appendChild(el("div", it.id + " · from " + (it.header.claimed_by || "?"), "muted"));
      const est = el("div", "Your time / cost: " + it.estimate_time_shown + " · " + it.estimate_cost_shown);
      if (it.estimate_time_shown === "not stated" || it.estimate_cost_shown === "not stated") est.className = "bad";
      c.appendChild(est);
      const bb = el("div"); badges(it.badges, bb); c.appendChild(bb);
      (it.problems || []).forEach((p) => c.appendChild(el("div", "Problem: " + p, "bad")));
      c.appendChild(el("div", it.first_time ? "First time staged." : (it.changes.length ? "Changed since you last approved it:" : "Unchanged since you last approved it."), "muted"));
      const fl = el("div"); const view = el("div");
      it.files.forEach((f) => {
        const ch = (it.changes || []).find((x) => x.path === f.path);
        const b = el("button", f.path + (ch ? " (" + ch.what + ")" : ""));
        b.onclick = () => showFile(it.id, f.path, view);
        fl.appendChild(b);
      });
      (it.changes || []).filter((x) => x.what === "removed").forEach((x) => fl.appendChild(el("div", x.path + " (removed)", "muted")));
      c.appendChild(fl); c.appendChild(view);
      c.appendChild(el("div", "Fingerprint " + it.manifest_sha256.slice(0, 16) + "…", "muted"));
      const run = el("button", "Run (needs your phone unlock)", "go");
      run.disabled = (it.problems || []).length > 0;
      const msg = el("div", "", "muted");
      // Plan 6.4: a badged item asks a second confirm before the phone unlock.
      run.onclick = () => {
        if ((it.badges || []).length && !window.confirm("This item is marked: " + it.badges.join("; ") + ". Run it anyway?")) return;
        tap(it.id, "run", msg);
      };
      c.appendChild(run); c.appendChild(msg);
      box.appendChild(c);
    });
  } catch (e) { $("items").textContent = "Cannot list items: " + e.message; }
}
async function passkey() {
  try {
    const v = await (await fetch("/api/passkey", { cache: "no-store" })).json();
    $("pkstate").textContent = v.count ? v.count + " passkey(s) registered." : "No passkey yet: Run and Stop are refused until one is added at the desk.";
    $("risk").textContent = v.risk_note;
  } catch (e) { /* status tick reports reachability */ }
}
$("pkbtn").onclick = async () => {
  const m = $("pkmsg");
  m.textContent = "Unlock your phone when it asks…"; m.className = "muted";
  try {
    const opts = await postJSON("/api/passkey/begin", {});
    const pk = opts.publicKey;
    pk.challenge = b64u.dec(pk.challenge); pk.user.id = b64u.dec(pk.user.id);
    (pk.excludeCredentials || []).forEach((c) => { c.id = b64u.dec(c.id); });
    const cred = await navigator.credentials.create({ publicKey: pk });
    const res = await postJSON("/api/passkey/finish", {
      id: cred.id, rawId: b64u.enc(cred.rawId), type: cred.type,
      response: { clientDataJSON: b64u.enc(cred.response.clientDataJSON), attestationObject: b64u.enc(cred.response.attestationObject),
        transports: cred.response.getTransports ? cred.response.getTransports() : [] },
    });
    m.replaceChildren(el("div", "Code: " + res.code, "ok"), el("div", res.next, "muted"));
  } catch (e) {
    m.textContent = "Not added: " + e.message + (e.message.includes("reopen") ? "" : " This registration window is now used up. Run the passkey step at the desk again to reopen it, then try once more.");
    m.className = "bad";
  }
  passkey();
};
tick(); settings(); runTick(); items(); passkey();
setInterval(tick, 2000); setInterval(runTick, 2000); setInterval(items, 15000); setInterval(passkey, 15000);
