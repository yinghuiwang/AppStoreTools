(function () {
  "use strict";

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
  var connectionStatus = "等待选择任务";
  var closeTransitionHandler = null;
  var closeFallbackTimer = null;
  var backgroundInertEntries = null;
  var previouslyFocused = null;
  var suppressNextOutsideClick = false;

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

  function updatePosition() {
    if (!positionEl || !statusEl) return;
    if (newLogCount > 0) {
      positionEl.textContent = newLogCount + " 条未读";
      statusEl.textContent = "有 " + newLogCount + " 条新日志";
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

  function renderLogEntries() {
    if (!output) return;
    var fragment = document.createDocumentFragment();
    logEntries.forEach(function (entry) {
      if (!onlyErrors || entry.isError) fragment.append(document.createTextNode(entry.message + "\n"));
    });
    output.replaceChildren(fragment);
  }

  function appendLog(message, seq) {
    var shouldFollow = !followPaused && isAtBottom();
    var entry = { seq: seq, message: String(message), isError: isErrorLog(message) };
    logEntries.push(entry);
    if (output && (!onlyErrors || entry.isError)) output.append(document.createTextNode(entry.message + "\n"));
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

  function closeSource() {
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
    if (errorsControl) errorsControl.setAttribute("aria-pressed", "false");
    followPaused = false;
    if (followControl) followControl.checked = true;
    if (output) output.replaceChildren();
  }

  function finishStream(source, message, callbackName, payload) {
    if (eventSource !== source) return;
    setConnectionStatus(message);
    closeSource();
    var callback = callbacks[callbackName];
    if (typeof callback === "function") {
      try { callback(payload); } catch (error) { /* consumer callback error is not our concern */ }
    }
  }

  function startStream(taskId) {
    var source = new EventSource("/api/task/" + encodeURIComponent(taskId) + "/stream?after=0");
    eventSource = source;
    // EventSource automatically sends Last-Event-ID when it reconnects.
    source.onopen = function () {
      if (eventSource === source) setConnectionStatus("实时连接", true);
    };
    source.onerror = function () {
      if (eventSource === source) setConnectionStatus("连接中断，正在重连");
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
        var progress = JSON.parse(event.data);
        if (typeof callbacks.onProgress === "function") {
          var pct = Number(progress && progress.pct);
          var msg = progress && progress.msg == null ? "" : String(progress.msg);
          callbacks.onProgress(Number.isFinite(pct) ? Math.max(0, Math.min(100, pct)) : null, msg);
        }
      } catch (error) {
        setConnectionStatus("收到无效进度数据", true);
      }
    });
    source.addEventListener("done", function () { finishStream(source, "任务已完成", "onDone"); });
    source.addEventListener("error_event", function (event) {
      if (eventSource !== source) return;
      if (event.data === "timeout") {
        setConnectionStatus("连接超时，正在重连");
        return;
      }
      finishStream(source, "任务失败", "onError", event.data);
    });
    source.addEventListener("canceled", function () { finishStream(source, "任务已取消", "onCanceled"); });
  }

  async function loadStatusThenStream(taskId, requestId, controller) {
    try {
      var response = await fetch("/api/task/" + encodeURIComponent(taskId) + "/status", {
        signal: controller.signal,
        headers: { Accept: "application/json" }
      });
      if (requestId !== openRequestId || !isDrawerOpen()) return;
      if (response.status === 404) {
        setConnectionStatus("任务不存在或已被清理");
        if (output) output.textContent = "任务不存在或已被清理\n";
        return;
      }
      if (!response.ok) throw new Error("HTTP " + response.status);
    } catch (error) {
      if (requestId !== openRequestId || (error && error.name === "AbortError")) return;
      setConnectionStatus("连接失败，请关闭后重试");
      if (output) output.textContent = "无法连接任务日志，请关闭后重试。\n";
      return;
    } finally {
      if (requestId === openRequestId) statusController = null;
    }
    if (requestId !== openRequestId || !isDrawerOpen()) return;
    startStream(taskId);
  }

  function open(taskId, options) {
    options = options || {};
    closeSource();
    cancelPreflight();
    var requestId = openRequestId;
    var controller = new AbortController();
    statusController = controller;
    activeTaskId = String(taskId);
    callbacks = {
      onProgress: options.onProgress,
      onDone: options.onDone,
      onError: options.onError,
      onCanceled: options.onCanceled,
      onLog: options.onLog
    };
    resetLogState();
    if (titleEl) titleEl.textContent = options.title || "任务日志";
    setConnectionStatus("正在连接");
    updatePosition();
    previouslyFocused = document.activeElement;
    openDrawerPanel();
    if (output) output.focus({ preventScroll: true });

    // Swallow the same click that triggered `open()` so the document-level
    // outside-click handler below does not immediately close the drawer again.
    suppressNextOutsideClick = true;
    setTimeout(function () { suppressNextOutsideClick = false; }, 0);

    loadStatusThenStream(taskId, requestId, controller);
  }

  function close() {
    closeSource();
    cancelPreflight();
    beginCloseDrawerPanel();
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
  if (clearControl) {
    clearControl.addEventListener("click", function () {
      logEntries = [];
      if (output) output.replaceChildren();
      newLogCount = 0;
      updatePosition();
      if (statusEl) statusEl.textContent = "显示已清空";
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
        if (statusEl) statusEl.textContent = "浏览器不支持自动复制";
        return;
      }
      navigator.clipboard.writeText(output ? output.textContent : "").then(function () {
        if (statusEl) statusEl.textContent = "日志已复制";
      }).catch(function () {
        if (statusEl) statusEl.textContent = "复制失败，请手动选择";
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
