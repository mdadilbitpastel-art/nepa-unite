/* Product form: live "you receive after commission" hint next to Price.
 *
 * Reads the category -> commission-percent map injected as JSON, looks up the
 * rate for the selected category (falling back to the platform default), and
 * shows the seller's net price as they type. CSP-safe (external file). */
(function () {
  var dataEl = document.getElementById("commission-data");
  var priceEl = document.getElementById("id_price");
  var categoryEl = document.getElementById("id_category");
  var hintEl = document.getElementById("pf-net-hint");
  if (!dataEl || !priceEl || !hintEl) return;

  var data;
  try {
    data = JSON.parse(dataEl.textContent);
  } catch (e) {
    return;
  }
  var rates = data.rates || {};
  var defaultPct = Number(data.default) || 0;

  function rateFor(category) {
    if (category && Object.prototype.hasOwnProperty.call(rates, category)) {
      return Number(rates[category]);
    }
    return defaultPct;
  }

  function money(n) {
    return n.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function clearAttention() {
    if (categoryEl) categoryEl.classList.remove("pf-needs-attention");
  }

  function update() {
    var price = parseFloat(priceEl.value);
    if (!price || price <= 0 || isNaN(price)) {
      hintEl.hidden = true;
      hintEl.classList.remove("is-warning");
      clearAttention();
      return;
    }
    var category = categoryEl ? categoryEl.value : "";
    if (categoryEl && !category) {
      // Price entered without a category — prompt the seller to pick one.
      hintEl.hidden = false;
      hintEl.classList.add("is-warning");
      hintEl.textContent = "⚠ Select a category to calculate your earnings.";
      categoryEl.classList.add("pf-needs-attention");
      return;
    }
    hintEl.classList.remove("is-warning");
    clearAttention();
    var pct = rateFor(category);
    var commission = (price * pct) / 100;
    var net = price - commission;
    hintEl.hidden = false;
    hintEl.innerHTML =
      "You'll receive ~$" + money(net) +
      " <span class=\"muted\">after " + money(pct) +
      "% commission (−$" + money(commission) + ")</span>";
  }

  priceEl.addEventListener("input", update);
  if (categoryEl) categoryEl.addEventListener("change", update);
  update();
})();
