(function () {
  "use strict";

  function tt(key, vars) {
    if (typeof window.t === "function") return window.t(key, vars);
    return key;
  }

  var drawer = document.getElementById("task-log-drawer");
  if (!drawer) {
    window.TaskLogDrawer = {
      open: function () {},
      close: function () {},
      isOpen: function () { return false; },
      currentTaskId: function () { return null; },
      attachDock: function () {},
      preferOverlay: function () {}
    };
    return;
  }

  var titleEl = document.getElementById("task-log-title");
  var output = document.getElementById("task-log-output");
  var statusEl = drawer.querySelector("[data-task-log-status]");
  var positionEl = drawer.querySelector("[data-task-log-position]");
  var followControl = drawer.querySelector("[data-task-log-follow]");
  var latestControl = drawer.querySelector("[data-task-log-latest]");
  var errorsControl = drawer.querySelector("[data-task-log-errors]");
  var copyControl = drawer.querySelector("[data-task-log-copy]");
  var clearControl = drawer.querySelector("[data-task-log-clear]");
  var closeControl = drawer.querySelector("[data-task-log-close]");
  var tabButtons = drawer.querySelectorAll("[data-task-log-tab]");
  var logsPanel = drawer.querySelector('[data-task-log-panel="logs"]');
  var agentPanel = drawer.querySelector('[data-task-log-panel="agent"]');
  var explainControl = drawer.querySelector("[data-open-agent-task]");
  var agentNav = document.querySelector("[data-open-agent-dock]");
  var agentForm = drawer.querySelector("[data-agent-stream]");
  var sidebar = document.querySelector("body > aside");
  var overlayMedia = window.matchMedia("(max-width: 1360px)");

  var homeParent = drawer.parentElement;
  var homeNextSibling = drawer.nextSibling;
  var dockHost = null;
  var forceOverlay = false;

  var eventSource = null;
  var statusController = null;
  var openRequestId = 0;
  var activeTaskId = null;
  var callbacks = {};
  var lastSeq = 0;
  var followPaused = false;
  var newLogCount = 0;
  var logEntries = [];
  var onlyErrors = false;
  var connectionStatus = tt("drawer.waiting");
  var closeTransitionHandler = null;
  var closeFallbackTimer = null;
  var reconnectTimer = null;
  var reconnectAttempts = 0;
  var backgroundInertEntries = null;
  var previouslyFocused = null;
  var suppressNextOutsideClick = false;
  var activeTab = "logs";

  function isDrawerOpen() {
    return drawer.classList.contains("is-open");
  }

  function isOverlayMode() {
    return forceOverlay || !dockHost || overlayMedia.matches;
  }

  function setYieldPanelsHidden(hidden) {
    document.querySelectorAll("[data-task-log-yield]").forEach(function (element) {
      if (hidden) element.setAttribute("data-yielded", "true");
      else element.removeAttribute("data-yielded");
      element.setAttribute("aria-hidden", hidden ? "true" : "false");
    });
  }

  function moveToHome() {
    if (!homeParent || drawer.parentElement === homeParent) return;
    if (homeNextSibling && homeNextSibling.parentNode === homeParent) {
      homeParent.insertBefore(drawer, homeNextSibling);
    } else {
      homeParent.appendChild(drawer);
    }
  }

  function applyInertState(element) {
    var state = {
      hadInertAttr: element.hasAttribute("inert"),
      priorInertProp: "inert" in element ? element.inert : false,
      ariaHidden: element.getAttribute("aria-hidden")
    };
    element.setAttribute("inert", "");
    if ("inert" in element) element.inert = true;
    element.setAttribute("aria-hidden", "true");
    return state;
  }

  function releaseInertState(element, state) {
    if ("inert" in element) element.inert = state.priorInertProp;
    if (!state.hadInertAttr) element.removeAttribute("inert");
    if (state.ariaHidden == null) element.removeAttribute("aria-hidden");
    else element.setAttribute("aria-hidden", state.ariaHidden);
  }

  function setBackgroundInert(enabled) {
    if (enabled) {
      if (backgroundInertEntries) return;
      var nodes = [];
      if (sidebar) nodes.push(sidebar);
      var container = drawer.parentElement;
      if (container) {
        Array.prototype.forEach.call(container.children, function (child) {
          if (child !== drawer) nodes.push(child);
        });
      }
      backgroundInertEntries = nodes.map(function (element) {
        return { el: element, state: applyInertState(element) };
      });
    } else if (backgroundInertEntries) {
      backgroundInertEntries.forEach(function (entry) {
        releaseInertState(entry.el, entry.state);
      });
      backgroundInertEntries = null;
    }
  }

  function updateMode() {
    var overlay = isOverlayMode();
    drawer.classList.toggle("is-overlay", overlay);
    drawer.classList.toggle("is-docked", !overlay);
    if (overlay) {
      moveToHome();
    } else if (dockHost && drawer.parentElement !== dockHost) {
      dockHost.appendChild(drawer);
    }
    if (dockHost) {
      dockHost.setAttribute("aria-hidden", isDrawerOpen() && !overlay ? "false" : "true");
    }
    // Build (and similar) right panels yield space while the drawer is docked open.
    setYieldPanelsHidden(isDrawerOpen() && !overlay);
    var modal = isDrawerOpen() && overlay;
    drawer.setAttribute("aria-modal", modal ? "true" : "false");
    setBackgroundInert(modal);
  }

  function drawerFocusables() {
    return Array.prototype.filter.call(
      drawer.querySelectorAll('button:not([disabled]):not([hidden]), input:not([disabled]):not([hidden]), [href], [tabindex]:not([tabindex="-1"])'),
      function (element) { return !element.hidden && element.getClientRects().length > 0; }
    );
  }

  function trapDrawerFocus(event) {
    if (event.key !== "Tab" || !isDrawerOpen() || !isOverlayMode()) return;
    var focusables = drawerFocusables();
    if (!focusables.length) return;
    var first = focusables[0];
    var last = focusables[focusables.length - 1];
    if (!drawer.contains(document.activeElement)) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
    } else if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function clearCloseTransition() {
    if (closeTransitionHandler) {
      drawer.removeEventListener("transitionend", closeTransitionHandler);
      closeTransitionHandler = null;
    }
    if (closeFallbackTimer != null) {
      clearTimeout(closeFallbackTimer);
      closeFallbackTimer = null;
    }
  }

  function openDrawerPanel() {
    clearCloseTransition();
    drawer.hidden = false;
    // Force a reflow so translateX(100%) paints before sliding in.
    void drawer.offsetWidth;
    drawer.classList.add("is-open");
    updateMode();
  }

  function beginCloseDrawerPanel() {
    if (!isDrawerOpen()) {
      drawer.hidden = true;
      updateMode();
      return;
    }
    clearCloseTransition();
    drawer.classList.remove("is-open");
    updateMode();
    closeTransitionHandler = function (event) {
      if (event.target !== drawer || event.propertyName !== "transform") return;
      clearCloseTransition();
      if (!isDrawerOpen()) drawer.hidden = true;
    };
    drawer.addEventListener("transitionend", closeTransitionHandler);
    closeFallbackTimer = setTimeout(function () {
      clearCloseTransition();
      if (!isDrawerOpen()) drawer.hidden = true;
    }, 300);
  }

  function setTaskState(state) {
    if (!drawer) return;
    if (state) drawer.setAttribute("data-task-state", state);
    else drawer.removeAttribute("data-task-state");
  }

  function updateAgentNavPressed() {
    if (!agentNav) return;
    var pressed = isDrawerOpen() && activeTab === "agent";
    agentNav.setAttribute("aria-pressed", pressed ? "true" : "false");
    agentNav.classList.toggle("active", pressed);
  }

  function setActiveTab(tab) {
    var next = tab === "agent" ? "agent" : "logs";
    if (next === "agent") pauseAtCurrentViewport();
    activeTab = next;
    Array.prototype.forEach.call(tabButtons, function (button) {
      var selected = button.getAttribute("data-task-log-tab") === activeTab;
      button.setAttribute("aria-selected", selected ? "true" : "false");
    });
    if (logsPanel) logsPanel.hidden = activeTab !== "logs";
    if (agentPanel) agentPanel.hidden = activeTab !== "agent";
    updateAgentNavPressed();
  }

  function syncExplainButton(isError) {
    if (!explainControl) return;
    explainControl.hidden = !isError;
    if (isError && activeTaskId) explainControl.setAttribute("data-task-id", activeTaskId);
    else explainControl.removeAttribute("data-task-id");
  }

  function updatePosition() {
    if (!positionEl || !statusEl) return;
    if (newLogCount > 0) {
      positionEl.textContent = tt("drawer.unread", { n: newLogCount });
      statusEl.textContent = tt("drawer.new_logs", { n: newLogCount });
      if (latestControl) latestControl.hidden = false;
    } else {
      positionEl.textContent = lastSeq + " / ?";
      statusEl.textContent = connectionStatus;
      if (latestControl) latestControl.hidden = !followPaused;
    }
  }

  function setConnectionStatus(message, preserveUnread) {
    connectionStatus = message;
    if (statusEl && (!preserveUnread || newLogCount === 0)) statusEl.textContent = connectionStatus;
  }

  function isAtBottom() {
    if (!output) return true;
    return output.scrollHeight - output.scrollTop - output.clientHeight <= 8;
  }

  function setFollow(enabled) {
    followPaused = !enabled;
    if (followControl) followControl.checked = enabled;
    if (enabled && output) {
      newLogCount = 0;
      output.scrollTop = output.scrollHeight;
    }
    updatePosition();
  }

  function pauseAtCurrentViewport() {
    if (!output) {
      setFollow(false);
      return;
    }
    var scrollTop = output.scrollTop;
    setFollow(false);
    output.scrollTop = scrollTop;
  }

  function isErrorLog(message) {
    return /\b(error|failed|failure|fatal|exception|traceback)\b|错误|失败|异常/i.test(String(message));
  }

  function createLogNode(entry) {
    var line = document.createElement("div");
    line.className = entry.isError ? "task-log-line task-log-line--error" : "task-log-line";
    line.textContent = entry.message;
    return line;
  }

  function renderLogEntries() {
    if (!output) return;
    var fragment = document.createDocumentFragment();
    logEntries.forEach(function (entry) {
      if (!onlyErrors || entry.isError) fragment.append(createLogNode(entry));
    });
    output.replaceChildren(fragment);
  }

  function appendLog(message, seq) {
    var shouldFollow = !followPaused && isAtBottom();
    var entry = { seq: seq, message: String(message), isError: isErrorLog(message) };
    logEntries.push(entry);
    if (output && (!onlyErrors || entry.isError)) output.append(createLogNode(entry));
    if (shouldFollow) {
      if (output) output.scrollTop = output.scrollHeight;
      newLogCount = 0;
    } else {
      followPaused = true;
      if (followControl) followControl.checked = false;
      newLogCount += 1;
    }
    updatePosition();
  }

  function clearReconnectTimer() {
    if (reconnectTimer != null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  }

  function closeSource() {
    clearReconnectTimer();
    if (eventSource) eventSource.close();
    eventSource = null;
  }

  function cancelPreflight() {
    openRequestId += 1;
    if (statusController) statusController.abort();
    statusController = null;
  }

  function resetLogState() {
    lastSeq = 0;
    newLogCount = 0;
    logEntries = [];
    onlyErrors = false;
    reconnectAttempts = 0;
    if (errorsControl) errorsControl.setAttribute("aria-pressed", "false");
    followPaused = false;
    if (followControl) followControl.checked = true;
    if (output) output.replaceChildren();
    syncExplainButton(false);
  }

  function finishStream(source, message, callbackName, payload) {
    if (eventSource !== source) return;
    var state = "idle";
    if (callbackName === "onDone") state = "done";
    else if (callbackName === "onError") state = "error";
    else if (callbackName === "onCanceled") state = "canceled";
    setTaskState(state);
    setConnectionStatus(message);
    closeSource();
    syncExplainButton(callbackName === "onError");
    var callback = callbacks[callbackName];
    if (typeof callback === "function") {
      try { callback(payload); } catch (error) { /* consumer callback error is not our concern */ }
    }
  }

  function scheduleReconnect(taskId, reasonStatus) {
    if (!isDrawerOpen() || activeTaskId !== String(taskId)) return;
    clearReconnectTimer();
    setConnectionStatus(reasonStatus || tt("drawer.reconnecting"));
    // Close the dead EventSource so the browser does not also auto-retry it.
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    var delay = Math.min(8000, 500 * Math.pow(2, Math.min(reconnectAttempts, 4)));
    reconnectAttempts += 1;
    reconnectTimer = setTimeout(function () {
      reconnectTimer = null;
      if (!isDrawerOpen() || activeTaskId !== String(taskId)) return;
      startStream(taskId);
    }, delay);
  }

  function startStream(taskId) {
    clearReconnectTimer();
    var after = Number.isFinite(lastSeq) && lastSeq > 0 ? lastSeq : 0;
    var source = new EventSource(
      "/api/task/" + encodeURIComponent(taskId) + "/stream?after=" + encodeURIComponent(String(after))
    );
    eventSource = source;
    source.onopen = function () {
      if (eventSource !== source) return;
      reconnectAttempts = 0;
      setTaskState("running");
      setConnectionStatus(tt("drawer.connected"), true);
    };
    source.onerror = function () {
      if (eventSource !== source) return;
      // CONNECTING: browser may still auto-retry; CLOSED: we must restart manually.
      if (source.readyState === EventSource.CLOSED) {
        scheduleReconnect(taskId, tt("drawer.reconnecting"));
      } else {
        setConnectionStatus(tt("drawer.reconnecting"));
      }
    };
    source.addEventListener("log", function (event) {
      if (eventSource !== source) return;
      var seq = Number(event.lastEventId);
      if (!Number.isFinite(seq) || seq <= lastSeq) return;
      lastSeq = seq;
      appendLog(event.data, seq);
      if (typeof callbacks.onLog === "function") {
        try { callbacks.onLog(event.data, seq); } catch (error) { /* consumer callback error is not our concern */ }
      }
    });
    source.addEventListener("progress", function (event) {
      if (eventSource !== source) return;
      try {
        var raw = JSON.parse(event.data) || {};
        if (typeof callbacks.onProgress === "function") {
          var pct = Number(raw.pct);
          callbacks.onProgress({
            pct: Number.isFinite(pct) ? Math.max(0, Math.min(100, pct)) : null,
            msg: raw.msg == null ? "" : String(raw.msg),
            phase: raw.phase == null ? "" : String(raw.phase),
            phase_label: raw.phase_label == null ? "" : String(raw.phase_label),
            phase_index: Number(raw.phase_index) || 0,
            phase_total: Number(raw.phase_total) || 0
          });
        }
      } catch (error) {
        setConnectionStatus(tt("drawer.invalid_progress"), true);
      }
    });
    source.addEventListener("done", function () { finishStream(source, tt("drawer.done"), "onDone"); });
    source.addEventListener("error_event", function (event) {
      if (eventSource !== source) return;
      if (event.data === "timeout") {
        // Server ends the stream after SSE_ABSOLUTE_TIMEOUT_SEC; resume from lastSeq.
        scheduleReconnect(taskId, tt("drawer.timeout"));
        return;
      }
      finishStream(source, tt("drawer.failed"), "onError", event.data);
    });
    source.addEventListener("canceled", function () { finishStream(source, tt("drawer.canceled"), "onCanceled"); });
  }

  async function loadStatusThenStream(taskId, requestId, controller) {
    try {
      var response = await fetch("/api/task/" + encodeURIComponent(taskId) + "/status", {
        signal: controller.signal,
        headers: { Accept: "application/json" }
      });
      if (requestId !== openRequestId || !isDrawerOpen()) return;
      if (response.status === 404) {
        setConnectionStatus(tt("drawer.missing"));
        if (output) output.textContent = tt("drawer.missing") + "\n";
        return;
      }
      if (!response.ok) throw new Error("HTTP " + response.status);
      if (typeof response.json === "function") {
        try {
          var payload = await response.json();
          if (requestId !== openRequestId || !isDrawerOpen()) return;
          if (payload && payload.status === "error") {
            setTaskState("error");
            syncExplainButton(true);
          }
        } catch (parseError) {
          /* status JSON is optional; still start the log stream */
        }
      }
    } catch (error) {
      if (requestId !== openRequestId || (error && error.name === "AbortError")) return;
      setConnectionStatus(tt("drawer.connect_failed"));
      if (output) output.textContent = tt("drawer.connect_failed_body");
      return;
    } finally {
      if (requestId === openRequestId) statusController = null;
    }
    if (requestId !== openRequestId || !isDrawerOpen()) return;
    startStream(taskId);
  }

  function open(taskId, options) {
    options = options || {};
    var hasTask = taskId != null && String(taskId) !== "";
    var tab = options.tab === "agent" || options.tab === "logs"
      ? options.tab
      : (hasTask ? "logs" : "agent");

    if (!hasTask) {
      previouslyFocused = document.activeElement;
      openDrawerPanel();
      setActiveTab(tab);
      suppressNextOutsideClick = true;
      setTimeout(function () { suppressNextOutsideClick = false; }, 0);
      return;
    }

    var nextId = String(taskId);
    if (isDrawerOpen() && activeTaskId === nextId) {
      setActiveTab(tab);
      suppressNextOutsideClick = true;
      setTimeout(function () { suppressNextOutsideClick = false; }, 0);
      return;
    }

    closeSource();
    cancelPreflight();
    var requestId = openRequestId;
    var controller = new AbortController();
    statusController = controller;
    activeTaskId = nextId;
    callbacks = {
      onProgress: options.onProgress,
      onDone: options.onDone,
      onError: options.onError,
      onCanceled: options.onCanceled,
      onLog: options.onLog
    };
    resetLogState();
    if (titleEl) titleEl.textContent = options.title || tt("drawer.title");
    setTaskState("running");
    setConnectionStatus(tt("drawer.connecting"));
    updatePosition();
    previouslyFocused = document.activeElement;
    openDrawerPanel();
    setActiveTab(tab);
    if (output) output.focus({ preventScroll: true });

    // Swallow the same click that triggered `open()` so the document-level
    // outside-click handler below does not immediately close the drawer again.
    suppressNextOutsideClick = true;
    setTimeout(function () { suppressNextOutsideClick = false; }, 0);

    loadStatusThenStream(nextId, requestId, controller);
  }

  function close() {
    closeSource();
    cancelPreflight();
    setTaskState("");
    beginCloseDrawerPanel();
    updateAgentNavPressed();
    var target = previouslyFocused && previouslyFocused.isConnected ? previouslyFocused : null;
    activeTaskId = null;
    callbacks = {};
    previouslyFocused = null;
    if (target) target.focus({ preventScroll: true });
  }

  function attachDock(host) {
    dockHost = host || null;
    updateMode();
  }

  function preferOverlay(enabled) {
    forceOverlay = enabled !== false;
    updateMode();
  }

  if (closeControl) closeControl.addEventListener("click", close);
  Array.prototype.forEach.call(tabButtons, function (button) {
    button.addEventListener("click", function () {
      setActiveTab(button.getAttribute("data-task-log-tab"));
    });
  });
  if (agentNav) {
    agentNav.addEventListener("click", function () {
      open(null, { tab: "agent" });
    });
  }
  if (explainControl) {
    explainControl.addEventListener("click", function () {
      setActiveTab("agent");
    });
  }
  if (agentForm) {
    agentForm.addEventListener("submit", function (event) {
      event.preventDefault();
    });
  }
  if (clearControl) {
    clearControl.addEventListener("click", function () {
      logEntries = [];
      if (output) output.replaceChildren();
      newLogCount = 0;
      updatePosition();
      if (statusEl) statusEl.textContent = tt("drawer.cleared");
    });
  }
  if (errorsControl) {
    errorsControl.addEventListener("click", function () {
      pauseAtCurrentViewport();
      var scrollTop = output ? output.scrollTop : 0;
      onlyErrors = !onlyErrors;
      errorsControl.setAttribute("aria-pressed", onlyErrors ? "true" : "false");
      renderLogEntries();
      if (output) output.scrollTop = scrollTop;
    });
  }
  if (copyControl) {
    copyControl.addEventListener("click", function () {
      pauseAtCurrentViewport();
      if (!navigator.clipboard || !navigator.clipboard.writeText) {
        if (statusEl) statusEl.textContent = tt("drawer.copy_unsupported");
        return;
      }
      var visible = onlyErrors
        ? logEntries.filter(function (entry) { return entry.isError; })
        : logEntries;
      navigator.clipboard.writeText(
        visible.map(function (entry) { return entry.message; }).join("\n")
      ).then(function () {
        if (statusEl) statusEl.textContent = tt("drawer.copied");
      }).catch(function () {
        if (statusEl) statusEl.textContent = tt("drawer.copy_failed");
      });
    });
  }
  if (followControl) followControl.addEventListener("change", function () { setFollow(followControl.checked); });
  if (latestControl) latestControl.addEventListener("click", function () { setFollow(true); });
  if (output) {
    output.addEventListener("scroll", function () {
      if (isAtBottom()) {
        if (followPaused) setFollow(true);
      } else if (!followPaused) {
        followPaused = true;
        if (followControl) followControl.checked = false;
        updatePosition();
      }
    }, { passive: true });
  }
  document.addEventListener("selectionchange", function () {
    if (!output) return;
    var selection = document.getSelection();
    if (!selection || selection.isCollapsed) return;
    if (output.contains(selection.anchorNode) || output.contains(selection.focusNode)) setFollow(false);
  });
  document.addEventListener("keydown", function (event) {
    trapDrawerFocus(event);
    if (event.key === "Escape" && isDrawerOpen()) close();
  });
  document.addEventListener("click", function (event) {
    if (suppressNextOutsideClick) {
      suppressNextOutsideClick = false;
      return;
    }
    if (!isDrawerOpen() || drawer.contains(event.target)) return;
    if (!isOverlayMode()) return;
    close();
  });
  if (overlayMedia.addEventListener) overlayMedia.addEventListener("change", updateMode);
  else overlayMedia.addListener(updateMode);

  // Dock into #task-log-dock when present (dashboard right_panel or base layout).
  var defaultDock = document.getElementById("task-log-dock");
  if (defaultDock) attachDock(defaultDock);
  else updateMode();

  window.TaskLogDrawer = {
    open: open,
    close: close,
    isOpen: isDrawerOpen,
    currentTaskId: function () { return activeTaskId; },
    attachDock: attachDock,
    preferOverlay: preferOverlay
  };
})();
