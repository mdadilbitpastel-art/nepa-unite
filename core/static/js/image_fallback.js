/* Broken-image fallback.
 *
 *   <span class="thumb-wrap">
 *     <span class="placeholder-svg"><svg>…</svg></span>
 *     <img src="…" data-fallback>
 *   </span>
 *
 * The placeholder is rendered unconditionally; the <img> overlays it via
 * CSS (position: absolute; inset: 0). If the image fails to load, this
 * script removes the <img>, leaving the placeholder visible — so the
 * browser's broken-image glyph is never shown.
 *
 * Idempotent: each <img> only listens once.
 */
(function () {
  function init() {
    document.querySelectorAll("img[data-fallback]").forEach(function (img) {
      // Already loaded successfully before this script wired up.
      if (img.complete && img.naturalWidth > 0) { return; }
      // Already loaded but failed.
      if (img.complete && img.naturalWidth === 0) {
        img.remove();
        return;
      }
      img.addEventListener("error", function () { img.remove(); }, { once: true });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
