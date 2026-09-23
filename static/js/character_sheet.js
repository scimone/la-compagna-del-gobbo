/*
 * The character sheet (templates/frontend/characters/detail.html).
 *
 *  - tabs: every panel is already in the page; a tab only shows one and rewrites `?tab=` so a
 *    reload or a language switch comes back to it.
 *  - actions: anything with `data-act` posts to the sheet's endpoint (`data-act-url` on #cs) - a
 *    button on click, an input/textarea/select when it changes. The extra `data-*` attributes are
 *    the parameters. The server answers with the state to redraw; `refresh: true` means something
 *    derived changed (AC, attacks), so the whole sheet is re-fetched and swapped instead.
 *  - descriptions: `data-describe="<url>"` rows unfold a description under themselves (`data-toggle`
 *    rows just unfold what is already there); chips
 *    (inside `data-panel-group`) show it in the panel that follows their group.
 *  - the spellbook's search and filter buttons filter the rows on the spot; so do those of the
 *    "add an item" and "add a spell" overlays, which are fetched the first time they are opened.
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
    // Rows the player has unfolded (an item whose quantity they are editing) stay unfolded.
    var open = Array.prototype.map.call(
      root.querySelectorAll("#cs-swap li[data-key] > .desc:not([hidden])"),
      function (desc) { return desc.parentElement.dataset.key; }
    );
    return fetch(window.location.href, { credentials: "same-origin" })
      .then(function (response) { return response.text(); })
      .then(function (html) {
        var fresh = new DOMParser().parseFromString(html, "text/html").getElementById("cs-swap");
        var current = document.getElementById("cs-swap");
        if (!fresh || !current) return;
        current.innerHTML = fresh.innerHTML;
        setup();
        open.forEach(function (key) {
          var row = root.querySelector(
            '#cs-swap li[data-key="' + key + '"] > .cs-line > .cs-row, #cs-swap li[data-key="' + key + '"] > .cs-row'
          );
          if (row) toggleRow(row, row.closest("li"));
        });
        area = scroller();
        if (area) area.scrollTop = scroll;
      })
      .catch(function () { showError(); });
  }

  root.addEventListener("click", function (event) {
    var button = event.target.closest("button[data-act]");
    if (button && !button.disabled) {
      event.preventDefault();
      if (button.dataset.buy) {
        // The price and what is left afterwards, both worked out from the purse as it stands right
        // now (this sheet is fetched once and never refreshed, so a static confirmation could go
        // stale after an earlier buy).
        var cost = Number(button.dataset.cost) || 0;
        var confirmText =
          root.dataset.fmtBuyConfirm.replace("%(price)s", copperLabel(cost)) +
          "\n" +
          root.dataset.fmtBuyLeft.replace("%(left)s", copperLabel(Math.max(0, purseCopper() - cost)));
        if (!window.confirm(confirmText)) return;
      } else if (button.dataset.confirm && !window.confirm(button.dataset.confirm)) {
        return;
      }
      send(paramsOf(button)).then(function (accepted) {
        if (accepted && button.dataset.done) {
          button.textContent = button.dataset.done;
          button.disabled = true;
        }
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
    var buttons = form.querySelector(".world-filter-buttons");
    form.querySelectorAll(".filter-popover[data-only]").forEach(function (popover) {
      var on = popover.dataset.only.split(" ").indexOf(mode) !== -1;
      popover.hidden = !on;
      if (!on) {
        popover.open = false;
        popover.querySelectorAll("input:checked").forEach(function (box) { box.checked = false; });
      }
    });
    if (buttons) buttons.hidden = !buttons.querySelector(".filter-popover:not([hidden])");
    form.querySelectorAll(".filter-popover input:checked").forEach(function (box) {
      (active[box.name] = active[box.name] || []).push(box.value);
    });
    var shown = 0;
    list.querySelectorAll(":scope > li").forEach(function (item) {
      var match = !query || fold(item.dataset.search).indexOf(query) !== -1;
      Object.keys(active).forEach(function (name) {
        if (!match) return;
        var have = name === "range" ? [item.dataset.range] : (item.dataset[name] || "").split(" ");
        match = active[name].some(function (value) { return have.indexOf(value) !== -1; });
      });
      item.hidden = !match;
      if (match) shown += 1;
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
  // A filter popover closes when you tap anywhere else.
  document.addEventListener("click", function (event) {
    if (event.target.closest(".filter-popover")) return;
    root.querySelectorAll(".filter-popover[open]").forEach(function (popover) { popover.open = false; });
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

  // A filter-popover button shows "active" (with a count badge of 1) once anything but its own
  // empty/"Any"/"None" option is picked - shared by the custom item form's Type and (for weapons)
  // Weapon category popovers below.
  function syncPopoverButton(panel, button) {
    var on = !!panel.querySelector("input:checked[value]:not([value=''])");
    button.classList.toggle("active", on);
    var badge = button.querySelector(".filter-count");
    if (on) {
      if (!badge) {
        badge = document.createElement("span");
        badge.className = "filter-count";
        button.appendChild(badge);
      }
      badge.textContent = 1;
    } else if (badge) {
      badge.remove();
    }
  }

  // Both popovers below live in `.cs-form`, which scrolls - a plain CSS dropdown
  // (`position: absolute`) would be clipped the moment that scrolls it even slightly out of view
  // (as every other filter avoids by living in the fixed part instead; these can't, sitting right
  // under Name). Escape that by switching the open panel to `position: fixed`, placed under its
  // button by hand, and closing it if the form scrolls out from under it rather than let it drift.
  function escapeScrollClip(popover, panel, button) {
    var scroller = popover.closest(".cs-scroll");
    popover.addEventListener("toggle", function () {
      if (!popover.open) return;
      var rect = button.getBoundingClientRect();
      panel.style.position = "fixed";
      panel.style.top = rect.bottom + 4 + "px";
      panel.style.left = rect.left + "px";
    });
    if (scroller) {
      scroller.addEventListener("scroll", function () {
        if (popover.open) popover.open = false;
      });
    }
  }

  // The custom item form's Type is a filter-popover of radio options, same as the catalog's own
  // Type filter right next to it - just single-select (an item has one type) and built from
  // whichever Category pill is picked (a "Weapons" item isn't offered "Shield" as a type).
  // `custom_types_by_section` ({section: [name, ...]}) came down as JSON. A "weapons" Category
  // also reveals a second popover next to it, for Simple/Martial.
  function initCustomTypeOptions(body) {
    var data = body.querySelector("#cs-custom-types-data");
    var sectionGroup = body.querySelector("[data-custom-section]");
    var weaponPopover = body.querySelector("[data-custom-weapon-category]");
    var weaponPanel = weaponPopover && weaponPopover.querySelector(".filter-popover-panel");
    var weaponButton = weaponPopover && weaponPopover.querySelector(".filter-button");
    var popover = body.querySelector("[data-custom-type]");
    var panel = popover && popover.querySelector("[data-custom-type-panel]");
    var button = popover && popover.querySelector(".filter-button");
    if (!data || !sectionGroup || !popover || !panel || !button) return;
    var bySection = JSON.parse(data.textContent);

    // The panel's first option is the static "None" radio (kept in the template); everything
    // after it is rebuilt here. A Category change always resets the pick back to "None" - a type
    // from the old Category may not even exist in the new one - and shows/hides the weapon
    // category popover (its own pick resets the same way, back to "Any").
    function rebuild() {
      var section = sectionGroup.querySelector("input:checked");
      var onWeapons = !!section && section.value === "weapons";
      Array.prototype.slice.call(panel.children, 1).forEach(function (el) { el.remove(); });
      ((section && bySection[section.value]) || []).forEach(function (name) {
        var option = document.createElement("label");
        option.className = "filter-option";
        var input = document.createElement("input");
        input.type = "radio";
        input.name = "type";
        input.value = name;
        option.appendChild(input);
        option.appendChild(document.createTextNode(" " + name));
        panel.appendChild(option);
      });
      panel.children[0].querySelector("input").checked = true;
      syncPopoverButton(panel, button);
      if (weaponPopover) {
        weaponPopover.hidden = !onWeapons;
        weaponPanel.children[0].querySelector("input").checked = true; // back to "Any"
        syncPopoverButton(weaponPanel, weaponButton);
      }
    }

    escapeScrollClip(popover, panel, button);
    if (weaponPopover) {
      escapeScrollClip(weaponPopover, weaponPanel, weaponButton);
      weaponPanel.addEventListener("change", function () {
        syncPopoverButton(weaponPanel, weaponButton);
      });
    }
    sectionGroup.addEventListener("change", rebuild);
    panel.addEventListener("change", function () { syncPopoverButton(panel, button); });
    rebuild();
  }

  // Each overlay (`.cs-overlay`) is fetched from its `data-url` the first time it is opened. The
  // button that opens one names it: `data-add-open="<overlay id>"`.
  function openAdd(overlay) {
    if (!overlay) return;
    overlay.hidden = false;
    markOverlay(overlay.id === "cs-add" ? "item" : "spell");
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
      send(params).then(function (accepted) {
        if (!accepted) return;
        overlay.querySelectorAll("[data-custom-form] [name]").forEach(function (field) {
          if (field.type === "checkbox") field.checked = false;
          else if (field.type === "radio") field.checked = field.defaultChecked;
          else if (field.name === "quantity") field.value = "1";
          else if (field.tagName !== "SELECT") field.value = "";
        });
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
  function sendPortrait(body) {
    var job = queue.then(function () {
      return fetch(root.dataset.portraitUrl, {
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
  root.addEventListener("click", function (event) {
    var remove = event.target.closest("[data-portrait-remove]");
    if (!remove) return;
    if (remove.dataset.confirm && !window.confirm(remove.dataset.confirm)) return;
    var body = new FormData();
    body.append("remove", "1");
    sendPortrait(body);
  });

  // ---- (re)applied after the sheet is swapped ---------------------------------------------

  function setup() {
    var current = root.querySelector(".cs-tabs button.active");
    if (current) centreTab(current);
  }

  setup();

  // Reopen an overlay a language switch (or any other reload) interrupted - see `markOverlay`.
  var overlayParam = new URLSearchParams(window.location.search).get("overlay");
  if (overlayParam === "item") openAdd(document.getElementById("cs-add"));
  else if (overlayParam === "spell") openAdd(document.getElementById("cs-add-spell"));
})();
