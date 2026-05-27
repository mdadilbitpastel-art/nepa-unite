/* Product form — show/hide attribute fields when category is selected */
(function () {
  var catSelect = document.getElementById("id_category");
  var attrSection = document.getElementById("product-attr-fields");
  if (!catSelect || !attrSection) return;

  function toggle() {
    if (catSelect.value) {
      attrSection.style.display = "";
    } else {
      attrSection.style.display = "none";
    }
  }

  catSelect.addEventListener("change", toggle);
  toggle();
})();
