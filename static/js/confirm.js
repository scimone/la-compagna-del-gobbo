/*
 * The app's confirmation popup, one look everywhere (replaces the browser's `window.confirm`):
 *
 *  - `appConfirm(message)` -> Promise<boolean>, for scripts (the character sheet's).
 *  - `data-app-confirm="message"` on a form or on a submit button: submitting asks first, and
 *    only goes through on OK. Works without any other script on the page.
 *
 * The button labels come from `window.APP_CONFIRM_LABELS` (translated by base.html).
 */
(function () {
  var dialog;

  function build() {
    dialog = document.createElement("dialog");
    dialog.className = "app-dialog";
    dialog.innerHTML =
      '<p class="app-dialog-message"></p><div class="app-dialog-buttons">' +
      '<button type="button" data-no></button><button type="button" class="ok" data-yes></button></div>';
    document.body.appendChild(dialog);
  }

  window.appConfirm = function (message) {
    if (!window.HTMLDialogElement || !document.createElement("dialog").showModal) {
      return Promise.resolve(window.confirm(message));
    }
    if (!dialog) build();
    var labels = window.APP_CONFIRM_LABELS || {};
    dialog.querySelector(".app-dialog-message").textContent = message;
    dialog.querySelector("[data-no]").textContent = labels.cancel || "Cancel";
    dialog.querySelector("[data-yes]").textContent = labels.ok || "OK";
    return new Promise(function (resolve) {
      function done(answer) {
        dialog.removeEventListener("click", onClick);
        dialog.removeEventListener("cancel", onCancel);
        dialog.close();
        resolve(answer);
      }
      function onClick(event) {
        if (event.target.closest("[data-yes]")) done(true);
        else if (event.target.closest("[data-no]")) done(false);
      }
      function onCancel(event) { event.preventDefault(); done(false); }
      dialog.addEventListener("click", onClick);
      dialog.addEventListener("cancel", onCancel);
      dialog.showModal();
    });
  };

  document.addEventListener(
    "submit",
    function (event) {
      var form = event.target;
      var trigger = event.submitter && event.submitter.dataset.appConfirm ? event.submitter : form;
      var message = trigger.dataset && trigger.dataset.appConfirm;
      if (!message || form.dataset.confirmed) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      window.appConfirm(message).then(function (ok) {
        if (!ok) return;
        form.dataset.confirmed = "1";
        try { form.requestSubmit(event.submitter || undefined); } finally { delete form.dataset.confirmed; }
      });
    },
    true
  );
})();
