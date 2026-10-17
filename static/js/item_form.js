// The parts of the custom item / custom feature forms that need a script (loaded on every page,
// and working through event delegation, so a form fetched into an overlay later needs no setup):
//
//  - the effects editor (`_effects_editor.html`): rows of "target + number", kept in the hidden
//    `effects` field as JSON so the form posts them like any other field;
//  - `data-show-if="<checkbox name>"`: shown only while that checkbox in the same form is ticked.
(function () {
  "use strict";

  function optionsOf(editor) {
    if (!editor._groups) {
      var script = editor.querySelector("script[data-effects-options]");
      try { editor._groups = JSON.parse(script.textContent); } catch (e) { editor._groups = []; }
    }
    return editor._groups;
  }

  function flatOptions(editor) {
    var all = {};
    optionsOf(editor).forEach(function (g) { g.options.forEach(function (o) { all[o.key] = o; }); });
    return all;
  }

  // The weapon's own rolls are for weapons: the editor says so itself (an edit page), or the
  // Category picked in the same form does (the add sheet).
  function forWeapon(editor) {
    if (editor.dataset.weapon === "1") return true;
    var form = editor.closest("[data-custom-form], form");
    var section = form && form.querySelector('input[name="section"]:checked');
    return !!section && section.value === "weapons";
  }

  function fillTargets(editor, select, chosen) {
    var weapon = forWeapon(editor);
    select.textContent = "";
    optionsOf(editor).forEach(function (group) {
      if (group.weapon && !weapon) return;
      var og = document.createElement("optgroup");
      og.label = group.label;
      group.options.forEach(function (o) { og.appendChild(new Option(o.label, o.key)); });
      select.appendChild(og);
    });
    if (chosen && select.querySelector('option[value="' + chosen + '"]')) select.value = chosen;
  }

  function syncRow(editor, row) {
    var option = flatOptions(editor)[row.querySelector("select").value];
    var number = row.querySelector("input");
    number.hidden = !!(option && option.flag);
  }

  function serialize(editor) {
    var all = flatOptions(editor);
    var effects = [];
    editor.querySelectorAll(".fx-row").forEach(function (row) {
      var target = row.querySelector("select").value;
      var number = row.querySelector("input");
      if (!all[target]) return;
      if (all[target].flag) return effects.push({ target: target, value: 1 });
      var value = parseInt(number.value, 10);
      if (!isNaN(value)) effects.push({ target: target, value: value });
    });
    editor.querySelector('input[name="effects"]').value = effects.length ? JSON.stringify(effects) : "";
  }

  function addRow(editor, effect) {
    var labels = editor.querySelector("[data-effects-labels]").dataset;
    var row = document.createElement("div");
    row.className = "fx-row";
    var select = document.createElement("select");
    select.setAttribute("aria-label", labels.target);
    fillTargets(editor, select, effect && effect.target);
    var number = document.createElement("input");
    number.type = "number";
    number.step = "1";
    number.inputMode = "numeric";
    number.setAttribute("aria-label", labels.value);
    number.value = effect && effect.value !== undefined ? effect.value : "1";
    var remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.setAttribute("aria-label", labels.remove);
    remove.dataset.effectsRemove = "1";
    row.append(select, number, remove);
    editor.querySelector("[data-effects-rows]").appendChild(row);
    syncRow(editor, row);
    return row;
  }

  // (Re)draw the rows from the hidden field's JSON.
  function load(editor) {
    editor.querySelector("[data-effects-rows]").textContent = "";
    var effects = [];
    try { effects = JSON.parse(editor.querySelector('input[name="effects"]').value || "[]"); } catch (e) {}
    effects.forEach(function (effect) { addRow(editor, effect); });
  }

  function syncShowIf(scope) {
    scope.querySelectorAll("[data-show-if]").forEach(function (el) {
      var form = el.closest("[data-custom-form], form");
      var box = form && form.querySelector('input[type="checkbox"][name="' + el.dataset.showIf + '"]');
      el.hidden = !(box && box.checked);
    });
  }

  document.addEventListener("click", function (event) {
    var add = event.target.closest("[data-effects-add]");
    if (add) {
      var editor = add.closest("[data-effects]");
      addRow(editor).querySelector("select").focus();
      serialize(editor);
      return;
    }
    var remove = event.target.closest("[data-effects-remove]");
    if (remove) {
      var owner = remove.closest("[data-effects]");
      remove.closest(".fx-row").remove();
      serialize(owner);
    }
  });

  document.addEventListener("input", function (event) {
    var editor = event.target.closest && event.target.closest("[data-effects]");
    if (editor) serialize(editor);
  });

  document.addEventListener("change", function (event) {
    var target = event.target;
    var editor = target.closest && target.closest("[data-effects]");
    if (editor) {
      if (target.tagName === "SELECT") syncRow(editor, target.closest(".fx-row"));
      return serialize(editor);
    }
    if (target.type === "checkbox") syncShowIf(target.closest("[data-custom-form], form") || document);
    if (target.name === "section") {
      // A new Category changes which targets a weapon-less form may offer.
      var form = target.closest("[data-custom-form], form");
      if (!form) return;
      form.querySelectorAll("[data-effects]").forEach(function (ed) {
        ed.querySelectorAll(".fx-row select").forEach(function (select) { fillTargets(ed, select, select.value); });
        serialize(ed);
      });
    }
  });

  // For a form that was just emptied (the add sheet, after an item went in).
  window.itemForm = {
    reset: function (scope) {
      scope.querySelectorAll("[data-effects]").forEach(function (editor) {
        editor.querySelector('input[name="effects"]').value = "";
        load(editor);
      });
      syncShowIf(scope);
    },
  };

  function init() {
    document.querySelectorAll("[data-effects]").forEach(load);
    syncShowIf(document);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
