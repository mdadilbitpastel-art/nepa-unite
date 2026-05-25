/* CSP-safe confirm-on-submit wiring.
 *
 * Any element with a `data-confirm` attribute prompts the user
 * before continuing. Works for forms (intercepts submit) and links
 * (intercepts click). Inline `onsubmit=`/`onclick=` are blocked by
 * our CSP, so this delegated listener is the single supported path.
 *
 *   <form method="post" action="/x/" data-confirm="Delete this?">
 *   <a href="/x/" data-confirm="Leave page?">
 */
(function () {
  function ask(event) {
    var el = event.currentTarget;
    var message = el.getAttribute("data-confirm");
    if (message && !window.confirm(message)) {
      event.preventDefault();
      event.stopPropagation();
    }
  }

  function init() {
    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
      form.addEventListener("submit", ask);
    });
    document.querySelectorAll("a[data-confirm]").forEach(function (link) {
      link.addEventListener("click", ask);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
