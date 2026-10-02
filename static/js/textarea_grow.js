/* Editable text areas are never shorter than their text: each <textarea> grows to fit its content
 * (on load, on every input, and whenever it becomes visible or its width changes). */
(function () {
  "use strict";
  function fit(ta) {
    if (!ta.offsetParent && !ta.getClientRects().length) return; // hidden: measured when shown
    var border = ta.offsetHeight - ta.clientHeight;
    ta.style.height = "auto";
    ta.style.height = (ta.scrollHeight + border) + "px";
  }
  function attach(ta) {
    if (ta.dataset.grow) return;
    ta.dataset.grow = "1";
    ta.style.overflowY = "hidden";
    ta.addEventListener("input", function () { fit(ta); });
    if (window.ResizeObserver) {
      var width = ta.offsetWidth;
      new ResizeObserver(function () {
        if (ta.offsetWidth !== width || !ta.style.height) { width = ta.offsetWidth; fit(ta); }
      }).observe(ta);
    }
    fit(ta);
  }
  function init() { document.querySelectorAll("textarea").forEach(attach); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
