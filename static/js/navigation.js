/*
 * In-app navigation: one history stack per bottom-nav menu (Characters / Handbook / Logbook / World).
 *
 * The pages are server-rendered, so the browser's own history is a single linear list that
 * knows nothing about menus. That is wrong for this app in three ways this file fixes:
 *
 *  1. "Back" (the header arrow *and* the phone's back button) must go one step back inside the
 *     menu you are in - never into another menu you visited on the way, and never out of the
 *     menu's root. At the root nothing happens.
 *  2. Tab switches (World's category tabs, a detail page's `?tab=`), the language switch and
 *     live search are not steps: they replace the current entry instead of adding one.
 *  3. Switching language must keep you on the same page, tab and scroll position.
 *
 * How:
 *  - The per-menu stacks live in sessionStorage (per window, so a PWA window and a browser tab
 *    don't share them). Each entry is `{u: "/path?query", p: parent url, y: scroll offset}`.
 *  - A page load is classified by a "pending" intent stored just before the navigation, by a
 *    link click or form submit (`data-nav="replace"|"pop"`, `data-menu`, default "push").
 *  - Tapping the bottom-nav item of the menu you are already in returns to that menu's root.
 *  - The active menu only changes through the bottom nav (or a cold entry by URL). So a link
 *    from the Handbook's Rules Glossary into `/world/rules/...` stays inside the Handbook's
 *    stack and back returns to the Glossary.
 *  - The phone's back button is a browser history traversal the page cannot cancel, so every
 *    page keeps a two-entry guard of its own: [base, top]. Back from `top` lands on `base` in
 *    the *same* document and fires `popstate`, which runs the very function the header arrow
 *    runs. At a menu's root the guard is simply re-entered (`history.go(1)`).
 *  - Should a back traversal ever reach a different document anyway (the browser skips
 *    script-added entries for a page with no user interaction yet), `arrive()` recognises it
 *    by the navigation type and applies the same rule to it.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "dnd.navigation.v1";
  var MENUS = ["characters", "handbook", "logbook", "world"];
  // Pages that are a detour from wherever they were opened, not a place of their own: leaving
  // the menu for another one must not park the account form on top of that menu's stack.
  var TRANSIENT_PATHS = ["/account/"];
  var MAX_DEPTH = 50;
  var PENDING_TTL_MS = 15000;

  // --- state --------------------------------------------------------------------------------

  function freshState() {
    return { active: null, pending: null, stacks: { characters: [], handbook: [], logbook: [], world: [] } };
  }

  function read() {
    try {
      var state = JSON.parse(window.sessionStorage.getItem(STORAGE_KEY));
      if (state && state.stacks) {
        MENUS.forEach(function (menu) {
          if (!Array.isArray(state.stacks[menu])) state.stacks[menu] = [];
        });
        return state;
      }
    } catch (error) {
      // Storage blocked/corrupt: behave as a first visit (the per-page parent link still works).
    }
    return freshState();
  }

  function write(state) {
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (error) {
      // Nothing to do - see read().
    }
  }

  function menuOf(path) {
    for (var i = 0; i < MENUS.length; i++) {
      if (path.indexOf("/" + MENUS[i] + "/") === 0) return MENUS[i];
    }
    return null;
  }

  function currentUrl() {
    return location.pathname + location.search;
  }

  function isTransient(url) {
    return TRANSIENT_PATHS.some(function (path) {
      return url.split("?")[0] === path;
    });
  }

  function top(stack) {
    return stack.length ? stack[stack.length - 1] : null;
  }

  function dropTransients(stack) {
    while (stack.length && isTransient(top(stack).u)) stack.pop();
  }

  function urlOf(href) {
    try {
      var url = new URL(href, location.href);
      return url.origin === location.origin ? url.pathname + url.search : null;
    } catch (error) {
      return null;
    }
  }

  // The header arrow's own `href` is this page's static parent (set by the view).
  function parentUrl() {
    var arrow = document.getElementById("back-btn");
    return arrow ? urlOf(arrow.getAttribute("href")) : null;
  }

  // --- scroll -------------------------------------------------------------------------------

  // Lists and detail pages scroll inside their own box, not the window.
  function scroller() {
    return document.querySelector(".list-scroll, .detail-body");
  }

  function saveScroll(state) {
    var stack = state.active && state.stacks[state.active];
    var entry = stack && top(stack);
    if (!entry || entry.u !== currentUrl()) return; // e.g. the entry was already popped
    var box = scroller();
    entry.y = box ? Math.round(box.scrollTop) : 0;
  }

  function restoreScroll(entry) {
    if (!entry || !entry.y || location.hash) return; // a #fragment scrolls itself
    function apply() {
      var box = scroller();
      if (box) box.scrollTop = entry.y;
    }
    apply();
    window.addEventListener("load", apply, { once: true });
  }

  // --- the stack ----------------------------------------------------------------------------

  // One step back within `stack`, or null at the root. With a single entry left the page's own
  // static parent is the way out (a deep link, or a fresh session): that page becomes the root.
  function planBack(stack) {
    if (stack.length > 1) return { url: stack[stack.length - 2].u, pop: true };
    var entry = top(stack);
    if (entry && entry.p && entry.p !== entry.u) return { url: entry.p, pop: false };
    return null;
  }

  function commitBack(stack, plan) {
    if (plan.pop) stack.pop();
    else stack[stack.length - 1] = { u: plan.url };
  }

  function goBack(viaHistory) {
    var state = read();
    saveScroll(state);
    var stack = state.active && state.stacks[state.active];
    var plan = stack && stack.length ? planBack(stack) : null;
    if (!plan) {
      write(state);
      // The phone's back button already moved us onto the guard's `base` entry - step forward
      // onto `top` again, so the page (and the guard) stay exactly as they were.
      if (viaHistory) window.history.go(1);
      return;
    }
    commitBack(stack, plan);
    write(state);
    location.replace(plan.url);
  }

  // Runs on every page load and on a bfcache restore: files this page into the stacks. Returns
  // false when it has sent the browser elsewhere instead (this page is not the one to show).
  function arrive(navType) {
    var state = read();
    var url = currentUrl();
    var pending = state.pending;
    state.pending = null;
    if (pending && Date.now() - pending.t > PENDING_TTL_MS) pending = null;

    // Arrived by a history traversal we did not start: a back press that got past the guard.
    // Treat it as "one step back" from where the user was, whatever page the browser picked.
    if (navType === "back_forward" && state.active) {
      var current = state.stacks[state.active];
      var here = top(current);
      if (here && here.u !== url) {
        var plan = planBack(current);
        if (plan) commitBack(current, plan);
        write(state);
        var wanted = plan ? plan.url : here.u; // no plan = at the root: stay where we were
        if (wanted !== url) {
          location.replace(wanted);
          return false;
        }
      }
    }

    // Which menu are we in? Only a bottom-nav tap (`pending.menu`) or a cold entry by URL
    // changes it - an ordinary link, even one into another menu's URL space, stays put.
    var active;
    var activeTop = state.active ? top(state.stacks[state.active] || []) : null;
    if (pending && pending.menu) {
      active = pending.menu;
    } else if (pending) {
      active = state.active || menuOf(location.pathname) || "characters";
    } else if (state.active && (navType === "reload" || (activeTop && activeTop.u === url))) {
      active = state.active; // a reload of the page we are on
    } else {
      active = menuOf(location.pathname) || state.active || "characters";
    }

    if (pending && pending.from && state.stacks[pending.from]) {
      if (pending.mode === "switch" || pending.mode === "pop") {
        dropTransients(state.stacks[pending.from]);
      }
    }

    var stack = state.stacks[active];
    if (pending && pending.mode === "root") stack.length = 0; // back to the menu's root
    var entry = top(stack);
    if (pending && pending.mode === "replace" && entry) {
      // Same URL (a language switch): keep the entry, and with it the scroll position.
      if (entry.u !== url) stack[stack.length - 1] = { u: url };
    } else if (!entry || entry.u !== url) {
      stack.push({ u: url });
    }
    entry = top(stack);
    var parent = parentUrl();
    if (parent) entry.p = parent;
    else delete entry.p;
    if (stack.length > MAX_DEPTH) stack.splice(0, stack.length - MAX_DEPTH);

    state.active = active;
    write(state);
    highlightMenu(active);
    restoreScroll(entry);
    return true;
  }

  function highlightMenu(active) {
    Array.prototype.forEach.call(document.querySelectorAll(".bottom-nav-item[data-menu]"), function (item) {
      item.classList.toggle("active", item.dataset.menu === active);
    });
  }

  function setPending(mode, extra) {
    var state = read();
    state.pending = { mode: mode, from: state.active, t: Date.now() };
    if (extra && extra.menu) state.pending.menu = extra.menu;
    write(state);
  }

  // --- history guard (the phone's back button) ------------------------------------------------

  function ensureGuard() {
    var marker = window.history.state;
    if (marker && marker.nav === "top") return; // reload / return to a page already guarded
    if (!marker || marker.nav !== "base") {
      window.history.replaceState({ nav: "base" }, "");
    }
    window.history.pushState({ nav: "top" }, "");
  }

  window.addEventListener("popstate", function (event) {
    if (event.state && event.state.nav === "base") goBack(true);
  });

  // --- user actions ---------------------------------------------------------------------------

  function plainClick(event) {
    return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
  }

  document.addEventListener(
    "click",
    function (event) {
      var link = event.target.closest && event.target.closest("a[href]");
      if (!link || event.defaultPrevented || !plainClick(event)) return;
      if ((link.target && link.target !== "_self") || link.hasAttribute("download")) return;
      var dest = urlOf(link.href);
      if (dest === null) return;

      var hash = new URL(link.href, location.href).hash;
      if (hash && dest === currentUrl()) {
        // A jump within this page (e.g. a class level's feature link): scroll there without
        // adding a browser history entry the back button would then have to undo first.
        var id = hash.slice(1);
        try {
          id = decodeURIComponent(id);
        } catch (error) {
          // keep the raw text
        }
        var target = document.getElementById(id);
        event.preventDefault();
        if (target) target.scrollIntoView();
        window.history.replaceState(window.history.state, "", hash);
        return;
      }

      if (link.dataset.menu) {
        var state = read();
        var menu = link.dataset.menu;
        event.preventDefault();
        if (state.active === menu) {
          // Tapping the menu you are already in returns to its root page (World: the first tab),
          // dropping whatever was drilled into.
          var root = urlOf(link.dataset.root) || dest;
          var own = state.stacks[menu];
          if (root === currentUrl() && own.length <= 1) return; // already there
          setPending("root", { menu: menu });
          location.assign(root);
          return;
        }
        var stack = state.stacks[menu].slice();
        dropTransients(stack);
        // Resume where this menu was left; the link's own href (the server's last page for it,
        // or its landing page) only when this session has nothing for it yet.
        setPending("switch", { menu: menu });
        location.assign(top(stack) ? top(stack).u : dest);
        return;
      }
      setPending(link.dataset.nav || "push");
    },
    true
  );

  document.addEventListener(
    "submit",
    function (event) {
      var form = event.target;
      if (!form || !form.dataset) return;
      if (form.classList.contains("lang-switcher")) {
        // Come back to exactly this page - tab, search text, filters, fragment - in the new
        // language. Read now: live search changes the URL without a reload.
        var next = form.querySelector("input[name=next]");
        if (next) next.value = location.pathname + location.search + location.hash;
      }
      setPending(form.dataset.nav || "push", { menu: form.dataset.navMenu });
    },
    true
  );

  var arrow = document.getElementById("back-btn");
  if (arrow) {
    arrow.addEventListener("click", function (event) {
      if (!plainClick(event)) return;
      event.preventDefault();
      goBack(false);
    });
  }

  function persistScroll() {
    var state = read();
    saveScroll(state);
    write(state);
  }
  window.addEventListener("pagehide", persistScroll);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") persistScroll();
  });

  window.addEventListener("pageshow", function (event) {
    if (event.persisted) arrive("back_forward"); // restored from the back/forward cache
  });

  // Live search rewrites the URL without a reload: keep the guard's history state and this
  // page's stack entry pointing at it.
  window.appNav = {
    replaceUrl: function (url) {
      var next = urlOf(url);
      window.history.replaceState(window.history.state, "", url);
      if (next === null) return;
      var state = read();
      var stack = state.active && state.stacks[state.active];
      var entry = stack && top(stack);
      if (entry) {
        entry.u = next;
        write(state);
      }
    },
    back: function () {
      goBack(false);
    },
  };

  if ("scrollRestoration" in window.history) window.history.scrollRestoration = "manual";

  var navEntry = window.performance && performance.getEntriesByType
    ? performance.getEntriesByType("navigation")[0]
    : null;
  if (arrive(navEntry ? navEntry.type : "navigate")) ensureGuard();
})();
