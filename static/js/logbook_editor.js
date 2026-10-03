/*
 * The Logbook's rich-text editor (templates/frontend/logbook/form.html).
 *
 * A contenteditable box with a small toolbar (bold, italic, heading, bullet and numbered list,
 * quote). What is stored is the Markdown subset of `apps/frontend/logbook_markup.py`: this script
 * turns the box's HTML into it on every change and writes it into the form's plain <textarea>
 * (hidden while the visual editor runs, so without JS that textarea - Markdown - is still usable).
 * The "Md" button switches to writing that Markdown by hand; switching back asks the server to
 * render it (`data-preview-url`). The toolbar floats above the phone's keyboard while editing.
 */
(function () {
  var box = document.querySelector("[data-rte]");
  if (!box) return;
  var body = box.querySelector(".rte-body");
  var textarea = box.parentNode.querySelector("textarea");
  if (!body || !textarea) return;

  var BLOCKS = { P: 1, DIV: 1, H1: 1, H2: 1, H3: 1, H4: 1, UL: 1, OL: 1, LI: 1, BLOCKQUOTE: 1 };

  function escapeText(text) {
    return text.replace(/[\\*\[]/g, "\\$&");
  }

  // `**bold**` needs its spaces outside the markers, or it does not render as bold.
  function wrap(marker, inner) {
    var m = /^(\s*)([\s\S]*?)(\s*)$/.exec(inner);
    return m[2] ? m[1] + marker + m[2] + marker + m[3] : inner;
  }

  function inline(node) {
    var out = "";
    Array.prototype.forEach.call(node.childNodes, function (child) {
      if (child.nodeType === 3) {
        out += escapeText(child.nodeValue.replace(/ /g, " "));
      } else if (child.nodeType === 1) {
        var tag = child.tagName;
        if (tag === "BR") out += "\n";
        else if (tag === "B" || tag === "STRONG") out += wrap("**", inline(child));
        else if (tag === "I" || tag === "EM") out += wrap("*", inline(child));
        else if (tag === "A") {
          var href = child.getAttribute("href") || "";
          var label = inline(child);
          out += href && label.trim() ? "[" + label + "](" + href.replace(/\s/g, "%20") + ")" : label;
        } else if (!BLOCKS[tag]) out += inline(child);
        else out += "\n" + inline(child);
      }
    });
    return out;
  }

  // A paragraph's lines must not read as list / heading / quote markers.
  function literal(text) {
    return text
      .split("\n")
      .map(function (line) { return /^(- |\d+\. |#|>)/.test(line) ? "\\" + line : line; })
      .join("\n");
  }

  function listLines(list, out) {
    var ordered = list.tagName === "OL";
    var n = 0;
    Array.prototype.forEach.call(list.children, function (item) {
      if (item.tagName !== "LI") return;
      n += 1;
      var own = document.createElement("div");
      var nested = [];
      Array.prototype.forEach.call(item.childNodes, function (c) {
        if (c.nodeType === 1 && (c.tagName === "UL" || c.tagName === "OL")) nested.push(c);
        else own.appendChild(c.cloneNode(true));
      });
      var text = inline(own).trim().replace(/\n+/g, " ");
      out.push((ordered ? n + ". " : "- ") + text);
      nested.forEach(function (l) { listLines(l, out); });
    });
  }

  function blocks(node, out) {
    var buffer = document.createElement("div");
    function flush() {
      var text = inline(buffer).trim();
      if (text) out.push(literal(text));
      buffer = document.createElement("div");
    }
    Array.prototype.forEach.call(node.childNodes, function (child) {
      var tag = child.nodeType === 1 ? child.tagName : "";
      if (!BLOCKS[tag]) {
        buffer.appendChild(child.cloneNode(true));
        return;
      }
      flush();
      if (tag === "UL" || tag === "OL") {
        var lines = [];
        listLines(child, lines);
        if (lines.length) out.push(lines.join("\n"));
      } else if (/^H\d$/.test(tag)) {
        var heading = inline(child).trim().replace(/\n+/g, " ");
        if (heading) out.push("## " + heading);
      } else if (tag === "BLOCKQUOTE") {
        var quote = inline(child).trim();
        if (quote) out.push(quote.split("\n").map(function (l) { return "> " + l; }).join("\n"));
      } else if (Array.prototype.some.call(child.childNodes, function (c) { return c.nodeType === 1 && BLOCKS[c.tagName]; })) {
        blocks(child, out);
      } else {
        var text = inline(child).trim();
        if (text) out.push(literal(text));
      }
    });
    flush();
  }

  function toMarkdown() {
    var out = [];
    blocks(body, out);
    return out.join("\n\n");
  }

  var markdownMode = false;
  function sync() { if (!markdownMode) textarea.value = toMarkdown(); }

  function command(name) {
    if (markdownMode) return;
    body.focus();
    if (name === "link") {
      var url = window.prompt(box.dataset.linkPrompt || "Link", "https://");
      // Only a page of this site or a web address, like the server accepts.
      if (url && /^(\/(?!\/)\S*|https?:\/\/\S+)$/.test(url.trim())) document.execCommand("createLink", false, url.trim());
    } else if (name === "heading" || name === "quote") {
      var tag = name === "heading" ? "h3" : "blockquote";
      var current = (document.queryCommandValue("formatBlock") || "").toLowerCase();
      document.execCommand("formatBlock", false, current === tag ? "p" : tag);
    } else {
      document.execCommand(name, false, null);
    }
    sync();
    state();
  }

  var buttons = box.querySelectorAll("[data-cmd]");
  function state() {
    var block = "";
    try { block = (document.queryCommandValue("formatBlock") || "").toLowerCase(); } catch (e) {}
    Array.prototype.forEach.call(buttons, function (button) {
      var name = button.dataset.cmd;
      var on = false;
      try {
        on = name === "heading" ? block === "h3"
          : name === "quote" ? block === "blockquote"
          : name === "link" ? false
          : document.queryCommandState(name);
      } catch (e) {}
      button.classList.toggle("on", !!on);
      button.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  var bar = box.querySelector(".rte-bar");
  var modeButton = box.querySelector("[data-mode]");
  var form = body.closest("form");

  function setMode(markdown) {
    markdownMode = markdown;
    box.classList.toggle("md-mode", markdown);
    body.hidden = markdown;
    textarea.hidden = !markdown;
    modeButton.classList.toggle("on", markdown);
    modeButton.setAttribute("aria-pressed", markdown ? "true" : "false");
  }

  function csrfToken() {
    var input = form.querySelector("input[name=csrfmiddlewaretoken]");
    return input ? input.value : "";
  }

  function toMarkdownMode() {
    textarea.value = toMarkdown();
    setMode(true);
    textarea.focus();
  }

  function toVisualMode() {
    var data = new FormData();
    data.append("text", textarea.value);
    fetch(box.dataset.previewUrl, {
      method: "POST",
      body: data,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken(), "X-Requested-With": "XMLHttpRequest" },
    })
      .then(function (response) {
        if (!response.ok) throw new Error("preview");
        return response.text();
      })
      .then(function (html) {
        body.innerHTML = html; // rendered (and escaped) by the server
        setMode(false);
        sync();
        body.focus();
      })
      .catch(function () { /* stay in Markdown: nothing is lost */ });
  }

  modeButton.addEventListener("mousedown", function (event) { event.preventDefault(); });
  modeButton.addEventListener("click", function () {
    if (markdownMode) toVisualMode(); else toMarkdownMode();
  });

  // The toolbar floats above the phone's keyboard while a field of the editor has focus: the
  // visual viewport (what is left of the screen) tells how high the keyboard is.
  var coarse = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
  var editing = false;
  function place() {
    var vv = window.visualViewport;
    var keyboard = vv ? Math.max(0, window.innerHeight - vv.height - vv.offsetTop) : 0;
    var floating = editing && (coarse || keyboard > 80);
    bar.classList.toggle("floating", floating);
    form.classList.toggle("kb", floating);
    bar.style.bottom = floating ? keyboard + "px" : "";
  }
  [body, textarea].forEach(function (field) {
    field.addEventListener("focus", function () { editing = true; place(); });
    field.addEventListener("blur", function () {
      editing = false;
      setTimeout(function () { if (!editing) place(); }, 150);
    });
  });
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", place);
    window.visualViewport.addEventListener("scroll", place);
  }

  Array.prototype.forEach.call(buttons, function (button) {
    // mousedown, not click: keep the selection (and the keyboard) in the box.
    button.addEventListener("mousedown", function (event) { event.preventDefault(); });
    button.addEventListener("click", function () { command(button.dataset.cmd); });
  });
  body.addEventListener("input", sync);
  body.addEventListener("keyup", state);
  body.addEventListener("mouseup", state);
  body.addEventListener("focus", state);
  // Pasted text comes in as plain text: no foreign styles or markup.
  body.addEventListener("paste", function (event) {
    var text = event.clipboardData && event.clipboardData.getData("text/plain");
    if (text === undefined || text === null) return;
    event.preventDefault();
    document.execCommand("insertText", false, text);
  });
  form.addEventListener("submit", sync);

  try { document.execCommand("defaultParagraphSeparator", false, "p"); } catch (e) {}
  box.hidden = false;
  setMode(false);
  // The label's `for` points at the textarea: send a click on it to the editor instead.
  var label = box.parentNode.querySelector("label");
  if (label) {
    label.addEventListener("click", function (event) {
      event.preventDefault();
      (markdownMode ? textarea : body).focus();
    });
  }
  sync();
})();
