(function () {
  "use strict";

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

  var STATUS_LABELS = {
    done: "成功",
    error: "失败",
    canceled: "已取消",
    running: "运行中",
    pending: "等待中"
  };

  function textElement(tag, className, value) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = value == null ? "" : String(value);
    return node;
  }

  function humanDuration(seconds) {
    var total = Math.max(0, Math.floor(Number(seconds) || 0));
    if (total < 60) return total + " 秒";
    if (total < 3600) return Math.floor(total / 60) + " 分钟";
    var hours = Math.floor(total / 3600);
    var minutes = Math.floor((total % 3600) / 60);
    return hours + " 小时" + (minutes ? " " + minutes + " 分钟" : "");
  }

  function taskTitle(task) {
    return task.title || task.kind || "未命名任务";
  }

  function makeLogButton(task) {
    var button = textElement("button", "dashboard-log-button", "日志");
    button.type = "button";
    button.dataset.dashboardLogTask = String(task.id || "");
    button.setAttribute("aria-label", "查看" + taskTitle(task) + "日志");
    return button;
  }

  function makeCancelButton(task) {
    var button = textElement("button", "dashboard-cancel-button", "终止");
    button.type = "button";
    button.dataset.dashboardCancelTask = String(task.id || "");
    button.setAttribute("aria-label", "终止" + taskTitle(task));
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
    if (!window.confirm("确定要终止该任务吗？已完成的 App Store Connect 操作不会自动回滚。")) return;
    if (button) {
      button.disabled = true;
      button.textContent = "终止中...";
    }
    try {
      var response = await fetch("/api/task/" + encodeURIComponent(taskId) + "/cancel", { method: "POST" });
      if (!response.ok) throw new Error("HTTP " + response.status);
    } catch (error) {
      if (button) {
        button.disabled = false;
        button.textContent = "终止";
      }
      window.alert("终止请求发送失败，请稍后重试");
      return;
    }
    refreshDashboard();
  }

  function renderMetrics(metrics) {
    var cards = [
      ["dashboard-stat dashboard-stat--accent", "预计节省时间", humanDuration(metrics.saved_seconds), "相对手动操作基准"],
      ["dashboard-stat dashboard-stat--success", "任务成功率", metrics.success_rate == null ? "--" : metrics.success_rate + "%", (metrics.completed_count || 0) + " 个已结束任务"],
      ["dashboard-stat dashboard-stat--error", "失败投入时间", humanDuration(metrics.failed_seconds), "失败与取消任务耗时"],
      ["dashboard-stat dashboard-stat--info", "正在执行", metrics.running_count || 0, "运行中与等待中任务"]
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
      container.append(mark, textElement("p", "", "当前没有执行中的任务"));
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
        heading.append(textElement("span", "", task.profile || "未指定 App"));
        var progress = document.createElement("div");
        var pct = Math.max(0, Math.min(100, Number(task.progress && task.progress.pct) || 0));
        progress.className = "dashboard-progress";
        progress.setAttribute("role", "progressbar");
        progress.setAttribute("aria-label", taskTitle(task) + "进度");
        progress.setAttribute("aria-valuemin", "0");
        progress.setAttribute("aria-valuemax", "100");
        progress.setAttribute("aria-valuenow", String(pct));
        var progressBar = document.createElement("span");
        progressBar.style.width = pct + "%";
        progress.append(progressBar);
        var progressMessage = task.progress && task.progress.msg;
        main.append(heading, progress, textElement("small", "", progressMessage || (task.status === "pending" ? "等待执行" : "正在执行")));
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

      var identity = document.createElement("td");
      identity.append(textElement("strong", "", taskTitle(task)));
      identity.append(textElement("small", "", task.kind || ""));

      var statusCell = document.createElement("td");
      var safeStatus = Object.prototype.hasOwnProperty.call(STATUS_LABELS, task.status) ? task.status : "unknown";
      var badge = document.createElement("span");
      badge.className = "dashboard-status dashboard-status--" + safeStatus;
      var dot = document.createElement("i");
      dot.setAttribute("aria-hidden", "true");
      badge.append(dot, document.createTextNode(STATUS_LABELS[task.status] || String(task.status || "--")));
      statusCell.append(badge);

      var profile = textElement("td", "dashboard-table__mono", task.profile || "--");
      var created = String(task.created_at || "").slice(0, 16).replace("T", " ") || "--";
      var started = textElement("td", "dashboard-table__mono", created);
      var duration = textElement("td", "dashboard-table__mono", task.duration_label || humanDuration(task.duration_seconds));
      var actions = document.createElement("td");
      actions.className = "dashboard-table__actions";
      actions.append(makeLogButton(task));
      var retryPaths = ["/metadata", "/build", "/whats-new", "/iap", "/urls", "/update"];
      if (task.status === "error" && retryPaths.indexOf(task.retry_path) !== -1) {
        var retry = textElement("a", "dashboard-retry-link", "重试");
        retry.href = task.retry_path;
        actions.append(retry);
      }
      row.append(identity, statusCell, profile, started, duration, actions);
      taskList.append(row);
    });
    if (!tasks.length) {
      var emptyRow = document.createElement("tr");
      var emptyCell = textElement("td", "dashboard-table__empty", "所选范围内暂无任务记录");
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
    if (refreshStatus) refreshStatus.textContent = "正在刷新…";
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
        if (refreshStatus) refreshStatus.textContent = "刷新失败，保留上次结果";
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
      title: (titleText || "任务") + " 日志",
      onProgress: function (pct, msg) {
        updateTaskProgress(taskId, { pct: pct, msg: msg });
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

  if (window.TaskLogDrawer) {
    var dock = document.getElementById("task-log-dock");
    TaskLogDrawer.attachDock(dock);
  }

  schedulePoll();
}());
