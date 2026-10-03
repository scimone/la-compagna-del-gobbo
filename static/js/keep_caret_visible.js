/* While typing on a phone the keyboard covers the lower part of the page: scroll so the caret of
 * the field being edited (a <textarea>, an <input> or a contenteditable) stays above it - and
 * above the logbook editor's toolbar, which floats on top of the keyboard. */
(function () {
  "use strict";
  var vv = window.visualViewport;
  var MIRRORED = ["boxSizing", "width", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
    "borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth", "fontFamily",
    "fontSize", "fontWeight", "fontStyle", "letterSpacing", "lineHeight", "textTransform",
    "textIndent", "tabSize", "wordSpacing"];

  function editable(el) {
    if (!el) return null;
    if (el.tagName === "TEXTAREA") return el;
    if (el.tagName === "INPUT" && /^(text|search|url|email|tel|password|number)?$/.test(el.type)) return el;
    return el.isContentEditable ? el : null;
  }

  // Viewport-relative top/bottom of the caret line.
  function caretBox(el) {
    var box = el.getBoundingClientRect();
    if (el.tagName === "INPUT") return { top: box.top, bottom: box.bottom };
    if (el.tagName === "TEXTAREA") {
      var style = getComputedStyle(el);
      var mirror = document.createElement("div");
      MIRRORED.forEach(function (name) { mirror.style[name] = style[name]; });
      mirror.style.position = "absolute";
      mirror.style.visibility = "hidden";
      mirror.style.top = "0";
      mirror.style.left = "-9999px";
      mirror.style.whiteSpace = "pre-wrap";
      mirror.style.overflowWrap = "break-word";
      mirror.textContent = el.value.slice(0, el.selectionEnd);
      var marker = document.createElement("span");
      marker.textContent = "​";
      mirror.appendChild(marker);
      document.body.appendChild(mirror);
      var line = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.4;
      var y = marker.offsetTop;
      document.body.removeChild(mirror);
      var top = box.top + y - el.scrollTop;
      return { top: top, bottom: top + line };
    }
    var selection = window.getSelection();
    if (!selection || !selection.rangeCount || !el.contains(selection.anchorNode)) return null;
    var range = selection.getRangeAt(0).cloneRange();
    range.collapse(false);
    var rect = range.getClientRects()[0] || range.getBoundingClientRect();
    if (rect && (rect.height || rect.top)) return { top: rect.top, bottom: rect.bottom };
    var node = selection.anchorNode;
    var parent = node.nodeType === 1 ? node : node.parentNode;
    var r = parent.getBoundingClientRect();
    return { top: r.top, bottom: r.bottom };
  }

  // The nearest ancestor that scrolls on its own (the character sheet scrolls inside `.cs-scroll`,
  // not the window), or null for the page itself.
  function scroller(el) {
    for (var node = el.parentElement; node && node !== document.body; node = node.parentElement) {
      var overflow = getComputedStyle(node).overflowY;
      if ((overflow === "auto" || overflow === "scroll") && node.scrollHeight > node.clientHeight) return node;
    }
    return null;
  }

  function reveal() {
    var el = editable(document.activeElement);
    if (!el || !vv) return;
    var caret = caretBox(el);
    if (!caret) return;
    var bar = document.querySelector(".rte-bar.floating");
    var margin = 16;
    var top = vv.offsetTop + margin;
    var bottom = vv.offsetTop + vv.height - (bar ? bar.offsetHeight : 0) - margin;
    var inner = scroller(el);
    if (inner) { // also stay within the scrolling box, which may end above the keyboard
      var rect = inner.getBoundingClientRect();
      top = Math.max(top, rect.top + margin);
      bottom = Math.min(bottom, rect.bottom - margin);
    }
    var delta = 0;
    if (caret.bottom > bottom) delta = caret.bottom - bottom;
    else if (caret.top < top) delta = caret.top - top;
    if (Math.abs(delta) > 1) (inner || window).scrollBy(0, delta);
  }

  var timer = null;
  function soon() {
    clearTimeout(timer);
    timer = setTimeout(reveal, 60);
  }

  document.addEventListener("input", soon);
  document.addEventListener("keyup", soon);
  document.addEventListener("selectionchange", soon);
  document.addEventListener("focusin", function () { setTimeout(reveal, 300); });
  if (vv) vv.addEventListener("resize", soon);
})();
