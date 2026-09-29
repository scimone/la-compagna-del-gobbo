/*
 * The character sheet (templates/frontend/characters/detail.html).
 *
 *  - tabs: every panel is already in the page; a tab only shows one and rewrites `?tab=` so a
 *    reload or a language switch comes back to it.
 *  - actions: anything with `data-act` posts to the sheet's endpoint (`data-act-url` on #cs) - a
 *    button on click, an input/textarea/select when it changes. The extra `data-*` attributes are
 *    the parameters. The server answers with the state to redraw; `refresh: true` means something
 *    derived changed (AC, attacks), so the whole sheet is re-fetched and swapped instead.
 *  - descriptions: `data-describe="<url>"` rows (the "add a spell" and "add a feature" lists)
 *    unfold a description under themselves (`data-toggle` rows just unfold what is already there); chips
 *    (inside `data-panel-group`) show it in the panel that follows their group.
 *  - the spellbook's search and filter buttons filter the rows on the spot; so do those of the
 *    "add an item", "add a spell" and "add a feature" overlays, which are fetched the first time
 *    they are opened.
 *  - the portrait: choosing a file (or removing it) posts to its own endpoint (`data-portrait-url`).
 *
 * Nothing here is a rule: the numbers come from the server.
 */
(function () {
  var root = document.getElementById("cs");
  if (!root) return;

  var actUrl = root.dataset.actUrl;
  var csrfInput = root.querySelector("input[name=csrfmiddlewaretoken]");
  var csrf = csrfInput ? csrfInput.value : "";
  var toast = document.getElementById("cs-toast");
  var descriptions = {}; // url -> Promise<html>

  // ---- tabs ------------------------------------------------------------------------------

  // The scrolling part of whichever panel is showing (the fixed part above it never scrolls).
  function scroller() {
    return root.querySelector(".cs-panel:not([hidden]) .cs-scroll");
  }

  // Scroll the tab strip (only it - never the page) so `button` sits in the middle.
  function centreTab(button) {
    var strip = button.parentElement;
    strip.scrollLeft = button.offsetLeft - (strip.clientWidth - button.offsetWidth) / 2;
  }

  function showTab(key, updateUrl) {
    var shown = false;
    root.querySelectorAll(".cs-panel").forEach(function (panel) {
      var on = panel.dataset.panel === key;
      panel.hidden = !on;
      shown = shown || on;
    });
    if (!shown) return;
    root.querySelectorAll(".cs-tabs button").forEach(function (button) {
      var on = button.dataset.tab === key;
      button.classList.toggle("active", on);
      button.setAttribute("aria-selected", on ? "true" : "false");
      if (on) centreTab(button);
    });
    var area = scroller();
    if (area) area.scrollTop = 0;
    if (updateUrl) {
      var url = new URL(window.location.href);
      url.searchParams.set("tab", key);
      var next = url.pathname + url.search + url.hash;
      if (window.appNav) window.appNav.replaceUrl(next);
      else window.history.replaceState(window.history.state, "", next);
    }
  }

  // ---- talking to the server -------------------------------------------------------------

  var queue = Promise.resolve(); // one request at a time, in the order they were made

  function notify(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.hidden = false;
    window.clearTimeout(notify.timer);
    notify.timer = window.setTimeout(function () { toast.hidden = true; }, 3500);
  }

  function showError(message) {
    notify(message || root.dataset.error);
  }

  function paramsOf(el) {
    var params = { action: el.dataset.act };
    var skip = ["act", "bind", "describe", "label", "toggle", "tab", "confirm", "done", "buy", "cost"];
    Object.keys(el.dataset).forEach(function (key) {
      if (skip.indexOf(key) === -1) params[key] = el.dataset[key];
    });
    if (el.matches("input, textarea, select")) params.value = el.value;
    return params;
  }

  // ---- buying: the purse total, read live (the coin purse's own `data-bind` elements, not a  ----
  // ---- number fetched from the server - so it is right even after other coins changed) -------

  function coinAmount(key) {
    var el = root.querySelector('[data-bind="coins.' + key + '"]');
    if (!el) return 0;
    return Number(el.matches("input") ? el.value : el.textContent) || 0;
  }

  function purseCopper() {
    return (
      coinAmount("copper") +
      coinAmount("silver") * 10 +
      coinAmount("electrum") * 50 +
      coinAmount("gold") * 100 +
      coinAmount("platinum") * 1000
    );
  }

  // Hide the Buy pill on any catalog row the purse can no longer afford (and bring it back once it
  // can again) - checked against the purse as it stands right now, same as the confirmation dialog.
  function updateBuyButtons() {
    var copper = purseCopper();
    root.querySelectorAll(".equip.buy[data-cost]").forEach(function (button) {
      button.hidden = Number(button.dataset.cost) > copper;
    });
  }

  // gp/sp/cp only, like the server's own `_gold_label` (platinum and electrum are never spent on
  // a purchase, so they never show up in a price or a balance).
  function copperLabel(copper) {
    var gold = Math.floor(copper / 100);
    var silver = Math.floor((copper % 100) / 10);
    var cp = copper % 10;
    var parts = [];
    if (gold) parts.push(root.dataset.fmtGp.replace("%(n)d", gold));
    if (silver) parts.push(root.dataset.fmtSp.replace("%(n)d", silver));
    if (cp) parts.push(root.dataset.fmtCp.replace("%(n)d", cp));
    return parts.length ? parts.join(" ") : root.dataset.fmtGp.replace("%(n)d", 0);
  }

  // Post an action. Resolves to true when the server accepted it (after any redraw it asked for).
  function send(params) {
    var job = queue.then(function () {
      return fetch(actUrl, {
        method: "POST",
        body: new URLSearchParams(params),
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest" },
      })
        .then(function (response) {
          return response.json().then(function (json) { return { ok: response.ok, json: json }; });
        })
        .then(function (result) {
          if (!result.ok) {
            showError();
            return refresh().then(function () { return false; }); // put back what the server really has
          }
          apply(result.json.state);
          if (result.json.message) notify(result.json.message);
          return (result.json.refresh ? refresh() : Promise.resolve()).then(function () { return true; });
        })
        .catch(function () { showError(); return false; });
    });
    queue = job;
    return job;
  }

  function lookup(state, path) {
    return path.split(".").reduce(function (value, key) {
      return value === undefined || value === null ? undefined : value[key];
    }, state);
  }

  // Redraw what an action can change. The pips carry their own `data-delta`, so they are rebuilt
  // from the counts rather than toggled.
  function apply(state) {
    root.querySelectorAll("[data-bind]").forEach(function (el) {
      var value = lookup(state, el.dataset.bind);
      if (value === undefined) return;
      if (el.matches("input")) {
        if (document.activeElement !== el) el.value = value;
      } else {
        el.textContent = value;
      }
    });
    var title = document.querySelector("header .brand");
    if (title && state.name) title.textContent = state.name;

    ["successes", "failures"].forEach(function (kind) {
      root.querySelectorAll('[data-death="' + kind + '"] .box').forEach(function (box) {
        box.classList.toggle("on", Number(box.dataset.index) <= state["death_" + kind]);
      });
    });

    root.querySelectorAll(".cs-insp").forEach(function (button) {
      button.classList.toggle("on", state.inspiration);
      button.setAttribute("aria-pressed", state.inspiration ? "true" : "false");
      button.dataset.value = state.inspiration ? "0" : "1";
    });

    root.querySelectorAll("[data-hd]").forEach(function (row) {
      var hd = state.hit_dice[row.dataset.hd];
      if (hd) setPips(row, hd.total - hd.spent);
    });

    root.querySelectorAll(".cs-slot-row").forEach(function (row) {
      var slot = state.slots[row.dataset.slot];
      if (slot) setPips(row, slot.max - slot.spent);
    });

    root.querySelectorAll("[data-hp-bar]").forEach(function (bar) {
      var pct = state.max_hp ? Math.max(0, Math.min(100, (state.hp / state.max_hp) * 100)) : 0;
      bar.style.setProperty("--pct", pct + "%");
    });

    updateBuyButtons();
    updateCustomBuy();
    updateCastButtons();
  }

  // A row of pips (spell slots, Hit Dice) with `left` of them filled. Each pip carries the delta it
  // would post: a filled one spends, an empty one recovers.
  function setPips(row, left) {
    row.querySelectorAll(".pip-btn").forEach(function (pip, index) {
      var on = index < left;
      pip.classList.toggle("on", on);
      pip.dataset.delta = on ? "1" : "-1";
    });
    row.querySelector(".cnt .left").textContent = left;
  }

  // Re-fetch the page and swap what is inside #cs-swap, keeping the tab (it is in the URL) and
  // the scroll position of its scrolling part.
  function refresh() {
    var area = scroller();
    var scroll = area ? area.scrollTop : 0;
    return fetch(window.location.href, { credentials: "same-origin" })
      .then(function (response) { return response.text(); })
      .then(function (html) {
        var fresh = new DOMParser().parseFromString(html, "text/html").getElementById("cs-swap");
        var current = document.getElementById("cs-swap");
        if (!fresh || !current) return;
        current.innerHTML = fresh.innerHTML;
        setup();
        area = scroller();
        if (area) area.scrollTop = scroll;
      })
      .catch(function () { showError(); });
  }

  root.addEventListener("click", function (event) {
    var button = event.target.closest("button[data-act]");
    if (button && !button.disabled) {
      event.preventDefault();
      var ask = "";
      if (button.dataset.buy) {
        // The price and what is left afterwards, both worked out from the purse as it stands right
        // now (this sheet is fetched once and never refreshed, so a static confirmation could go
        // stale after an earlier buy).
        var cost = Number(button.dataset.cost) || 0;
        var confirmText =
          root.dataset.fmtBuyConfirm.replace("%(price)s", copperLabel(cost)) +
          "\n" +
          root.dataset.fmtBuyLeft.replace("%(left)s", copperLabel(Math.max(0, purseCopper() - cost)));
        ask = confirmText;
      } else if (button.dataset.confirm) {
        ask = button.dataset.confirm;
      }
      (ask ? window.appConfirm(ask) : Promise.resolve(true)).then(function (ok) {
        if (!ok) return;
        send(paramsOf(button)).then(function (accepted) {
          if (accepted && button.dataset.done) {
            button.textContent = button.dataset.done;
            button.disabled = true;
          }
        });
      });
    }
  });
  root.addEventListener("change", function (event) {
    var field = event.target;
    if (field.matches("input[data-act], textarea[data-act], select[data-act]")) send(paramsOf(field));
  });
  root.addEventListener("keydown", function (event) {
    // Enter commits a number/name field (it would fire `change` on blur anyway) and never
    // submits the spell search form, whose GET fallback would leave the page.
    if (event.key !== "Enter") return;
    var field = event.target;
    if (field.matches("input[data-act]")) field.blur();
    else if (field.matches(".world-search input")) event.preventDefault();
  });

  // ---- tabs: plain clicks ------------------------------------------------

  root.addEventListener("click", function (event) {
    var tab = event.target.closest(".cs-tabs button[data-tab]");
    if (tab) showTab(tab.dataset.tab, true);
  });

  // ---- descriptions -----------------------------------------------------------------------

  function describe(url) {
    if (!descriptions[url]) {
      descriptions[url] = fetch(url, { credentials: "same-origin" }).then(function (response) {
        return response.ok ? response.text() : Promise.reject();
      });
    }
    return descriptions[url];
  }

  // Unfold (or fold) the description panel under a row. The catalog text is fetched once into the
  // panel's `.desc-body` (or the panel itself); a row with no URL just shows what is in the page.
  function toggleRow(trigger, row) {
    var panel = row.querySelector(":scope > .desc");
    var target = panel.querySelector(":scope > .desc-body") || panel;
    var url = trigger.dataset.describe;
    var open = panel.hidden;
    if (open && url && !panel.dataset.loaded) {
      target.textContent = "…";
      describe(url)
        .then(function (html) { target.innerHTML = html; panel.dataset.loaded = "1"; })
        .catch(function () { target.textContent = ""; panel.hidden = true; showError(); });
    }
    panel.hidden = !open;
    trigger.setAttribute("aria-expanded", open ? "true" : "false");
  }

  root.addEventListener("click", function (event) {
    var trigger = event.target.closest("[data-describe], [data-toggle]");
    if (!trigger || event.target.closest("[data-act]")) return;
    var url = trigger.dataset.describe;
    var row = trigger.closest("li");

    if (row && row.querySelector(":scope > .desc")) {
      // A row (feature, spell, item): its own panel unfolds under it.
      toggleRow(trigger, row);
      return;
    }

    // A chip or an item card: one shared panel after its group shows whichever was tapped last.
    var group = trigger.closest("[data-panel-group]");
    var panel = group && group.nextElementSibling;
    if (!panel || !panel.classList.contains("chip-panel")) return;
    var same = trigger.classList.contains("active");
    group.querySelectorAll(".active").forEach(function (other) { other.classList.remove("active"); });
    if (same) {
      panel.hidden = true;
      return;
    }
    trigger.classList.add("active");
    panel.hidden = false;
    panel.textContent = "…";
    describe(url)
      .then(function (html) {
        if (!trigger.classList.contains("active")) return;
        panel.innerHTML = html;
        if (trigger.dataset.label) {
          var title = document.createElement("h4");
          title.className = "chip-title";
          title.textContent = trigger.dataset.label;
          panel.insertBefore(title, panel.firstChild);
        }
      })
      .catch(function () { panel.hidden = true; trigger.classList.remove("active"); showError(); });
  });

  // ---- spellbook: casting ability, search, filters -----------------------------------------

  function fold(text) {
    return (text || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  // Filter the rows of a list by the search box and filter buttons of `scope` (an element with
  // `data-filter-list` = the list's id and `data-filter-empty` = its "nothing matches" note's id).
  // A row carries what it is filtered on as `data-<filter name>` (space-separated when it has
  // several values).
  function filterRows(scope) {
    var form = scope.querySelector(".world-search");
    var list = document.getElementById(scope.dataset.filterList);
    if (!form || !list) return;
    var query = fold(form.querySelector("input[name=q]").value.trim());
    var active = {};
    // Pills (radios) pick one value; "All" is the empty one and filters nothing.
    var mode = "";
    form.querySelectorAll(".world-pills input:checked").forEach(function (radio) {
      if (!radio.value) return;
      active[radio.name] = [radio.value];
      mode = radio.value;
    });
    // A filter button marked `data-only` belongs to one pill: it shows once that pill is picked and
    // is cleared when another is.
    form.querySelectorAll(".filter-popover[data-only]").forEach(function (popover) {
      var on = popover.dataset.only.split(" ").indexOf(mode) !== -1;
      popover.hidden = !on;
      if (!on) {
        popover.open = false;
        popover.querySelectorAll("input:checked").forEach(function (box) { box.checked = false; });
      }
    });
    form.querySelectorAll(".filter-popover input:checked").forEach(function (box) {
      (active[box.name] = active[box.name] || []).push(box.value);
    });
    var shown = 0;
    // A descendant selector, not `:scope > li`: the spellbook nests each level's rows one level
    // deeper, in that level's own `<ul>` (under its sticky heading) rather than a single flat one.
    list.querySelectorAll("li").forEach(function (item) {
      var match = !query || fold(item.dataset.search).indexOf(query) !== -1;
      Object.keys(active).forEach(function (name) {
        if (!match) return;
        var have = name === "range" ? [item.dataset.range] : (item.dataset[name] || "").split(" ");
        match = active[name].some(function (value) { return have.indexOf(value) !== -1; });
      });
      item.hidden = !match;
      if (match) shown += 1;
    });
    // A level heading (spellbook) or the Features tab's own "Bookmarks" block whose every row
    // just got hidden goes with them - unless it never had any to begin with (a level with slots
    // but no spells yet), which stays up regardless of the search.
    list.querySelectorAll(".cs-level-group, .bookmark-list").forEach(function (group) {
      var items = group.querySelectorAll("li");
      group.hidden = items.length > 0 && !Array.prototype.some.call(items, function (li) { return !li.hidden; });
    });
    var empty = document.getElementById(scope.dataset.filterEmpty);
    if (empty) empty.hidden = shown > 0;
    // The World's filter buttons show how many boxes are ticked.
    form.querySelectorAll(".filter-popover").forEach(function (popover) {
      var button = popover.querySelector(".filter-button");
      var count = popover.querySelectorAll("input:checked").length;
      var badge = button.querySelector(".filter-count");
      button.classList.toggle("active", count > 0);
      if (count && !badge) {
        badge = document.createElement("span");
        badge.className = "filter-count";
        button.appendChild(badge);
      }
      if (badge) {
        if (count) badge.textContent = count;
        else badge.remove();
      }
    });
  }

  root.addEventListener("input", function (event) {
    var scope = event.target.closest("[data-filter-list]");
    if (scope) filterRows(scope);
  });
  // "Clear filters" (`filter_clear.js`) reset the fields already; the rows follow.
  root.addEventListener("filtersclear", function (event) {
    var scope = event.target.closest("[data-filter-list]");
    if (scope) filterRows(scope);
  });
  root.addEventListener("change", function (event) {
    var scope = event.target.closest("[data-filter-list]");
    if (scope) filterRows(scope);
    var select = event.target.closest("[data-casting-select]");
    if (select) {
      var option = select.selectedOptions[0];
      var box = select.closest("[data-casting]");
      box.querySelector("[data-casting-mod]").textContent = option.dataset.mod;
      box.querySelector("[data-casting-dc]").textContent = option.dataset.dc;
      box.querySelector("[data-casting-atk]").textContent = option.dataset.atk;
    }
  });
  // ---- casting: the Cast button opens a dialog with the casting numbers, the slot to spend and, ----
  // ---- for a ritual, the choice to skip the slot; confirming posts `cast` (the server applies the ----
  // ---- rules - see `play.cast_spell`). Slot pools are read live from the spellbook's own rows. ----

  function castPools(minLevel) {
    var pools = [];
    root.querySelectorAll(".cs-slot-row[data-slot]").forEach(function (row) {
      var group = row.closest("[data-level-group]");
      var level = Number(group ? group.dataset.levelGroup : 0);
      var left = Number(row.querySelector(".left").textContent) || 0;
      if (level >= minLevel && left > 0) {
        pools.push({ key: row.dataset.slot, level: level, left: left, label: row.title });
      }
    });
    return pools;
  }

  function castRefresh(dialog) {
    var ritual = dialog.querySelector("[data-cast-ritual]").checked;
    var slotField = dialog.querySelector("[data-cast-slot-field]");
    var slotSelect = dialog.querySelector("[data-cast-slot]");
    var free = dialog.querySelector("[data-cast-free]").checked;
    var needsSlot = dialog._level > 0 && !ritual && !free;
    slotField.hidden = !needsSlot;
    dialog.querySelector("[data-cast-noslot]").hidden = !(needsSlot && !slotSelect.options.length);
    dialog.querySelector("[data-cast-confirm]").disabled = needsSlot && !slotSelect.options.length;
  }

  // Only a spell that can be cast right now shows its Cast button: a cantrip or a ritual always,
  // any other one while a slot of its level or higher is left (read live, like the dialog).
  function updateCastButtons() {
    root.querySelectorAll(".item-cast").forEach(function (button) {
      var level = Number(button.dataset.castLevel);
      button.hidden = !(level === 0 || button.dataset.castRitual === "1" || button.dataset.castFree === "1" || castPools(level).length);
    });
  }

  function openCast(button) {
    var dialog = document.getElementById("cs-cast-dialog");
    if (!dialog || !dialog.showModal) return;
    var level = Number(button.dataset.castLevel);
    var canSlot = button.dataset.castSlot === "1";
    var isRitual = button.dataset.castRitual === "1";
    dialog._spell = button.dataset.cast;
    dialog._button = button;
    dialog._level = level;
    var name = button.closest("li").querySelector(".item-name");
    dialog.querySelector("[data-cast-title]").textContent = name ? name.textContent.trim() : "";
    // The casting numbers of the spell's own class, worked out by the server.
    ["ability", "mod", "dc", "atk"].forEach(function (key) {
      dialog.querySelector("[data-cast-" + key + "]").textContent = button.dataset["cast" + key.charAt(0).toUpperCase() + key.slice(1)];
    });
    var slotSelect = dialog.querySelector("[data-cast-slot]");
    slotSelect.innerHTML = "";
    if (level > 0 && canSlot) {
      castPools(level).forEach(function (pool) {
        var option = document.createElement("option");
        option.value = pool.key;
        option.textContent = pool.label + " (" + pool.left + ")";
        slotSelect.appendChild(option);
      });
    }
    var ritual = dialog.querySelector("[data-cast-ritual]");
    ritual.checked = level > 0 && isRitual && !canSlot; // only castable as a ritual
    ritual.disabled = !canSlot;
    dialog.querySelector("[data-cast-ritual-field]").hidden = !(level > 0 && isRitual);
    // A free cast (Magic Initiate's spell): offered, and ticked, while its once per long rest is left.
    var canFree = level > 0 && button.dataset.castFree === "1";
    var free = dialog.querySelector("[data-cast-free]");
    free.checked = canFree && !ritual.checked;
    dialog.querySelector("[data-cast-free-field]").hidden = !canFree;
    dialog.querySelector("[data-cast-concentration]").hidden = button.dataset.castConcentration !== "1";
    castRefresh(dialog);
    dialog.showModal();
  }

  root.addEventListener("click", function (event) {
    var button = event.target.closest(".item-cast");
    if (button) {
      event.preventDefault();
      openCast(button);
      return;
    }
    var dialog = event.target.closest("#cs-cast-dialog");
    if (!dialog) return;
    if (event.target.closest("[data-cast-cancel]")) {
      dialog.close();
    } else if (event.target.closest("[data-cast-confirm]")) {
      var ritual = dialog.querySelector("[data-cast-ritual]").checked;
      var free = dialog.querySelector("[data-cast-free]").checked;
      var params = { action: "cast", spell: dialog._spell };
      if (ritual) params.ritual = "1";
      else if (free) params.free = "1";
      else if (dialog._level > 0) params.slot = dialog.querySelector("[data-cast-slot]").value;
      dialog.close();
      var castButton = dialog._button;
      send(params).then(function (accepted) {
        if (accepted && params.free && castButton) {
          castButton.dataset.castFree = "0"; // spent until the next long rest
          updateCastButtons();
        }
      });
    }
  });
  root.addEventListener("change", function (event) {
    var dialog = event.target.closest("#cs-cast-dialog");
    if (!dialog) return;
    // A ritual and a free cast both skip the slot; picking one drops the other.
    var other = event.target.matches("[data-cast-ritual]") ? "[data-cast-free]" : "[data-cast-ritual]";
    if (event.target.checked && event.target.matches("[data-cast-ritual], [data-cast-free]")) {
      dialog.querySelector(other).checked = false;
    }
    if (event.target.matches("[data-cast-ritual], [data-cast-free]")) castRefresh(dialog);
  });

  // ---- rests: the Short/Long Rest tiles open their dialogs; confirming posts the action and the ----
  // ---- server (`play.short_rest`/`play.long_rest`) works out what is restored. -------------------

  root.addEventListener("click", function (event) {
    var tile = event.target.closest("[data-rest]");
    if (tile) {
      var opener = document.getElementById("cs-" + tile.dataset.rest + "-rest-dialog");
      if (opener && opener.showModal) opener.showModal();
      return;
    }
    var dialog = event.target.closest("#cs-short-rest-dialog, #cs-long-rest-dialog");
    if (!dialog) return;
    if (event.target.closest("[data-rest-cancel]")) {
      dialog.close();
    } else if (event.target.closest("[data-rest-confirm]")) {
      var params = { action: event.target.closest("[data-rest-confirm]").dataset.restConfirm + "_rest" };
      dialog.querySelectorAll("[data-rest-die]").forEach(function (input) {
        if (Number(input.value) > 0) params["hd_" + input.dataset.restDie] = input.value;
      });
      dialog.close();
      send(params);
    }
  });

  // A filter popover closes when you tap anywhere else.
  document.addEventListener("click", function (event) {
    if (event.target.closest(".filter-popover")) return;
    root.querySelectorAll(".filter-popover[open]").forEach(function (popover) { popover.open = false; });
  });

  // ---- bookmarks, on any tab with them (Features, Spellbook): the World list's own AJAX swap,
  // ---- list.html, over that tab's own list id instead of #search-results, found generically -
  // ---- `button.form` (its own `form=""` attribute) rather than a hardcoded form id, since every
  // ---- tab sits in the DOM at once (just `hidden`) and so needs its own distinct form id (see
  // ---- `_list_item.html`'s `bookmark_form_id`); the swap target the same way, off the nearest
  // ---- `[data-filter-list]` (its `.cs-sticky` search/filter tools). filterRows() re-runs on the
  // ---- fresh list after, since unlike a full page this tab's search/filter state lives only in
  // ---- the DOM, not the URL, and would otherwise be lost.
  root.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest(".item-bookmark");
    if (!button || !window.fetch) return;
    var form = button.form;
    var tools = button.closest(".cs-panel") && button.closest(".cs-panel").querySelector("[data-filter-list]");
    if (!form || !tools) return;
    event.preventDefault();

    var listId = tools.dataset.filterList;
    var data = new FormData(form);
    data.set("object_id", button.value);
    button.disabled = true;
    fetch(form.action, {
      method: "POST",
      body: data,
      headers: { "X-Requested-With": "XMLHttpRequest" },
    })
      .then(function (response) {
        if (!response.ok) throw new Error("bookmark failed");
        return fetch(window.location.href, { cache: "no-store" });
      })
      .then(function (response) { return response.text(); })
      .then(function (html) {
        var next = new DOMParser().parseFromString(html, "text/html").getElementById(listId);
        var current = document.getElementById(listId);
        if (!next || !current) throw new Error("no list");
        current.replaceWith(next);
        var freshTools = root.querySelector('[data-filter-list="' + listId + '"]');
        if (freshTools) filterRows(freshTools);
      })
      .catch(function () {
        button.disabled = false;
        form.submit();
      });
  });

  // ---- adding items and spells: the overlays -----------------------------------------------

  // The open overlay, if any, is named in `?overlay=item|spell` - not for deep-linking, just so a
  // reload keeps you in it: the overlay is closed by `hidden`, page-local state a language switch
  // (a real page reload, `next` read from `location.search` at submit time) would otherwise lose,
  // dumping the player back on the sheet as if they had backed out of it.
  function markOverlay(key) {
    var url = new URL(window.location.href);
    if (key) url.searchParams.set("overlay", key);
    else url.searchParams.delete("overlay");
    var next = url.pathname + url.search + url.hash;
    if (window.appNav) window.appNav.replaceUrl(next);
    else window.history.replaceState(window.history.state, "", next);
  }

  // A dropdown filter looks "active" (accent border, like the World's own) once anything but its
  // empty first option is picked - it shows the picked option itself, not a count.
  function syncSelect(select) {
    select.classList.toggle("active", !!select.value);
  }

  // The custom item form's Type is a dropdown, same as the Features list's own filters - single
  // choice (an item has one type), built from whichever Category pill is picked (a "Weapons" item
  // isn't offered "Shield" as a type). `custom_types_by_section` ({section: [name, ...]}) came
  // down as JSON. A "weapons" Category also reveals a second dropdown next to it, for
  // Simple/Martial.
  function initCustomTypeOptions(body) {
    var data = body.querySelector("#cs-custom-types-data");
    var sectionGroup = body.querySelector("[data-custom-section]");
    var weaponWrap = body.querySelector("[data-custom-weapon-category]");
    var weaponSelect = weaponWrap && weaponWrap.querySelector("select");
    var typeWrap = body.querySelector("[data-custom-type]");
    var typeSelect = typeWrap && typeWrap.querySelector("select");
    if (!data || !sectionGroup || !typeSelect) return;
    var bySection = JSON.parse(data.textContent);

    // The select's first option is the static empty one (kept in the template); everything after
    // it is rebuilt here. A Category change always resets the pick - a type from the old Category
    // may not even exist in the new one - and shows/hides the weapon category dropdown.
    function rebuild() {
      var section = sectionGroup.querySelector("input:checked");
      Array.prototype.slice.call(typeSelect.options, 1).forEach(function (o) { o.remove(); });
      ((section && bySection[section.value]) || []).forEach(function (name) {
        typeSelect.add(new Option(name, name));
      });
      typeSelect.value = "";
      syncSelect(typeSelect);
      if (weaponSelect) {
        weaponWrap.hidden = !section || section.value !== "weapons";
        weaponSelect.value = "";
        syncSelect(weaponSelect);
      }
    }

    sectionGroup.addEventListener("change", rebuild);
    typeSelect.addEventListener("change", function () { syncSelect(typeSelect); });
    if (weaponSelect) weaponSelect.addEventListener("change", function () { syncSelect(weaponSelect); });
    rebuild();
  }

  // What a custom item costs in copper (unit cost in gp, times quantity), from the form as filled
  // in right now.
  function customCost(form) {
    var cost = Number(form.querySelector('[name="cost"]').value) || 0;
    var quantity = Math.max(1, Math.floor(Number(form.querySelector('[name="quantity"]').value) || 1));
    return Math.round(cost * 100) * quantity;
  }

  // The custom item form's Buy button shows only while a cost is filled in that the purse covers.
  function updateCustomBuy() {
    root.querySelectorAll("[data-custom-form]").forEach(function (form) {
      var buy = form.querySelector("[data-custom-buy]");
      if (!buy) return;
      var cost = customCost(form);
      buy.hidden = cost <= 0 || cost > purseCopper();
    });
  }

  root.addEventListener("input", function (event) {
    if (event.target.closest("[data-custom-form]")) updateCustomBuy();
  });

  // Each overlay (`.cs-overlay`) is fetched from its `data-url` the first time it is opened. The
  // button that opens one names it: `data-add-open="<overlay id>"`.
  function openAdd(overlay) {
    if (!overlay) return;
    overlay.hidden = false;
    markOverlay(overlay.dataset.overlay);
    if (overlay.dataset.loaded) return;
    var body = overlay.querySelector(".cs-overlay-body");
    body.textContent = "…";
    fetch(overlay.dataset.url, { credentials: "same-origin" })
      .then(function (response) { return response.ok ? response.text() : Promise.reject(); })
      .then(function (html) {
        body.innerHTML = html;
        overlay.dataset.loaded = "1";
        var scope = body.querySelector("[data-filter-list]");
        if (scope) filterRows(scope); // hides the filters that wait for a pill to be picked
        updateBuyButtons();
        initCustomTypeOptions(body);
        updateCustomBuy();
      })
      .catch(function () { body.textContent = ""; overlay.hidden = true; showError(); });
  }

  function closeAdd() {
    root.querySelectorAll(".cs-overlay").forEach(function (overlay) { overlay.hidden = true; });
    markOverlay(null);
  }

  function showAddPane(overlay, name) {
    overlay.querySelectorAll("[data-add-pane]").forEach(function (pane) { pane.hidden = pane.dataset.addPane !== name; });
    overlay.querySelectorAll("[data-add-tab]").forEach(function (tab) {
      var on = tab.dataset.addTab === name;
      tab.classList.toggle("active", on);
      tab.setAttribute("aria-selected", on ? "true" : "false");
    });
  }

  root.addEventListener("click", function (event) {
    var open = event.target.closest("[data-add-open]");
    if (open) return openAdd(document.getElementById(open.dataset.addOpen));
    if (event.target.closest("[data-add-close]")) return closeAdd();
    var tab = event.target.closest("[data-add-tab]");
    if (tab) return showAddPane(tab.closest(".cs-overlay"), tab.dataset.addTab);

    var add = event.target.closest("[data-custom-add]");
    if (add) {
      // Not a <form>: a submit would reach navigation.js, which treats every submit as a page change.
      var overlay = add.closest(".cs-overlay");
      var params = { action: "custom_add" };
      var form = add.closest("[data-custom-form]");
      var name = overlay.querySelector('[data-custom-form] [name="name"]');
      overlay.querySelectorAll("[data-custom-form] [name]").forEach(function (field) {
        if (field.type === "checkbox") params[field.name] = field.checked ? "1" : "";
        else if (field.type === "radio") { if (field.checked) params[field.name] = field.value; }
        else params[field.name] = field.value;
      });
      if (!params.name.trim()) {
        name.focus();
        return;
      }
      if (add.hasAttribute("data-custom-buy")) {
        // Same confirmation as the catalog's Buy: the price, and what is left of the purse after.
        var cost = customCost(form);
        var confirmText =
          root.dataset.fmtBuyConfirm.replace("%(price)s", copperLabel(cost)) +
          "\n" +
          root.dataset.fmtBuyLeft.replace("%(left)s", copperLabel(Math.max(0, purseCopper() - cost)));
        params.buy = "1";
      }
      (params.buy ? window.appConfirm(confirmText) : Promise.resolve(true)).then(function (ok) {
        if (!ok) return null;
        return send(params);
      }).then(function (accepted) {
        if (!accepted) return;
        overlay.querySelectorAll("[data-custom-form] [name]").forEach(function (field) {
          if (field.type === "checkbox") field.checked = false;
          else if (field.type === "radio") field.checked = field.defaultChecked;
          else if (field.name === "quantity") field.value = "1";
          else if (field.tagName !== "SELECT") field.value = "";
        });
        updateCustomBuy();
        // Radios reset above, but the Category pill, weapon-category pill and Type popover also
        // carry their own live state (rebuilt options, hidden/shown, the popover's badge) - a
        // "change" event redoes that too.
        overlay.querySelectorAll('[data-custom-form] input[type="radio"]:checked').forEach(function (field) {
          field.dispatchEvent(new Event("change", { bubbles: true }));
        });
      });
    }
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeAdd();
  });

  // ---- the portrait ------------------------------------------------------------------------

  // Post the chosen picture (or a removal) to the portrait endpoint, one request at a time like
  // every other change, then redraw the header.
  function sendPortrait(body, url) {
    var job = queue.then(function () {
      return fetch(url || root.dataset.portraitUrl, {
        method: "POST",
        body: body,
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest" },
      })
        .then(function (response) {
          return response.json().then(function (json) { return { ok: response.ok, json: json }; });
        })
        .then(function (result) {
          if (!result.ok) return showError(result.json.error);
          return refresh();
        })
        .catch(function () { showError(); });
    });
    queue = job;
    return job;
  }

  root.addEventListener("change", function (event) {
    var input = event.target.closest("[data-portrait-file]");
    if (!input || !input.files.length) return;
    var body = new FormData();
    body.append("file", input.files[0]);
    input.value = ""; // choosing the same file again must fire `change` again
    sendPortrait(body);
  });
  // The gallery: every chosen file is its own request (a failed one shows its error and the
  // rest still go), each removal names the picture's id.
  root.addEventListener("change", function (event) {
    var input = event.target.closest("[data-gallery-file]");
    if (!input || !input.files.length) return;
    var files = Array.prototype.slice.call(input.files);
    input.value = "";
    files.forEach(function (file) {
      var body = new FormData();
      body.append("file", file);
      sendPortrait(body, root.dataset.galleryUrl);
    });
  });
  // The gallery viewer: tapping a thumbnail opens every picture full screen, swiped sideways (a CSS
  // scroll-snap track, so the browser does the gestures), with arrow keys / buttons on a desktop.
  // The owner can remove the picture on screen. Built on <body> so a sheet refresh never removes it.
  var SVG_NS = '<svg viewBox="0 0 24 24" aria-hidden="true">';
  var ICON_X = SVG_NS + '<path d="M6 6l12 12M18 6L6 18"/></svg>';
  var ICON_TRASH = SVG_NS + '<path d="M4 7h16"/><path d="M6 7l1 13a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-13"/><path d="M9 7V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3"/></svg>';
  var ICON_PREV = SVG_NS + '<path d="M15 5l-7 7 7 7"/></svg>';
  var ICON_NEXT = SVG_NS + '<path d="M9 5l7 7-7 7"/></svg>';
  var viewer = null;

  function closeViewer() {
    if (!viewer) return;
    document.removeEventListener("keydown", viewer.onKey);
    viewer.el.remove();
    viewer = null;
  }

  function openViewer(items, start, canRemove) {
    closeViewer();
    var el = document.createElement("div");
    el.className = "cs-viewer";
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-modal", "true");
    el.innerHTML =
      '<div class="cs-viewer-bar"><span data-count></span><span style="flex:1"></span>' +
      (canRemove ? '<button type="button" data-remove aria-label="' + (root.dataset.removeLabel || "Remove") + '">' + ICON_TRASH + "</button>" : "") +
      '<button type="button" data-close aria-label="' + (root.dataset.closeLabel || "Close") + '">' + ICON_X + "</button></div>" +
      '<div class="cs-viewer-track"></div>' +
      '<button type="button" class="cs-viewer-nav prev" data-step="-1" aria-hidden="true" tabindex="-1">' + ICON_PREV + "</button>" +
      '<button type="button" class="cs-viewer-nav next" data-step="1" aria-hidden="true" tabindex="-1">' + ICON_NEXT + "</button>";
    var track = el.querySelector(".cs-viewer-track");
    var count = el.querySelector("[data-count]");
    items.forEach(function (item) {
      var slide = document.createElement("div");
      slide.className = "cs-viewer-slide";
      var img = document.createElement("img");
      img.src = item.src;
      img.alt = "";
      slide.appendChild(img);
      track.appendChild(slide);
    });
    function index() { return Math.round(track.scrollLeft / (track.clientWidth || 1)); }
    function show() { count.textContent = index() + 1 + " / " + items.length; }
    function go(i) {
      i = Math.max(0, Math.min(items.length - 1, i));
      track.scrollTo({ left: i * track.clientWidth, behavior: "smooth" });
    }
    track.addEventListener("scroll", show);
    el.addEventListener("click", function (event) {
      var target = event.target;
      if (target.closest("[data-close]") || target.classList.contains("cs-viewer-slide")) return closeViewer();
      var step = target.closest("[data-step]");
      if (step) return go(index() + parseInt(step.dataset.step, 10));
      if (target.closest("[data-remove]")) {
        var id = items[index()].id;
        var ask = root.dataset.removeConfirm;
        (ask ? window.appConfirm(ask) : Promise.resolve(true)).then(function (ok) {
          if (!ok) return;
          closeViewer();
          var body = new FormData();
          body.append("remove", id);
          sendPortrait(body, root.dataset.galleryUrl);
        });
      }
    });
    function onKey(event) {
      if (event.key === "Escape") closeViewer();
      else if (event.key === "ArrowLeft") go(index() - 1);
      else if (event.key === "ArrowRight") go(index() + 1);
    }
    document.addEventListener("keydown", onKey);
    document.body.appendChild(el);
    viewer = { el: el, onKey: onKey };
    track.scrollLeft = start * track.clientWidth; // jump, no animation
    show();
    el.querySelector("[data-close]").focus();
  }

  root.addEventListener("click", function (event) {
    var thumb = event.target.closest("[data-gallery-open]");
    if (!thumb) return;
    var strip = thumb.closest("[data-gallery-strip]");
    var thumbs = Array.prototype.slice.call(strip.querySelectorAll("[data-gallery-open]"));
    openViewer(
      thumbs.map(function (t) { return { id: t.dataset.galleryOpen, src: t.dataset.src }; }),
      thumbs.indexOf(thumb),
      !!strip.dataset.canRemove
    );
  });
  root.addEventListener("click", function (event) {
    var remove = event.target.closest("[data-portrait-remove]");
    if (!remove) return;
    (remove.dataset.confirm ? window.appConfirm(remove.dataset.confirm) : Promise.resolve(true)).then(function (ok) {
      if (!ok) return;
      var body = new FormData();
      body.append("remove", "1");
      sendPortrait(body);
    });
  });

  // ---- (re)applied after the sheet is swapped ---------------------------------------------

  function setup() {
    var current = root.querySelector(".cs-tabs button.active");
    if (current) centreTab(current);
  }

  setup();

  // Reopen an overlay a language switch (or any other reload) interrupted - see `markOverlay`.
  var overlayParam = new URLSearchParams(window.location.search).get("overlay");
  root.querySelectorAll(".cs-overlay").forEach(function (overlay) {
    if (overlay.dataset.overlay === overlayParam) openAdd(overlay);
  });
})();
