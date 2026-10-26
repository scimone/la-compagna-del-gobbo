/* The Chat page. A question is POSTed and the reply read as a stream of server-sent events:
 *   step_start / step_end  the assistant looking something up (HTML for one step, by id)
 *   text                   the answer so far (HTML, rendered and link-checked by the server)
 *   done / error           the finished answer, or why there is none
 * All HTML comes from the server, which escapes it; what the user typed is inserted as text. */
(function () {
  var root = document.querySelector(".chat");
  var form = document.getElementById("chat-form");
  var log = document.getElementById("chat-log");
  if (!root || !form || !log) return;

  var input = form.querySelector("textarea");
  var button = form.querySelector("button");
  var token = form.querySelector("input[name=csrfmiddlewaretoken]").value;
  var toolsTemplate = document.getElementById("tools-template");
  var THINKING = '<span class="thinking" aria-hidden="true"><i></i><i></i><i></i></span>';

  function nearBottom() {
    return log.scrollHeight - log.scrollTop - log.clientHeight < 120;
  }
  function scrollDown(force) {
    if (force || nearBottom()) log.scrollTop = log.scrollHeight;
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
    node.appendChild(bubble);
    if (toolsTemplate) node.appendChild(toolsTemplate.content.cloneNode(true));
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
    bubble.className = "bubble failed";
    bubble.textContent = text || root.dataset.failed;
    node.classList.remove("working");
  }

  function handle(node, event) {
    var bubble = node.querySelector(".bubble");
    var steps = node.querySelector(".steps");
    var stick = nearBottom();
    if (event.name === "step_start") {
      steps.insertAdjacentHTML("beforeend", event.data.html);
      bubble.innerHTML = THINKING;
    } else if (event.name === "step_end") {
      var old = steps.querySelector('[data-step="' + CSS.escape(event.data.id) + '"]');
      if (old) old.outerHTML = event.data.html;
      else steps.insertAdjacentHTML("beforeend", event.data.html);
    } else if (event.name === "text") {
      bubble.innerHTML = event.data.html + '<span class="caret"></span>';
    } else if (event.name === "done") {
      bubble.innerHTML = event.data.html;
      node.classList.remove("working");
    } else if (event.name === "error") {
      fail(node, event.data.message);
    }
    scrollDown(stick);
  }

  function send(text) {
    text = text.trim();
    if (!text || button.disabled) return;
    input.value = "";
    input.style.height = "";
    button.disabled = true;

    var mine = message("user");
    mine.querySelector(".bubble").textContent = text;
    var node = message("assistant");
    node.classList.add("working");
    node.querySelector(".bubble").innerHTML = THINKING;
    scrollDown(true);

    var body = new FormData();
    body.append("thread", root.dataset.thread);
    body.append("message", text);
    var finished = false;

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
        button.disabled = false;
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

  // Copy: the text of the bubble it sits under.
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
  log.addEventListener("click", function (event) {
    var copy = event.target.closest("[data-copy-button]");
    if (!copy) return;
    var bubble = copy.closest(".msg").querySelector(".bubble");
    copyText(bubble.innerText.trim()).then(function () {
      var label = copy.querySelector("span");
      copy.classList.add("done");
      label.textContent = root.dataset.copied;
      setTimeout(function () {
        copy.classList.remove("done");
        label.textContent = root.dataset.copy;
      }, 1600);
    });
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
