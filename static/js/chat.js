/* The Chat page: sends a question as a same-origin POST and appends the reply (server-rendered
 * HTML, escaped by the server) to the log. Everything the user or the model wrote is inserted
 * as text, except the reply's `html`, which comes from `logbook_markup.render`. */
(function () {
  var root = document.querySelector(".chat");
  var form = document.getElementById("chat-form");
  var log = document.getElementById("chat-log");
  if (!root || !form || !log) return;

  var input = form.querySelector("textarea");
  var button = form.querySelector("button");
  var token = form.querySelector("input[name=csrfmiddlewaretoken]").value;

  function scrollDown() {
    log.scrollTop = log.scrollHeight;
  }

  function bubble(kind, text) {
    var empty = log.querySelector(".chat-empty");
    if (empty) empty.remove();
    var node = document.createElement("div");
    node.className = "bubble " + kind;
    node.textContent = text;
    log.appendChild(node);
    scrollDown();
    return node;
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      body: body,
      credentials: "same-origin",
      headers: { "X-CSRFToken": token, "X-Requested-With": "XMLHttpRequest" },
    }).then(function (response) {
      return response.json().catch(function () { return {}; });
    });
  }

  function send(text) {
    text = text.trim();
    if (!text) return;
    input.value = "";
    input.style.height = "";
    button.disabled = true;
    bubble("user", text);
    var pending = bubble("assistant pending", root.dataset.thinking);
    var body = new FormData();
    body.append("message", text);
    post(root.dataset.sendUrl, body)
      .then(function (data) {
        if (data.ok) {
          pending.className = "bubble assistant";
          pending.innerHTML = data.html;
        } else {
          pending.className = "bubble assistant failed";
          pending.textContent = data.error || root.dataset.failed;
        }
      })
      .catch(function () {
        pending.className = "bubble assistant failed";
        pending.textContent = root.dataset.failed;
      })
      .then(function () {
        button.disabled = false;
        scrollDown();
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

  var picker = document.getElementById("chat-character");
  if (picker) {
    picker.addEventListener("change", function () {
      var body = new FormData();
      body.append("character", picker.value);
      post(root.dataset.characterUrl, body);
    });
  }
  scrollDown();
})();
