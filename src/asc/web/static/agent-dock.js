(function () {
  "use strict";

  function tt(key, vars) {
    if (typeof window.t === "function") return window.t(key, vars);
    return key;
  }

  function parseSseChunk(buffer) {
    var parts = buffer.split("\n\n");
    var rest = parts.pop();
    var events = [];
    parts.forEach(function (block) {
      var name = "message";
      var data = [];
      block.split("\n").forEach(function (line) {
        if (line.indexOf("event:") === 0) name = line.slice(6).trim();
        else if (line.indexOf("data:") === 0) data.push(line.slice(5).replace(/^ /, ""));
      });
      events.push({ event: name, data: data.join("\n") });
    });
    return { events: events, rest: rest };
  }

  var panel = document.querySelector("[data-agent-panel]");
  var toggle = document.querySelector("[data-agent-toggle]");
  var messagesEl = panel ? panel.querySelector("[data-agent-messages]") : null;
  var stopBtn = panel ? panel.querySelector("[data-agent-stop]") : null;
  var form = panel ? panel.querySelector("[data-agent-stream]") : null;
  var searchInput = panel ? panel.querySelector("[data-agent-task-search]") : null;
  var toolbar = panel ? panel.querySelector(".agent-dock-toolbar") : null;
  var resizeHandle = panel ? panel.querySelector("[data-agent-resize]") : null;

  var boundTaskId = null;
  var sessionId = null;
  var agentOpen = false;
  var CHROME_STORAGE_KEY = "asc.agent.chrome";
  var PANEL_WIDTH_STORAGE_KEY = "asc.agentPanel.width";
  var DEFAULT_PANEL_WIDTH = 390;
  var MIN_PANEL_WIDTH = 280;
  var MAX_PANEL_WIDTH = 720;
  var resizing = false;
  var resizeStartX = 0;
  var resizeStartWidth = DEFAULT_PANEL_WIDTH;
  var streamController = null;
  var generating = false;
  var currentAssistantEl = null;
  var bindSeq = 0;
  var searchTimer = null;
  var resultsBox = null;
  var boundMeta = null;

  function clampPanelWidth(px) {
    var minW = MIN_PANEL_WIDTH;
    var viewport = Number(window.innerWidth);
    if (!Number.isFinite(viewport) || viewport <= 0) viewport = 1440;
    var maxW = Math.min(MAX_PANEL_WIDTH, Math.round(viewport * 0.5));
    if (maxW < minW) maxW = minW;
    var n = Number(px);
    if (!Number.isFinite(n)) n = DEFAULT_PANEL_WIDTH;
    return Math.round(Math.min(maxW, Math.max(minW, n)));
  }

  function readStoredPanelWidth() {
    try {
      var raw = localStorage.getItem(PANEL_WIDTH_STORAGE_KEY);
      if (raw == null || raw === "") return DEFAULT_PANEL_WIDTH;
      return clampPanelWidth(raw);
    } catch (error) {
      return DEFAULT_PANEL_WIDTH;
    }
  }

  var panelWidth = readStoredPanelWidth();

  function persistPanelWidth(px) {
    panelWidth = clampPanelWidth(px);
    try { localStorage.setItem(PANEL_WIDTH_STORAGE_KEY, String(panelWidth)); } catch (error) { /* ignore */ }
    return panelWidth;
  }

  function applyPanelWidthVar() {
    var widthPx = agentOpen ? panelWidth : 0;
    try {
      document.documentElement.style.setProperty("--agent-panel-width", widthPx + "px");
    } catch (error) { /* ignore */ }
  }

  function emptyChrome() {
    return { agentOpen: false, sessionId: "", boundTaskId: "" };
  }

  function readChrome() {
    try {
      var raw = sessionStorage.getItem(CHROME_STORAGE_KEY);
      if (!raw) return emptyChrome();
      var parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return emptyChrome();
      return {
        agentOpen: parsed.agentOpen === true,
        sessionId: typeof parsed.sessionId === "string" ? parsed.sessionId : "",
        boundTaskId: typeof parsed.boundTaskId === "string" ? parsed.boundTaskId : ""
      };
    } catch (error) {
      return emptyChrome();
    }
  }

  function persistChrome() {
    try {
      sessionStorage.setItem("asc.agent.chrome", JSON.stringify({
        agentOpen: !!agentOpen,
        sessionId: sessionId ? String(sessionId) : "",
        boundTaskId: boundTaskId ? String(boundTaskId) : ""
      }));
    } catch (error) { /* in-memory only */ }
  }

  function getState() {
    return {
      open: !!agentOpen,
      sessionId: sessionId ? String(sessionId) : "",
      boundTaskId: boundTaskId ? String(boundTaskId) : ""
    };
  }

  function setOpen(open) {
    agentOpen = !!open;
    if (panel) {
      panel.classList.toggle("is-open", agentOpen);
      panel.setAttribute("aria-hidden", agentOpen ? "false" : "true");
    }
    if (toggle) {
      toggle.setAttribute("aria-pressed", agentOpen ? "true" : "false");
    }
    applyPanelWidthVar();
    persistChrome();
  }

  async function restoreChrome() {
    var chrome = readChrome();
    sessionId = chrome.sessionId || "";
    boundTaskId = chrome.boundTaskId || "";
    setOpen(chrome.agentOpen);
    if (!boundTaskId) {
      showEmpty();
      return;
    }
    var seq = ++bindSeq;
    try {
      var response = await fetch("/api/agent/sessions?task_id=" + encodeURIComponent(boundTaskId), {
        headers: { Accept: "application/json" }
      });
      if (seq !== bindSeq) return;
      if (!response.ok) {
        showEmpty();
        return;
      }
      var payload = await response.json();
      if (seq !== bindSeq) return;
      var session = payload.session || {};
      if (session.id) sessionId = String(session.id);
      persistChrome();
      setBoundMeta({ id: boundTaskId, profile: session.profile }, session.profile);
      renderHistory(payload);
    } catch (error) {
      if (seq !== bindSeq) return;
      showEmpty();
    }
  }

  function markdownParser() {
    var marked = window.marked;
    if (!marked) return null;
    if (typeof marked.parse === "function") {
      return function (text, options) { return marked.parse(text, options); };
    }
    if (typeof marked.marked === "function") {
      return function (text, options) { return marked.marked(text, options); };
    }
    if (typeof marked === "function") return marked;
    return null;
  }

  function fallbackSanitize(html) {
    if (typeof document === "undefined" || !document.createElement) {
      return String(html || "");
    }
    var template = document.createElement("template");
    template.innerHTML = String(html || "");
    var forbidden = template.content.querySelectorAll(
      "script,iframe,object,embed,link,meta,style,form"
    );
    Array.prototype.forEach.call(forbidden, function (node) {
      if (node.parentNode) node.parentNode.removeChild(node);
    });
    var nodes = template.content.querySelectorAll("*");
    Array.prototype.forEach.call(nodes, function (el) {
      if (!el.attributes) return;
      var names = [];
      var i;
      for (i = 0; i < el.attributes.length; i++) names.push(el.attributes[i].name);
      for (i = 0; i < names.length; i++) {
        var name = names[i];
        var lower = name.toLowerCase();
        var value = el.getAttribute(name) || "";
        if (
          lower.indexOf("on") === 0 ||
          lower === "srcdoc" ||
          /^\s*javascript:/i.test(value)
        ) {
          el.removeAttribute(name);
        }
      }
    });
    var wrap = document.createElement("div");
    wrap.appendChild(template.content);
    return wrap.innerHTML;
  }

  function sanitizeHtml(html) {
    if (html == null) return "";
    if (typeof html !== "string") {
      if (html && typeof html.then === "function") return null;
      html = String(html);
    }
    if (window.DOMPurify && typeof window.DOMPurify.sanitize === "function") {
      return window.DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
    }
    return fallbackSanitize(html);
  }

  function renderMarkdown(text) {
    var parse = markdownParser();
    if (!parse) return null;
    var html;
    try { html = parse(String(text || ""), { gfm: true, breaks: true }); }
    catch (error) { return null; }
    if (html && typeof html.then === "function") return null;
    return sanitizeHtml(html);
  }

  function setAssistantMarkdown(el, text) {
    var source = String(text || "");
    el.classList.add("agent-msg--md");
    el.setAttribute("data-md-source", source);
    var html = renderMarkdown(source);
    if (html == null) {
      el.textContent = source;
      return;
    }
    el.innerHTML = html;
  }

  function scheduleMdRender(el) {
    if (el._mdRaf) return;
    el._mdRaf = window.requestAnimationFrame(function () {
      el._mdRaf = 0;
      setAssistantMarkdown(el, el._mdSource || "");
    });
  }

  function flushMdRender(el) {
    if (!el) return;
    if (el._mdRaf) {
      window.cancelAnimationFrame(el._mdRaf);
      el._mdRaf = 0;
    }
    setAssistantMarkdown(el, el._mdSource || "");
  }

  function trunc(value, max) {
    var text = typeof value === "string" ? value : JSON.stringify(value);
    if (!text) return "";
    return text.length > max ? text.slice(0, max) + "…" : text;
  }

  function shortId(value) {
    var text = String(value || "");
    return text.length <= 10 ? text : text.slice(0, 8);
  }

  function hideEmpty() {
    if (!messagesEl) return;
    var empty = messagesEl.querySelector(".agent-dock-empty");
    if (empty) empty.remove();
  }

  function showEmpty() {
    if (!messagesEl) return;
    messagesEl.replaceChildren();
    var empty = document.createElement("p");
    empty.className = "agent-dock-empty";
    empty.textContent = tt("agent.empty");
    messagesEl.appendChild(empty);
  }

  function scrollMessages() {
    if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function setGenerating(on) {
    generating = !!on;
    if (stopBtn) stopBtn.hidden = !generating;
  }

  function requestStop() {
    if (!sessionId) return;
    fetch("/api/agent/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId })
    }).catch(function () { /* stop is best-effort */ });
  }

  function abortFetch() {
    flushMdRender(currentAssistantEl);
    if (streamController) {
      streamController.abort();
      streamController = null;
    }
    setGenerating(false);
    currentAssistantEl = null;
  }

  function abortStream() {
    var wasGenerating = generating;
    abortFetch();
    if (wasGenerating) requestStop();
  }

  function setBoundMeta(task, profile) {
    if (!toolbar) return;
    if (!boundMeta) {
      boundMeta = document.createElement("div");
      boundMeta.className = "agent-bound-meta";
      boundMeta.setAttribute("data-agent-bound", "");
      toolbar.insertBefore(boundMeta, toolbar.firstChild);
    }
    var title = task && (task.title || task.kind);
    var bits = [];
    if (title) bits.push(String(title));
    if (boundTaskId) bits.push(shortId(boundTaskId));
    var profileName = (task && task.profile) || profile;
    if (profileName) bits.push(String(profileName));
    var when = task && (task.updated_at || task.created_at);
    if (when) bits.push(String(when).slice(0, 16).replace("T", " "));
    boundMeta.textContent = bits.join(" · ");
    boundMeta.hidden = !bits.length;
  }

  function appendBubble(role, text) {
    if (!messagesEl || text == null || text === "") return;
    hideEmpty();
    currentAssistantEl = null;
    var node = document.createElement("div");
    node.className = "agent-msg agent-msg--" + role;
    if (role === "assistant") setAssistantMarkdown(node, text);
    else node.textContent = String(text);
    messagesEl.appendChild(node);
    scrollMessages();
    return node;
  }

  function appendToken(fragment) {
    if (!messagesEl || fragment == null || fragment === "") return;
    hideEmpty();
    if (!currentAssistantEl) {
      currentAssistantEl = document.createElement("div");
      currentAssistantEl.className = "agent-msg agent-msg--assistant agent-msg--md";
      currentAssistantEl._mdSource = "";
      messagesEl.appendChild(currentAssistantEl);
    }
    currentAssistantEl._mdSource += String(fragment);
    scheduleMdRender(currentAssistantEl);
    scrollMessages();
  }

  function appendToolStatus(summary) {
    if (!messagesEl) return;
    hideEmpty();
    currentAssistantEl = null;
    var row = document.createElement("div");
    row.className = "agent-tool-status";
    row.textContent = summary || tt("agent.tool_running");
    messagesEl.appendChild(row);
    scrollMessages();
  }

  function mutationLine(mutation) {
    var op = mutation && mutation.op ? String(mutation.op) : "";
    var path = mutation && mutation.path ? String(mutation.path) : "";
    var before = "";
    var after = "";
    if (mutation) {
      if (mutation.before != null) before = trunc(mutation.before, 80);
      if (mutation.fields != null) after = trunc(mutation.fields, 80);
      else if (mutation.after != null) after = trunc(mutation.after, 80);
      else if (mutation.value != null) after = trunc(mutation.value, 80);
      else if (mutation.action) after = String(mutation.action);
    }
    var line = (op + " " + path).trim();
    if (before || after) line += "  " + before + " → " + after;
    return line;
  }

  function setCardStatus(card, status, detail) {
    if (!card) return;
    var statusEl = card.querySelector("[data-agent-plan-status]");
    if (!statusEl) {
      statusEl = document.createElement("p");
      statusEl.setAttribute("data-agent-plan-status", "");
      card.appendChild(statusEl);
    }
    var key = "agent." + status;
    var label = tt(key);
    statusEl.textContent = label === key ? String(status) : label;
    if (detail) statusEl.textContent += " — " + trunc(detail, 120);
    var actions = card.querySelector(".agent-plan-card__actions");
    if (actions && status !== "pending") actions.remove();
  }

  function renderPlanCard(plan) {
    if (!messagesEl || !plan) return;
    var status = String(plan.status || "");
    if (status === "draft" || status === "abandoned") return;
    hideEmpty();
    var card = document.createElement("article");
    card.className = "agent-plan-card";
    card.setAttribute("data-agent-plan", String(plan.id || ""));

    var summary = document.createElement("p");
    summary.className = "agent-plan-card__summary";
    summary.textContent = plan.summary || "";
    card.appendChild(summary);

    var mutations = Array.isArray(plan.mutations) ? plan.mutations : [];
    mutations.forEach(function (mutation) {
      var line = document.createElement("div");
      line.className = "agent-plan-mutation";
      line.textContent = mutationLine(mutation);
      card.appendChild(line);
    });

    var steps = Array.isArray(plan.manual_steps) ? plan.manual_steps : [];
    steps.forEach(function (step) {
      var line = document.createElement("div");
      line.className = "agent-plan-mutation";
      line.textContent = String(step);
      card.appendChild(line);
    });

    if (plan.rerun && plan.rerun.task_id) {
      var rerunHint = document.createElement("p");
      rerunHint.className = "agent-plan-mutation";
      rerunHint.textContent = String(plan.rerun.kind || "") + " · " + shortId(plan.rerun.task_id);
      card.appendChild(rerunHint);
    }

    if (status === "pending") {
      var actions = document.createElement("div");
      actions.className = "agent-plan-card__actions";
      if (plan.rerun) {
        var label = document.createElement("label");
        var box = document.createElement("input");
        box.type = "checkbox";
        box.setAttribute("data-agent-rerun", "");
        box.checked = true;
        label.append(box, document.createTextNode(" " + tt("agent.rerun_after_apply")));
        actions.appendChild(label);
      }
      if (mutations.length) {
        var applyBtn = document.createElement("button");
        applyBtn.type = "button";
        applyBtn.className = "task-log-button";
        applyBtn.textContent = tt("agent.apply");
        applyBtn.addEventListener("click", function () {
          applyPlan(plan, card);
        });
        actions.appendChild(applyBtn);
      }
      var ignoreBtn = document.createElement("button");
      ignoreBtn.type = "button";
      ignoreBtn.className = "task-log-button";
      ignoreBtn.textContent = tt("agent.ignore");
      ignoreBtn.addEventListener("click", function () {
        rejectPlan(plan, card);
      });
      actions.appendChild(ignoreBtn);
      card.appendChild(actions);
    } else {
      setCardStatus(card, status, plan.error);
    }

    messagesEl.appendChild(card);
    scrollMessages();
  }

  async function loadPlanCards(planIds) {
    if (!planIds || !planIds.length) return;
    for (var i = 0; i < planIds.length; i += 1) {
      try {
        var response = await fetch("/api/agent/plans/" + encodeURIComponent(planIds[i]), {
          headers: { Accept: "application/json" }
        });
        if (!response.ok) continue;
        renderPlanCard(await response.json());
      } catch (error) {
        /* skip a missing plan and keep remaining cards */
      }
    }
  }

  async function applyPlan(plan, card) {
    if (!plan || !plan.id) return;
    var rerun = false;
    var box = card && card.querySelector("[data-agent-rerun]");
    if (box) rerun = !!box.checked;
    setCardStatus(card, "applying");
    try {
      var response = await fetch("/api/agent/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_id: plan.id, rerun: rerun })
      });
      var payload = {};
      try { payload = await response.json(); } catch (parseError) { payload = {}; }
      if (!response.ok || payload.ok === false) {
        var detail = payload.error || payload.detail || payload.rerun_error || String(response.status);
        setCardStatus(card, "apply_failed", detail);
        return;
      }
      setCardStatus(card, payload.status || "applied", payload.rerun_error);
      if (payload.new_task_id && window.TaskLogDrawer) {
        TaskLogDrawer.open(payload.new_task_id);
      }
    } catch (error) {
      setCardStatus(card, "apply_failed", error && error.message);
    }
  }

  async function rejectPlan(plan, card) {
    if (!plan || !plan.id) return;
    try {
      var response = await fetch("/api/agent/reject", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_id: plan.id })
      });
      if (!response.ok) return;
      setCardStatus(card, "rejected");
    } catch (error) {
      /* keep the card actionable if reject fails */
    }
  }

  function handleFrame(frame) {
    var name = frame && frame.event;
    var data = frame && frame.data;
    if (!name || name === "message") return;
    if (name === "session") {
      try {
        var session = JSON.parse(data);
        if (session.session_id) sessionId = String(session.session_id);
        if (session.task_id) boundTaskId = String(session.task_id);
        persistChrome();
      } catch (error) { /* ignore malformed session frames */ }
      return;
    }
    if (name === "token") {
      appendToken(data);
      return;
    }
    if (name === "tool_start") {
      appendToolStatus(tt("agent.tool_running"));
      return;
    }
    if (name === "tool_result") {
      return;
    }
    if (name === "error") {
      setGenerating(false);
      try {
        var err = JSON.parse(data);
        appendBubble("error", err.message || data);
      } catch (error) {
        appendBubble("error", data);
      }
      return;
    }
    if (name === "stopped") {
      setGenerating(false);
      flushMdRender(currentAssistantEl);
      return;
    }
    if (name === "done") {
      setGenerating(false);
      flushMdRender(currentAssistantEl);
      currentAssistantEl = null;
      try {
        var done = JSON.parse(data);
        if (done.session_id) sessionId = String(done.session_id);
        persistChrome();
        var planIds = done.plan_ids || [];
        if (planIds.length) loadPlanCards(planIds);
      } catch (error) { /* done without cards is still a finished turn */ }
    }
  }

  async function readSse(reader) {
    var decoder = new TextDecoder();
    var buffer = "";
    while (true) {
      var chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      var parsed = parseSseChunk(buffer);
      buffer = parsed.rest;
      parsed.events.forEach(handleFrame);
    }
    if (buffer.trim()) {
      parseSseChunk(buffer + "\n\n").events.forEach(handleFrame);
    }
    flushMdRender(currentAssistantEl);
    setGenerating(false);
  }

  function startStream(options) {
    options = options || {};
    var taskId = options.task_id || boundTaskId;
    var sid = options.session_id || sessionId;
    if (!taskId && !sid) return;
    abortFetch();
    streamController = new AbortController();
    setGenerating(true);
    currentAssistantEl = null;
    var body = {
      message: options.message || "",
      auto_analyze: !!options.auto_analyze
    };
    if (sid) body.session_id = sid;
    if (taskId) body.task_id = taskId;
    fetch("/api/agent/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream"
      },
      body: JSON.stringify(body),
      signal: streamController.signal
    }).then(function (response) {
      if (!response.ok || !response.body || typeof response.body.getReader !== "function") {
        setGenerating(false);
        appendBubble("error", tt("agent.error.llm_unavailable"));
        return null;
      }
      return readSse(response.body.getReader());
    }).catch(function (error) {
      if (error && error.name === "AbortError") return;
      setGenerating(false);
      appendBubble("error", tt("agent.error.llm_unavailable"));
    });
  }

  function hasUserOrAssistant(messages) {
    return (messages || []).some(function (msg) {
      return msg.role === "user" || msg.role === "assistant";
    });
  }

  function renderHistory(payload) {
    showEmpty();
    var messages = (payload && payload.messages) || [];
    messages.forEach(function (msg) {
      if (msg.role === "user" || msg.role === "assistant") {
        appendBubble(msg.role, msg.content);
      }
    });
    ((payload && payload.plans) || []).forEach(renderPlanCard);
  }

  async function bindTask(taskId) {
    if (taskId == null || String(taskId) === "") return;
    var seq = ++bindSeq;
    abortStream();
    boundTaskId = String(taskId);
    sessionId = null;
    setOpen(true);
    persistChrome();
    showEmpty();
    setBoundMeta({ id: boundTaskId }, "");
    var payload;
    try {
      var response = await fetch("/api/agent/sessions?task_id=" + encodeURIComponent(boundTaskId), {
        headers: { Accept: "application/json" }
      });
      if (seq !== bindSeq) return;
      if (!response.ok) return;
      payload = await response.json();
    } catch (error) {
      if (seq !== bindSeq) return;
      return;
    }
    if (seq !== bindSeq) return;
    var session = payload.session || {};
    sessionId = session.id || null;
    persistChrome();
    setBoundMeta({ id: boundTaskId, profile: session.profile }, session.profile);
    renderHistory(payload);
    if (!hasUserOrAssistant(payload.messages)) {
      appendBubble("user", tt("agent.auto_analyze_label"));
      startStream({
        task_id: boundTaskId,
        session_id: sessionId,
        message: "",
        auto_analyze: true
      });
    }
  }

  function ensureResultsBox() {
    if (resultsBox || !toolbar) return;
    resultsBox = document.createElement("div");
    resultsBox.className = "agent-search-results";
    resultsBox.hidden = true;
    toolbar.appendChild(resultsBox);
  }

  function hideResults() {
    if (resultsBox) resultsBox.hidden = true;
  }

  async function runSearch() {
    if (!searchInput) return;
    ensureResultsBox();
    var q = String(searchInput.value || "").trim();
    var url = "/api/agent/failed-tasks";
    if (q) url += "?q=" + encodeURIComponent(q);
    try {
      var response = await fetch(url, { headers: { Accept: "application/json" } });
      if (!response.ok) return;
      var payload = await response.json();
      var tasks = payload.tasks || [];
      resultsBox.replaceChildren();
      if (!tasks.length) {
        hideResults();
        return;
      }
      tasks.forEach(function (task) {
        var button = document.createElement("button");
        button.type = "button";
        button.textContent = [
          task.title || task.kind || "",
          shortId(task.id),
          task.profile || ""
        ].filter(Boolean).join(" · ");
        button.addEventListener("click", function () {
          hideResults();
          bindTask(task.id);
        });
        resultsBox.appendChild(button);
      });
      resultsBox.hidden = false;
    } catch (error) {
      hideResults();
    }
  }

  function openBoundTask(taskId) {
    if (!taskId) return;
    setOpen(true);
    bindTask(taskId);
  }

  if (form) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (generating) return;
      var input = form.querySelector("[name=message]");
      var text = input ? String(input.value || "").trim() : "";
      if (!text || (!boundTaskId && !sessionId)) return;
      appendBubble("user", text);
      if (input) input.value = "";
      startStream({
        task_id: boundTaskId,
        session_id: sessionId,
        message: text,
        auto_analyze: false
      });
    });
  }

  if (stopBtn) {
    stopBtn.addEventListener("click", function () {
      abortStream();
    });
  }

  if (searchInput) {
    searchInput.addEventListener("input", function () {
      if (searchTimer) window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(runSearch, 200);
    });
    searchInput.addEventListener("focus", function () {
      runSearch();
    });
  }

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!target || !target.closest) return;
    var trigger = target.closest("[data-open-agent-task]");
    if (trigger) {
      var taskId = trigger.getAttribute("data-task-id");
      if (!taskId && window.TaskLogDrawer && typeof TaskLogDrawer.currentTaskId === "function") {
        taskId = TaskLogDrawer.currentTaskId();
      }
      if (taskId) openBoundTask(taskId);
      return;
    }
    if (resultsBox && toolbar && !toolbar.contains(target)) hideResults();
  });

  window.addEventListener("pagehide", function () {
    abortStream();
  });

  if (toggle) {
    toggle.addEventListener("click", function () {
      setOpen(!agentOpen);
    });
  }

  function onResizePointerMove(event) {
    if (!resizing || !agentOpen) return;
    panelWidth = clampPanelWidth(resizeStartWidth + (resizeStartX - event.clientX));
    applyPanelWidthVar();
  }

  function endPanelResize(event) {
    if (!resizing) return;
    resizing = false;
    if (event && resizeHandle && resizeHandle.releasePointerCapture && event.pointerId != null) {
      try { resizeHandle.releasePointerCapture(event.pointerId); } catch (error) { /* already released */ }
    }
    if (document.body && document.body.classList) {
      document.body.classList.remove("agent-panel-resizing");
    }
    if (panel) panel.classList.remove("is-resizing");
    document.removeEventListener("pointermove", onResizePointerMove);
    document.removeEventListener("pointerup", endPanelResize);
    document.removeEventListener("pointercancel", endPanelResize);
    persistPanelWidth(panelWidth);
    applyPanelWidthVar();
  }

  if (resizeHandle) {
    resizeHandle.addEventListener("pointerdown", function (event) {
      if (!agentOpen) return;
      if (event.button) return;
      event.preventDefault();
      resizing = true;
      resizeStartX = event.clientX;
      resizeStartWidth = clampPanelWidth(panelWidth);
      if (resizeHandle.setPointerCapture) {
        try { resizeHandle.setPointerCapture(event.pointerId); } catch (error) { /* capture is best-effort */ }
      }
      if (document.body && document.body.classList) {
        document.body.classList.add("agent-panel-resizing");
      }
      if (panel) panel.classList.add("is-resizing");
      document.addEventListener("pointermove", onResizePointerMove);
      document.addEventListener("pointerup", endPanelResize);
      document.addEventListener("pointercancel", endPanelResize);
    });
  }

  restoreChrome();

  window.AscAgentDock = {
    bindTask: bindTask,
    setOpen: setOpen,
    getState: getState,
    renderMarkdown: renderMarkdown,
    setAssistantMarkdown: setAssistantMarkdown
  };
})();
