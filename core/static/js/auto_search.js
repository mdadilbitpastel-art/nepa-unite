/* Debounced auto-search for any <form class="auto-search-form">.
 *
 * Behaviour:
 *   - Text / search inputs: submit 1s after the user stops typing.
 *     Typing in another input on the same form resets the timer.
 *   - <select> elements: submit immediately on change.
 *   - After an auto-submit reload, focus is restored to the first
 *     search input with a value so the user can keep typing.
 *
 * Loaded once from base_app.html — no per-page wiring needed.
 */
(function () {
  var DEBOUNCE_MS = 1000;

  function init() {
    var forms = document.querySelectorAll("form.auto-search-form");
    forms.forEach(function (form) {
      var timer = null;

      function scheduleSubmit() {
        if (timer) { clearTimeout(timer); }
        timer = setTimeout(function () { form.submit(); }, DEBOUNCE_MS);
      }

      var textInputs = form.querySelectorAll(
        'input[type="search"], input[type="text"], input[type="email"]'
      );
      textInputs.forEach(function (input) {
        input.addEventListener("input", scheduleSubmit);
      });

      var selects = form.querySelectorAll("select");
      selects.forEach(function (select) {
        select.addEventListener("change", function () {
          if (timer) { clearTimeout(timer); }
          form.submit();
        });
      });

      // Restore caret to the search box after an auto-submit reload —
      // browser's normal focus behaviour drops it on the body otherwise.
      var firstSearch = form.querySelector('input[type="search"]');
      if (
        firstSearch &&
        firstSearch.value &&
        document.activeElement === document.body
      ) {
        firstSearch.focus();
        var len = firstSearch.value.length;
        try { firstSearch.setSelectionRange(len, len); } catch (_) { /* ignore */ }
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
