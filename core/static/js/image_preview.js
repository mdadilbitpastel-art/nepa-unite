/* Live image preview for file inputs.
 *
 *   <input type="file" data-image-preview="#some-container">
 *
 * When the user picks a file, the matching container's contents are
 * wiped and replaced with an <img> showing the selection. The
 * container size is governed by CSS (img is set to width:100%; height:100%;
 * object-fit:cover) so callers control the preview footprint.
 *
 * CSP-safe — sourced from a same-origin static file, no inline JS, and
 * data: URIs are already whitelisted by our img-src policy.
 */
(function () {
  function handlePick(input) {
    var targetSelector = input.getAttribute("data-image-preview");
    if (!targetSelector) { return; }
    var target = document.querySelector(targetSelector);
    if (!target) { return; }

    var file = input.files && input.files[0];
    if (!file) { return; }
    if (file.type && file.type.indexOf("image/") !== 0) { return; }

    var reader = new FileReader();
    reader.onload = function (ev) {
      // Preserve the placeholder SVG underneath — just upsert the <img>
      // on top. If the picked file ever fails to render, the placeholder
      // is the natural fallback.
      var img = target.querySelector("img");
      if (!img) {
        img = document.createElement("img");
        img.alt = "Product image preview";
        target.appendChild(img);
      }
      img.src = ev.target.result;
    };
    reader.readAsDataURL(file);
  }

  function init() {
    var inputs = document.querySelectorAll('input[type="file"][data-image-preview]');
    inputs.forEach(function (input) {
      input.addEventListener("change", function () { handlePick(input); });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
