(function () {
  "use strict";

  function tt(key, vars) {
    if (typeof window.t === "function") return window.t(key, vars);
    return key;
  }

  var root = document.getElementById("dashboard-root");
  if (!root) return;

  var summary = document.getElementById("dashboard-summary");
  var taskList = document.getElementById("dashboard-task-list");
  var runningSection = root.querySelector(".dashboard-running");
  var rangeControl = root.querySelector('[data-dashboard-filter="range"]');
  var profileControl = root.querySelector('[data-dashboard-filter="profile"]');
  var statusControl = root.querySelector('[data-dashboard-filter="status"]');
  var kindControl = root.querySelector('[data-dashboard-filter="kind"]');
  var refreshStatus = root.querySelector("[data-dashboard-refresh-status]");

  var state = window.__ASC_DASHBOARD__ || { metrics: {}, tasks: [] };
  var filters = {
    range: (rangeControl && rangeControl.querySelector('[aria-pressed="true"]') || {}).dataset?.value || "30d",
    profile: profileControl ? profileControl.value : "",
    status: statusControl ? statusControl.value : "",
    kind: kindControl ? kindControl.value : ""
  };
  var refreshController = null;
  var refreshRequest = 0;
  var pollTimer = null;

  function statusLabel(status) {
    var key = "index.status." + status;
    var label = tt(key);
    return label === key ? String(status || "--") : label;
  }

  function textElement(tag, className, value) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = value == null ? "" : String(value);
    return node;
  }

  function humanDuration(seconds) {
    var total = Math.max(0, Math.floor(Number(seconds) || 0));
    if (total < 60) return tt("index.duration.seconds", { n: total });
    if (total < 3600) return tt("index.duration.minutes", { n: Math.floor(total / 60) });
    var hours = Math.floor(total / 3600);
    var minutes = Math.floor((total % 3600) / 60);
    return minutes ? tt("index.duration.hours_minutes", { h: hours, m: minutes }) : tt("index.duration.hours", { n: hours });
  }

  function taskTitle(task) {
    return task.title || task.kind || tt("dashboard.unnamed_task");
  }

  function makeLogButton(task) {
    var button = textElement("button", "dashboard-log-button", tt("index.log"));
    button.type = "button";
    button.dataset.dashboardLogTask = String(task.id || "");
    button.setAttribute("aria-label", tt("index.view_log_aria", { title: taskTitle(task) }));
    return button;
  }

  function makeExplainButton(task) {
    var button = textElement("button", "dashboard-log-button", tt("drawer.explain_with_agent"));
    button.type = "button";
    button.setAttribute("data-open-agent-task", "");
    button.setAttribute("data-task-id", String(task.id || ""));
    button.style.marginLeft = "4px";
    return button;
  }

  function makeCancelButton(task) {
    var button = textElement("button", "dashboard-cancel-button", tt("index.cancel"));
    button.type = "button";
    button.dataset.dashboardCancelTask = String(task.id || "");
    button.setAttribute("aria-label", tt("index.cancel_aria", { title: taskTitle(task) }));
    if (task.cancel_requested) {
      button.disabled = true;
      button.textContent = tt("dashboard.canceling");
    }
    return button;
  }

  function makeRunningActions(task) {
    var actions = document.createElement("div");
    actions.className = "dashboard-running-task__actions";
    actions.append(makeLogButton(task), makeCancelButton(task));
    return actions;
  }

  async function cancelRunningTask(taskId, button) {
    if (!taskId) return;
    if (!window.confirm(tt("dashboard.confirm_cancel"))) return;
    if (button) {
      button.disabled = true;
      button.textContent = tt("dashboard.canceling");
    }
    try {
      var response = await fetch("/api/task/" + encodeURIComponent(taskId) + "/cancel", { method: "POST" });
      if (!response.ok) throw new Error("HTTP " + response.status);
    } catch (error) {
      if (button) {
        button.disabled = false;
        button.textContent = tt("index.cancel");
      }
      window.alert(tt("dashboard.cancel_failed"));
      return;
    }
    refreshDashboard();
  }

  function renderMetrics(metrics) {
    var cards = [
      ["dashboard-stat dashboard-stat--accent", tt("index.metric_saved"), humanDuration(metrics.saved_seconds), tt("index.metric_saved_hint")],
      ["dashboard-stat dashboard-stat--success", tt("index.metric_success"), metrics.success_rate == null ? "--" : metrics.success_rate + "%", tt("index.metric_completed", { n: metrics.completed_count || 0 })],
      ["dashboard-stat dashboard-stat--error", tt("index.metric_failed"), humanDuration(metrics.failed_seconds), tt("index.metric_failed_hint")],
      ["dashboard-stat dashboard-stat--info", tt("index.metric_running"), metrics.running_count || 0, tt("index.metric_running_hint")]
    ];
    summary.replaceChildren();
    cards.forEach(function (card) {
      var article = document.createElement("article");
      article.className = card[0];
      article.append(textElement("span", "dashboard-stat__label", card[1]));
      article.append(textElement("strong", "", card[2]));
      article.append(textElement("small", "", card[3]));
      summary.append(article);
    });
  }

  function renderRunning(tasks) {
    var running = tasks.filter(function (task) {
      return task.status === "pending" || task.status === "running";
    });
    var count = runningSection.querySelector(".dashboard-count");
    if (count) count.textContent = String(running.length);
    var oldList = runningSection.querySelector(".dashboard-running-list, .dashboard-empty-state");
    var container = document.createElement("div");
    if (!running.length) {
      container.className = "dashboard-empty-state";
      var mark = document.createElement("span");
      mark.className = "dashboard-empty-state__mark";
      mark.setAttribute("aria-hidden", "true");
      container.append(mark, textElement("p", "", tt("index.empty_running")));
    } else {
      container.className = "dashboard-running-list";
      running.forEach(function (task) {
        var article = document.createElement("article");
        article.className = "dashboard-running-task";
        article.dataset.taskId = String(task.id || "");

        var indicator = document.createElement("div");
        indicator.className = "dashboard-running-task__status";
        indicator.setAttribute("aria-hidden", "true");
        indicator.append(document.createElement("span"));

        var main = document.createElement("div");
        main.className = "dashboard-running-task__main";
        var heading = document.createElement("div");
        heading.append(textElement("strong", "", taskTitle(task)));
        heading.append(textElement("span", "", task.profile || tt("index.no_profile")));
        var progress = document.createElement("div");
        var pct = Math.max(0, Math.min(100, Number(task.progress && task.progress.pct) || 0));
        progress.className = "dashboard-progress";
        progress.setAttribute("role", "progressbar");
        progress.setAttribute("aria-label", tt("index.progress_aria", { title: taskTitle(task) }));
        progress.setAttribute("aria-valuemin", "0");
        progress.setAttribute("aria-valuemax", "100");
        progress.setAttribute("aria-valuenow", String(pct));
        var progressBar = document.createElement("span");
        progressBar.style.width = pct + "%";
        progress.append(progressBar);
        var progressMessage = task.progress && task.progress.msg;
        main.append(heading, progress, textElement("small", "", progressMessage || (task.status === "pending" ? tt("index.waiting") : tt("index.executing"))));
        article.append(indicator, main, makeRunningActions(task));
        container.append(article);
      });
    }
    if (oldList) oldList.replaceWith(container);
    else runningSection.append(container);
  }

  function renderTasks(tasks) {
    taskList.replaceChildren();
    tasks.slice(0, 20).forEach(function (task) {
      var row = document.createElement("tr");
      row.dataset.taskId = String(task.id || "");
      if (task.status === "error") row.className = "dashboard-row--error";
      else if (task.status === "running" || task.status === "pending") row.className = "dashboard-row--running";

      var identity = document.createElement("td");
      identity.append(textElement("strong", "", taskTitle(task)));
      identity.append(textElement("small", "", task.kind || ""));

      var statusCell = document.createElement("td");
      var known = ["done", "error", "canceled", "running", "pending"];
      var safeStatus = known.indexOf(task.status) !== -1 ? task.status : "unknown";
      var badge = document.createElement("span");
      badge.className = "dashboard-status dashboard-status--" + safeStatus;
      var dot = document.createElement("i");
      dot.setAttribute("aria-hidden", "true");
      badge.append(dot, document.createTextNode(statusLabel(task.status)));
      statusCell.append(badge);

      var profile = textElement("td", "dashboard-table__mono", task.profile || "--");
      var created = String(task.created_at || "").slice(0, 16).replace("T", " ") || "--";
      var started = textElement("td", "dashboard-table__mono", created);
      var duration = textElement("td", "dashboard-table__mono", task.duration_label || humanDuration(task.duration_seconds));
      var actions = document.createElement("td");
      actions.className = "dashboard-table__actions";
      actions.append(makeLogButton(task));
      if (task.status === "error") {
        actions.append(makeExplainButton(task));
      }
      var retryPaths = ["/metadata", "/build", "/whats-new", "/iap", "/urls", "/update"];
      if (task.status === "error" && retryPaths.indexOf(task.retry_path) !== -1) {
        var retry = textElement("a", "dashboard-retry-link", tt("index.retry"));
        retry.href = task.retry_path;
        actions.append(retry);
      }
      row.append(identity, statusCell, profile, started, duration, actions);
      taskList.append(row);
    });
    if (!tasks.length) {
      var emptyRow = document.createElement("tr");
      var emptyCell = textElement("td", "dashboard-table__empty", tt("index.empty_history"));
      emptyCell.colSpan = 6;
      emptyRow.append(emptyCell);
      taskList.append(emptyRow);
    }
  }

  function captureTaskFocus() {
    var active = document.activeElement;
    var section = active && active.closest && active.closest(".dashboard-running, .dashboard-history");
    if (!section || !root.contains(section)) return null;
    var task = active.closest("[data-task-id]");
    if (!task) return null;
    var action = null;
    if (active.matches("[data-dashboard-log-task]")) action = "log";
    if (active.matches("[data-dashboard-cancel-task]")) action = "cancel";
    if (active.matches("[data-open-agent-task]")) action = "explain";
    if (active.matches(".dashboard-retry-link")) action = "retry";
    if (!action) return null;
    return {
      taskId: task.dataset.taskId,
      action: action,
      section: section.classList.contains("dashboard-running") ? "running" : "history"
    };
  }

  function restoreTaskFocus(snapshot) {
    if (!snapshot) return;
    var section = root.querySelector(snapshot.section === "running" ? ".dashboard-running" : ".dashboard-history");
    var tasks = section ? section.querySelectorAll("[data-task-id]") : [];
    var task = null;
    for (var index = 0; index < tasks.length; index += 1) {
      if (tasks[index].dataset.taskId === snapshot.taskId) {
        task = tasks[index];
        break;
      }
    }
    var actionSelector = "[data-dashboard-log-task]";
    if (snapshot.action === "retry") actionSelector = ".dashboard-retry-link";
    if (snapshot.action === "cancel") actionSelector = "[data-dashboard-cancel-task]";
    if (snapshot.action === "explain") actionSelector = "[data-open-agent-task]";
    var target = task && task.querySelector(actionSelector);
    if (!target) {
      target = section && section.querySelector("h2");
      if (!target) target = root;
      target.setAttribute("tabindex", "-1");
    }
    target.focus({ preventScroll: true });
  }

  function renderDashboard(nextState) {
    var focusSnapshot = captureTaskFocus();
    state = nextState;
    var tasks = Array.isArray(state.tasks) ? state.tasks : [];
    renderMetrics(state.metrics || {});
    renderRunning(tasks);
    renderTasks(tasks);
    restoreTaskFocus(focusSnapshot);
    schedulePoll();
  }

  function hasActiveTasks() {
    return Number(state.metrics && state.metrics.active_count) > 0;
  }

  function schedulePoll() {
    if (pollTimer) window.clearTimeout(pollTimer);
    pollTimer = null;
    if (!hasActiveTasks()) return;
    pollTimer = window.setTimeout(function () {
      if (document.visibilityState === "visible") refreshDashboard();
      else schedulePoll();
    }, 3000);
  }

  async function refreshDashboard() {
    if (pollTimer) window.clearTimeout(pollTimer);
    pollTimer = null;
    if (refreshController) refreshController.abort();
    var controller = new AbortController();
    var requestId = ++refreshRequest;
    refreshController = controller;
    root.setAttribute("aria-busy", "true");
    if (refreshStatus) refreshStatus.textContent = tt("dashboard.refreshing");
    var query = new URLSearchParams(filters);
    try {
      var response = await fetch("/api/dashboard/summary?" + query.toString(), {
        signal: controller.signal,
        headers: { Accept: "application/json" }
      });
      if (!response.ok) throw new Error("HTTP " + response.status);
      var nextState = await response.json();
      if (requestId !== refreshRequest) return;
      renderDashboard(nextState);
      if (refreshStatus) refreshStatus.textContent = "";
    } catch (error) {
      if (requestId === refreshRequest && error.name !== "AbortError") {
        if (refreshStatus) refreshStatus.textContent = tt("dashboard.refresh_failed");
        schedulePoll();
      }
    } finally {
      if (requestId === refreshRequest) {
        refreshController = null;
        root.removeAttribute("aria-busy");
      }
    }
  }

  function updateTaskProgress(taskId, progress) {
    if (!progress || typeof progress !== "object") return;
    var pct = Number(progress.pct);
    if (!Number.isFinite(pct)) return;
    pct = Math.max(0, Math.min(100, pct));
    var message = progress.msg == null ? "" : String(progress.msg);
    var tasks = Array.isArray(state.tasks) ? state.tasks : [];
    tasks.forEach(function (task) {
      if (String(task.id) === String(taskId)) task.progress = { pct: pct, msg: message };
    });
    runningSection.querySelectorAll("[data-task-id]").forEach(function (card) {
      if (card.dataset.taskId !== String(taskId)) return;
      var progressBar = card.querySelector(".dashboard-progress");
      var fill = progressBar && progressBar.querySelector("span");
      var stage = card.querySelector(".dashboard-running-task__main > small");
      if (progressBar) progressBar.setAttribute("aria-valuenow", String(pct));
      if (fill) fill.style.width = pct + "%";
      if (stage && message) stage.textContent = message;
    });
  }

  function openLogs(taskId, trigger) {
    if (!window.TaskLogDrawer) return;
    var taskContainer = trigger.closest("[data-task-id]");
    var titleNode = taskContainer && taskContainer.querySelector("strong");
    var titleText = titleNode ? titleNode.textContent : "";
    TaskLogDrawer.open(taskId, {
      title: tt("dashboard.task_log_title", { title: titleText || tt("dashboard.task_fallback") }),
      onProgress: function (progress) {
        updateTaskProgress(taskId, progress);
      },
      onDone: function () { refreshDashboard(); },
      onError: function () { refreshDashboard(); },
      onCanceled: function () { refreshDashboard(); }
    });
  }

  rangeControl.addEventListener("click", function (event) {
    var button = event.target.closest("button[data-value]");
    if (!button || !rangeControl.contains(button)) return;
    rangeControl.querySelectorAll("button[data-value]").forEach(function (candidate) {
      candidate.setAttribute("aria-pressed", candidate === button ? "true" : "false");
    });
    filters.range = button.dataset.value || "30d";
    refreshDashboard();
  });
  profileControl.addEventListener("change", function () {
    filters.profile = profileControl.value;
    refreshDashboard();
  });
  statusControl.addEventListener("change", function () {
    filters.status = statusControl.value;
    refreshDashboard();
  });
  kindControl.addEventListener("change", function () {
    filters.kind = kindControl.value;
    refreshDashboard();
  });

  root.addEventListener("click", function (event) {
    var cancelButton = event.target.closest("[data-dashboard-cancel-task]");
    if (cancelButton && root.contains(cancelButton)) {
      event.preventDefault();
      cancelRunningTask(cancelButton.dataset.dashboardCancelTask, cancelButton);
      return;
    }
    var button = event.target.closest("[data-dashboard-log-task]");
    if (button && root.contains(button)) {
      openLogs(button.dataset.dashboardLogTask, button);
    }
  });
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible" && hasActiveTasks()) refreshDashboard();
  });

  schedulePoll();
}());
