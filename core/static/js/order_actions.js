(function () {
  var sharedNote = document.getElementById("admin-transition-note");
  if (!sharedNote) return;

  document.querySelectorAll("form.transition-form").forEach(function (form) {
    form.addEventListener("submit", function () {
      var hidden = form.querySelector('input[name="note"]');
      if (hidden) hidden.value = sharedNote.value;
    });
  });
})();
