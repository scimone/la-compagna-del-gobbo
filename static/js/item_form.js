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

  // ---- the spells field (`_spells_editor.html`): chips, and a dialog with the whole spell list ------
  //
  // The field holds `[{id, free}]` (`free`: "", "long", "short" or "unlimited") in the hidden `spells`
  // input. The chips show the chosen spells, each with a select for how it may be cast without a slot;
  // "Choose spells" opens the list (fetched once from the editor's `data-picker-url`): search, filters,
  // a Read button that unfolds the spell, and an Add button that asks about the free cast first.

  var FREE = ["", "long", "short", "unlimited"];

  function spellState(editor) {
    if (!editor._spells) {
      var names = {};
      try { names = JSON.parse(editor.querySelector("[data-spells-names]").textContent || "{}"); } catch (e) {}
      editor._names = names;
      try { editor._spells = JSON.parse(editor.querySelector('input[name="spells"]').value || "[]"); } catch (e) { editor._spells = []; }
      editor._spells = editor._spells.map(function (e) { return typeof e === "string" ? { id: e, free: "" } : e; });
    }
    return editor._spells;
  }

  function drawSpells(editor) {
    var list = spellState(editor);
    var labels = editor.querySelector("[data-spells-labels]").dataset;
    editor.querySelector('input[name="spells"]').value = list.length ? JSON.stringify(list) : "";
    var chips = editor.querySelector("[data-spells-chips]");
    chips.textContent = "";
    list.forEach(function (entry) {
      var li = document.createElement("li");
      li.appendChild(document.createTextNode(editor._names[entry.id] || entry.id));
      var select = document.createElement("select");
      select.className = "sp-free";
      select.dataset.spellFree = entry.id;
      select.setAttribute("aria-label", labels.free);
      FREE.forEach(function (key) {
        var option = new Option(labels[key || "none"], key);
        option.selected = key === entry.free;
        select.appendChild(option);
      });
      var remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "×";
      remove.dataset.spellRemove = entry.id;
      remove.setAttribute("aria-label", labels.remove);
      li.append(select, remove);
      chips.appendChild(li);
    });
  }

  function addSpell(editor, id, name, free) {
    var list = spellState(editor);
    editor._names[id] = name;
    var found = list.filter(function (e) { return e.id === id; })[0];
    if (found) found.free = free;
    else list.push({ id: id, free: free });
    drawSpells(editor);
  }

  document.addEventListener("change", function (event) {
    var select = event.target;
    if (!select.dataset || select.dataset.spellFree === undefined) return;
    var editor = select.closest("[data-spells]");
    spellState(editor).forEach(function (e) { if (e.id === select.dataset.spellFree) e.free = select.value; });
    drawSpells(editor);
  });

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-spell-remove]");
    if (!button) return;
    var editor = button.closest("[data-spells]");
    editor._spells = spellState(editor).filter(function (e) { return e.id !== button.dataset.spellRemove; });
    drawSpells(editor);
  });

  // The picker dialog: one per page, filled once.
  var picker = null;       // {dialog, body, ready}
  var pickerEditor = null; // the editor the dialog is choosing for

  function markAdded() {
    if (!picker || !pickerEditor) return;
    var chosen = {};
    spellState(pickerEditor).forEach(function (e) { chosen[e.id] = true; });
    picker.body.querySelectorAll("[data-spk-list] > li").forEach(function (li) {
      li.classList.toggle("added", !!chosen[li.dataset.id]);
      li.querySelector("[data-spk-add]").textContent = chosen[li.dataset.id] ? picker.added : picker.add;
    });
  }

  function filterSpells() {
    var query = (picker.body.querySelector("[data-spk-search]").value || "").trim().toLowerCase();
    var selects = picker.body.querySelectorAll("[data-spk-filter]");
    var shown = 0;
    picker.body.querySelectorAll("[data-spk-list] > li").forEach(function (li) {
      var ok = !query || li.dataset.search.indexOf(query) >= 0;
      selects.forEach(function (select) {
        if (!ok || !select.value) return;
        var values = (li.dataset[select.dataset.spkFilter] || "").split(" ");
        ok = values.indexOf(select.value) >= 0;
      });
      li.hidden = !ok;
      if (ok) shown += 1;
    });
    picker.body.querySelector("[data-spk-empty]").hidden = shown > 0;
  }

  function ensurePicker(editor) {
    if (picker) return picker.ready;
    var dialog = document.createElement("dialog");
    dialog.className = "spk-dialog";
    dialog.innerHTML = '<div class="spk-wrap"><div class="spk-head"><h3></h3><button type="button" data-spk-close></button></div><div class="spk-body"></div></div>';
    var labels = editor.querySelector("[data-spells-labels]").dataset;
    dialog.querySelector("h3").textContent = editor.querySelector(".fx-title").textContent;
    dialog.querySelector("[data-spk-close]").textContent = labels.done;
    document.body.appendChild(dialog);
    picker = { dialog: dialog, body: dialog.querySelector(".spk-body"), add: "", added: "" };
    picker.ready = fetch(editor.dataset.pickerUrl, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.text() : Promise.reject(); })
      .then(function (html) {
        picker.body.innerHTML = html;
        var add = picker.body.querySelector("[data-spk-add]");
        picker.add = add ? add.textContent : "Add";
        picker.added = "✓";
        picker.body.addEventListener("input", function (e) { if (e.target.matches("[data-spk-search]")) filterSpells(); });
        picker.body.addEventListener("change", function (e) {
          if (e.target.matches("[data-spk-filter]")) {
            e.target.classList.toggle("active", !!e.target.value);
            filterSpells();
          }
        });
        picker.body.addEventListener("click", pickerClick);
        dialog.querySelector("[data-spk-close]").addEventListener("click", function () { dialog.close(); });
      })
      .catch(function () { picker.body.textContent = "…"; picker = null; });
    return picker.ready;
  }

  function pickerClick(event) {
    var li = event.target.closest("[data-spk-list] > li");
    if (!li) return;
    var free = li.querySelector(".spk-free");
    var read = event.target.closest("[data-spk-read]");
    if (read) {
      var desc = li.querySelector(".spk-desc");
      var open = desc.hidden;
      if (open && !desc.dataset.loaded) {
        desc.textContent = "…";
        fetch(read.dataset.spkRead, { credentials: "same-origin" })
          .then(function (r) { return r.ok ? r.text() : Promise.reject(); })
          .then(function (html) { desc.innerHTML = html; desc.dataset.loaded = "1"; })
          .catch(function () { desc.textContent = ""; desc.hidden = true; });
      }
      desc.hidden = !open;
      read.setAttribute("aria-expanded", open ? "true" : "false");
    } else if (event.target.closest("[data-spk-add]")) {
      var current = spellState(pickerEditor).filter(function (e) { return e.id === li.dataset.id; })[0];
      free.querySelector("[data-spk-free]").value = current ? current.free : "";
      free.hidden = !free.hidden;
    } else if (event.target.closest("[data-spk-cancel]")) {
      free.hidden = true;
    } else if (event.target.closest("[data-spk-confirm]")) {
      addSpell(pickerEditor, li.dataset.id, li.dataset.name, free.querySelector("[data-spk-free]").value);
      free.hidden = true;
      markAdded();
    }
  }

  document.addEventListener("click", function (event) {
    var open = event.target.closest("[data-spells-open]");
    if (!open) return;
    var editor = open.closest("[data-spells]");
    pickerEditor = editor;
    ensurePicker(editor).then(function () {
      if (!picker) return;
      markAdded();
      picker.dialog.showModal();
    });
  });

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
      scope.querySelectorAll("[data-spells]").forEach(function (editor) { editor._spells = []; drawSpells(editor); });
      syncShowIf(scope);
    },
  };

  function init() {
    document.querySelectorAll("[data-effects]").forEach(load);
    document.querySelectorAll("[data-spells]").forEach(drawSpells);
    syncShowIf(document);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
