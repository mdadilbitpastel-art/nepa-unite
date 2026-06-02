// Buyer checkout — Stripe Payment Element.
// Config arrives via data-* attributes on #payment-form (CSP-safe: no inline JS).
(function () {
  "use strict";

  var form = document.getElementById("payment-form");
  if (!form || typeof Stripe === "undefined") {
    return;
  }

  var publishableKey = form.getAttribute("data-publishable-key");
  var clientSecret = form.getAttribute("data-client-secret");
  var returnUrl = form.getAttribute("data-return-url");

  var errorBox = document.getElementById("pay-error");
  var submitBtn = document.getElementById("pay-submit");
  var submitText = document.getElementById("pay-submit-text");
  var submitSpinner = document.getElementById("pay-submit-spinner");

  function showError(message) {
    if (!errorBox) return;
    errorBox.textContent = message || "Something went wrong. Please try again.";
    errorBox.classList.add("show");
  }

  function clearError() {
    if (!errorBox) return;
    errorBox.textContent = "";
    errorBox.classList.remove("show");
  }

  function setBusy(busy) {
    if (submitBtn) submitBtn.disabled = busy;
    if (submitText) submitText.style.display = busy ? "none" : "";
    if (submitSpinner) submitSpinner.style.display = busy ? "inline-block" : "none";
  }

  if (!publishableKey || !clientSecret) {
    showError("Payment isn't configured correctly. Please contact support.");
    return;
  }

  var stripe = Stripe(publishableKey);
  var elements = stripe.elements({ clientSecret: clientSecret });
  var paymentElement = elements.create("payment");
  paymentElement.mount("#payment-element");

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    clearError();
    setBusy(true);

    stripe
      .confirmPayment({
        elements: elements,
        confirmParams: { return_url: returnUrl },
      })
      .then(function (result) {
        // On success Stripe redirects to return_url, so we only land here on
        // error (or when the card needs no redirect and failed validation).
        if (result.error) {
          showError(result.error.message);
          setBusy(false);
        }
      })
      .catch(function () {
        showError("We couldn't reach Stripe. Check your connection and retry.");
        setBusy(false);
      });
  });
})();
