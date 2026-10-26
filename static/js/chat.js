/* The Chat page. A question is POSTed and the reply read as a stream of server-sent events:
 *   step_start / step_end  the assistant looking something up (HTML for one step, by id)
 *   text                   the answer so far (HTML, rendered and link-checked by the server)
 *   done / error           the finished answer, or why there is none
 * When an answer is done the whole message list is fetched again from the server, so every
 * message has its id, version switcher and buttons. All HTML comes from the server, which
 * escapes it; what the user typed is inserted as text. */
(function () {
  var root = document.querySelector(".chat");
  var form = document.getElementById("chat-form");
  var log = document.getElementById("chat-log");
  if (!root || !form || !log) return;

  var input = form.querySelector("textarea");
  var button = form.querySelector("button");
  var token = form.querySelector("input[name=csrfmiddlewaretoken]").value;
  var THINKING = '<span class="thinking" aria-hidden="true"><i></i><i></i><i></i></span>';
  var busy = false;

  function nearBottom() {
    return log.scrollHeight - log.scrollTop - log.clientHeight < 120;
  }
  function scrollDown(force) {
    if (force || nearBottom()) log.scrollTop = log.scrollHeight;
  }
  function setBusy(value) {
    busy = value;
    button.disabled = value;
  }

  function message(kind) {
    var empty = log.querySelector(".chat-empty");
    if (empty) empty.remove();
    var node = document.createElement("div");
    node.className = "msg " + kind;
    if (kind === "assistant") {
      var steps = document.createElement("div");
      steps.className = "steps";
      node.appendChild(steps);
    }
    var bubble = document.createElement("div");
    bubble.className = "bubble";
    var body = document.createElement("div");
    body.className = "bubble-body";
    bubble.appendChild(body);
    node.appendChild(bubble);
    log.appendChild(node);
    return node;
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      body: body,
      credentials: "same-origin",
      headers: { "X-CSRFToken": token, "X-Requested-With": "XMLHttpRequest" },
    });
  }

  function refreshLog(keepScroll) {
    var top = log.scrollTop;
    return fetch(root.dataset.logUrl, { credentials: "same-origin" })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        log.innerHTML = html;
        if (keepScroll) log.scrollTop = top; else scrollDown(true);
      });
  }

  function parseEvent(block) {
    var name = "message", data = "";
    block.split("\n").forEach(function (line) {
      if (line.indexOf("event:") === 0) name = line.slice(6).trim();
      else if (line.indexOf("data:") === 0) data += line.slice(5).trim();
    });
    if (!data) return null; // a ": ping" comment
    try { return { name: name, data: JSON.parse(data) }; } catch (e) { return null; }
  }

  function fail(node, text) {
    var bubble = node.querySelector(".bubble");
    bubble.classList.add("failed");
    node.querySelector(".bubble-body").textContent = text || root.dataset.failed;
    node.classList.remove("working");
  }

  function handle(node, event) {
    var body = node.querySelector(".bubble-body");
    var steps = node.querySelector(".steps");
    var stick = nearBottom();
    if (event.name === "step_start") {
      steps.insertAdjacentHTML("beforeend", event.data.html);
      body.innerHTML = THINKING;
    } else if (event.name === "step_end") {
      var old = steps.querySelector('[data-step="' + CSS.escape(event.data.id) + '"]');
      if (old) old.outerHTML = event.data.html;
      else steps.insertAdjacentHTML("beforeend", event.data.html);
    } else if (event.name === "text") {
      body.innerHTML = event.data.html + '<span class="caret"></span>';
    } else if (event.name === "done") {
      body.innerHTML = event.data.html;
      node.classList.remove("working");
    } else if (event.name === "error") {
      fail(node, event.data.message);
    }
    scrollDown(stick);
  }

  // `replace`: the id of an earlier question being edited or asked again - the new one becomes
  // another version of it, and the messages that followed it are no longer shown.
  function send(text, replace) {
    text = text.trim();
    if ((!text && !replace) || busy) return;
    input.value = "";
    input.style.height = "";
    setBusy(true);

    if (replace) {
      var old = log.querySelector('.msg[data-id="' + replace + '"]');
      while (old && old.nextElementSibling) old.nextElementSibling.remove();
      if (old) old.remove();
    }
    var mine = message("user");
    mine.querySelector(".bubble-body").textContent =
      text || (replace && root.dataset.lastText) || "";
    var node = message("assistant");
    node.classList.add("working");
    node.querySelector(".bubble-body").innerHTML = THINKING;
    scrollDown(true);

    var body = new FormData();
    body.append("thread", root.dataset.thread);
    body.append("message", text);
    if (replace) body.append("replace", replace);
    var finished = false;
    var succeeded = false;

    post(root.dataset.sendUrl, body)
      .then(function (response) {
        var type = response.headers.get("Content-Type") || "";
        if (!response.ok || type.indexOf("text/event-stream") !== 0 || !response.body) {
          throw new Error("no stream");
        }
        var reader = response.body.getReader();
        var decoder = new TextDecoder();
        var buffer = "";
        function pump() {
          return reader.read().then(function (chunk) {
            if (chunk.done) return;
            buffer += decoder.decode(chunk.value, { stream: true });
            var parts = buffer.split("\n\n");
            buffer = parts.pop();
            parts.forEach(function (part) {
              var event = parseEvent(part);
              if (!event) return;
              if (event.name === "done" || event.name === "error") finished = true;
              if (event.name === "done") succeeded = true;
              handle(node, event);
            });
            return pump();
          });
        }
        return pump();
      })
      .catch(function () {
        if (!finished) { finished = true; fail(node); }
      })
      .then(function () {
        if (!finished) fail(node);
        // Put the server's version of the conversation in place of the live one - with ids,
        // version switcher and buttons. A failed answer stays on screen as it is.
        return succeeded ? refreshLog(false) : null;
      })
      .then(function () {
        setBusy(false);
        input.focus();
      });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    send(input.value);
  });
  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      send(input.value);
    }
  });
  input.addEventListener("input", function () {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 128) + "px";
  });
  Array.prototype.forEach.call(document.querySelectorAll("[data-prompt]"), function (chip) {
    chip.addEventListener("click", function () { send(chip.dataset.prompt); });
  });

  // --- Copy, edit, ask again, other versions (one listener for the whole log) --------------
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    return new Promise(function (resolve, reject) {
      var area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      try { document.execCommand("copy") ? resolve() : reject(); } catch (e) { reject(e); }
      area.remove();
    });
  }

  function startEditing(msg) {
    var body = msg.querySelector(".bubble-body");
    var foot = msg.querySelector(".bubble-foot");
    var original = body.textContent;
    var editor = document.createElement("div");
    editor.className = "editing";
    var area = document.createElement("textarea");
    area.value = original;
    area.maxLength = 2000;
    area.rows = 3;
    var row = document.createElement("div");
    row.className = "row";
    var cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = root.dataset.cancel;
    var save = document.createElement("button");
    save.type = "button";
    save.className = "primary";
    save.textContent = root.dataset.save;
    row.appendChild(cancel);
    row.appendChild(save);
    editor.appendChild(area);
    editor.appendChild(row);
    body.hidden = true;
    if (foot) foot.hidden = true;
    body.parentNode.insertBefore(editor, body);
    area.focus();
    area.setSelectionRange(area.value.length, area.value.length);

    function close() {
      editor.remove();
      body.hidden = false;
      if (foot) foot.hidden = false;
    }
    cancel.addEventListener("click", close);
    save.addEventListener("click", function () {
      var text = area.value.trim();
      if (!text) return;
      root.dataset.lastText = text;
      send(text, msg.dataset.id);
    });
    area.addEventListener("keydown", function (event) {
      if (event.key === "Escape") close();
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) save.click();
    });
  }

  log.addEventListener("click", function (event) {
    var target = event.target;
    var copy = target.closest("[data-copy-button]");
    if (copy) {
      var bubble = copy.closest(".bubble").querySelector(".bubble-body");
      copyText(bubble.innerText.trim()).then(function () {
        var label = copy.querySelector("span");
        copy.classList.add("done");
        label.textContent = root.dataset.copied;
        setTimeout(function () {
          copy.classList.remove("done");
          label.textContent = root.dataset.copy;
        }, 1600);
      });
      return;
    }
    if (busy) return;
    var msg = target.closest(".msg");
    var edit = target.closest("[data-edit-button]");
    if (edit && msg) { startEditing(msg); return; }
    var again = target.closest("[data-resend-button]");
    if (again && msg) {
      root.dataset.lastText = msg.querySelector(".bubble-body").textContent;
      send("", msg.dataset.id);
      return;
    }
    var flip = target.closest("[data-switch]");
    if (flip && flip.dataset.switch) {
      var body = new FormData();
      body.append("thread", root.dataset.thread);
      body.append("message", flip.dataset.switch);
      post(root.dataset.switchUrl, body).then(function () { return refreshLog(true); });
    }
  });

  var picker = document.getElementById("chat-character");
  if (picker) {
    picker.addEventListener("change", function () {
      var body = new FormData();
      body.append("thread", root.dataset.thread);
      body.append("character", picker.value);
      post(root.dataset.characterUrl, body);
    });
  }
  scrollDown(true);
})();
