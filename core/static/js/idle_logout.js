// Client-side inactivity auto-logout (defense-in-depth; the server middleware
// enforces it regardless, this just gives immediate logout + a warning).
// Config comes from <body data-inactivity-timeout="300" data-logout-url="/logout/">.
// Multi-tab: activity in any tab resets every tab via localStorage.
(function () {
  "use strict";

  var body = document.body;
  var timeout = parseInt(body.getAttribute("data-inactivity-timeout"), 10) || 300; // seconds
  var logoutUrl = body.getAttribute("data-logout-url");
  var keepaliveUrl = body.getAttribute("data-keepalive-url");
  if (!logoutUrl || timeout < 30) return;

  var warnBefore = Math.min(60, Math.max(15, Math.floor(timeout / 5))); // warn window (s)
  // Ping the server at most this often so on-page activity refreshes the
  // server-side window without hammering it.
  var pingEvery = Math.min(120, Math.max(30, Math.floor(timeout / 3))) * 1000;
  var STORAGE_KEY = "nepa_last_activity";

  function pingServer() {
    if (!keepaliveUrl || !window.fetch) return;
    fetch(keepaliveUrl, {
      method: "GET",
      credentials: "same-origin",
      redirect: "manual",  // a 302 -> login means the session is already gone
      headers: { "X-Requested-With": "XMLHttpRequest" },
    })
      .then(function (r) { if (!r.ok) doLogout(); })  // 302->login or error = session gone
      .catch(function () {});
  }

  var warnTimer = null, logoutTimer = null, countdownTimer = null;
  var banner = null;

  function doLogout() {
    window.location.href = logoutUrl;
  }

  function hideBanner() {
    if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null; }
    if (banner) { banner.remove(); banner = null; }
  }

  function showBanner() {
    if (banner) return;
    banner = document.createElement("div");
    banner.setAttribute("role", "alertdialog");
    var s = banner.style;
    s.position = "fixed"; s.bottom = "20px"; s.right = "20px"; s.zIndex = "99999";
    s.maxWidth = "320px"; s.padding = "14px 16px"; s.borderRadius = "10px";
    s.background = "#1f2937"; s.color = "#fff"; s.fontSize = "13px";
    s.lineHeight = "1.5"; s.boxShadow = "0 8px 28px rgba(0,0,0,.35)";
    s.fontFamily = "system-ui, sans-serif";

    var msg = document.createElement("div");
    var span = document.createElement("strong");
    var remaining = warnBefore;
    function render() {
      span.textContent = remaining + "s";
    }
    msg.appendChild(document.createTextNode("You'll be signed out in "));
    msg.appendChild(span);
    msg.appendChild(document.createTextNode(" due to inactivity."));
    render();

    var btn = document.createElement("button");
    btn.textContent = "Stay signed in";
    var bs = btn.style;
    bs.marginTop = "10px"; bs.padding = "6px 12px"; bs.border = "0";
    bs.borderRadius = "6px"; bs.background = "#d4a155"; bs.color = "#1a1208";
    bs.fontWeight = "600"; bs.cursor = "pointer"; bs.fontSize = "13px";
    btn.addEventListener("click", function () { recordActivity(true); });

    banner.appendChild(msg);
    banner.appendChild(btn);
    document.body.appendChild(banner);

    countdownTimer = setInterval(function () {
      remaining -= 1;
      if (remaining <= 0) { doLogout(); return; }
      render();
    }, 1000);
  }

  function armTimers() {
    clearTimeout(warnTimer);
    clearTimeout(logoutTimer);
    warnTimer = setTimeout(showBanner, (timeout - warnBefore) * 1000);
    logoutTimer = setTimeout(doLogout, timeout * 1000);
  }

  function reset() {
    hideBanner();
    armTimers();
  }

  // Record activity locally + broadcast to other tabs + refresh server window.
  var lastBroadcast = 0;
  var lastPing = 0;
  function recordActivity(force) {
    reset();
    var now = Date.now();
    if (now - lastBroadcast > 1000) {
      lastBroadcast = now;
      try { localStorage.setItem(STORAGE_KEY, String(now)); } catch (e) {}
    }
    if (force || now - lastPing > pingEvery) {
      lastPing = now;
      pingServer();
    }
  }

  // Throttle high-frequency events.
  var lastLocal = 0;
  function onActivity() {
    var now = Date.now();
    if (banner || now - lastLocal > 1000) { lastLocal = now; recordActivity(); }
  }

  ["mousemove", "mousedown", "keydown", "scroll", "touchstart", "click"].forEach(
    function (evt) { document.addEventListener(evt, onActivity, { passive: true }); }
  );

  // Another tab saw activity → reset here too.
  window.addEventListener("storage", function (e) {
    if (e.key === STORAGE_KEY) reset();
  });

  reset();
})();
