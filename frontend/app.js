const DEFAULT_API_BASE =
  window.location.protocol === "http:" || window.location.protocol === "https:"
    ? `${window.location.protocol}//${window.location.hostname || "127.0.0.1"}:8000`
    : "http://127.0.0.1:8000";

const state = {
  apiBase: DEFAULT_API_BASE,
  agentId: "",
  pollTimer: null,
  currentTask: null,
  reportMarkdown: "",
  openQuestions: [],
};

const elements = {
  form: document.querySelector("#review-form"),
  apiBase: document.querySelector("#api-base"),
  title: document.querySelector("#title"),
  requirementText: document.querySelector("#requirement-text"),
  targetUsers: document.querySelector("#target-users"),
  explicitConstraints: document.querySelector("#explicit-constraints"),
  supplementalContext: document.querySelector("#supplemental-context"),
  submitButton: document.querySelector("#submit-button"),
  resetButton: document.querySelector("#reset-button"),
  healthStatus: document.querySelector("#health-status"),
  agentStatus: document.querySelector("#agent-status"),
  taskStatusChip: document.querySelector("#task-status-chip"),
  taskStatus: document.querySelector("#task-status"),
  taskId: document.querySelector("#task-id"),
  clarityScore: document.querySelector("#clarity-score"),
  clarityRationale: document.querySelector("#clarity-rationale"),
  gateStatus: document.querySelector("#gate-status"),
  gateDetail: document.querySelector("#gate-detail"),
  toolSummary: document.querySelector("#tool-summary"),
  toolDetail: document.querySelector("#tool-detail"),
  riskDecisionSummary: document.querySelector("#risk-decision-summary"),
  riskDecisionDetail: document.querySelector("#risk-decision-detail"),
  elapsedSummary: document.querySelector("#elapsed-summary"),
  artifactDetail: document.querySelector("#artifact-detail"),
  statusMessage: document.querySelector("#status-message"),
  stageResults: document.querySelector("#stage-results"),
  markdownPreview: document.querySelector("#markdown-preview"),
  toolCalls: document.querySelector("#tool-calls"),
  errorPanel: document.querySelector("#error-panel"),
  downloadMarkdown: document.querySelector("#download-markdown"),
  followUpQuestions: document.querySelector("#follow-up-questions"),
  submitFollowUp: document.querySelector("#submit-follow-up"),
  followUpResult: document.querySelector("#follow-up-result"),
  followUpDiff: document.querySelector("#follow-up-diff"),
  stageTemplate: document.querySelector("#stage-template"),
  toolTemplate: document.querySelector("#tool-template"),
};

function splitLines(value) {
  return value
    .split(/\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function setStatusMessage(message) {
  elements.statusMessage.textContent = message;
}

function setTaskStatus(status) {
  elements.taskStatus.textContent = status;
  elements.taskStatusChip.textContent = status;
  document.body.dataset.taskStatus = status;
}

function showError(message) {
  elements.errorPanel.textContent = message;
  elements.errorPanel.classList.remove("hidden");
}

function clearError() {
  elements.errorPanel.textContent = "";
  elements.errorPanel.classList.add("hidden");
}

function disableDownloads() {
  elements.downloadMarkdown.disabled = true;
}

function enableDownloads() {
  elements.downloadMarkdown.disabled = !state.reportMarkdown;
}

function resetResults() {
  state.reportMarkdown = "";
  state.openQuestions = [];
  elements.taskId.textContent = "Task ID: -";
  elements.clarityScore.textContent = "-";
  elements.clarityRationale.textContent = "等待运行";
  elements.gateStatus.textContent = "-";
  elements.gateDetail.textContent = "未执行";
  elements.toolSummary.textContent = "-";
  elements.toolDetail.textContent = "无记录";
  elements.riskDecisionSummary.textContent = "-";
  elements.riskDecisionDetail.textContent = "等待运行";
  elements.elapsedSummary.textContent = "-";
  elements.artifactDetail.textContent = "等待审核文档";
  elements.markdownPreview.innerHTML = "";
  elements.markdownPreview.textContent = "任务完成后显示报告。";
  elements.markdownPreview.classList.add("empty-state");
  elements.stageResults.innerHTML = "";
  elements.stageResults.textContent = "任务运行后显示阶段记录。";
  elements.stageResults.classList.add("empty-state");
  elements.toolCalls.innerHTML = "";
  elements.toolCalls.textContent = "任务完成后显示工具调用详情。";
  elements.toolCalls.classList.add("empty-state");
  elements.followUpQuestions.innerHTML = "";
  elements.followUpQuestions.textContent = "任务完成后显示待确认问题。";
  elements.followUpQuestions.classList.add("empty-state");
  elements.submitFollowUp.disabled = true;
  elements.followUpResult.textContent = "提交澄清回答后显示 V2 复审结果。";
  elements.followUpResult.classList.add("empty-state");
  elements.followUpDiff.textContent = "重新审核后显示 V1 / V2 diff。";
  elements.followUpDiff.classList.add("empty-state");
  disableDownloads();
}

async function apiFetch(path, options = {}) {
  const apiBase = elements.apiBase.value.trim() || DEFAULT_API_BASE;
  state.apiBase = apiBase.replace(/\/$/, "");
  const response = await fetch(`${state.apiBase}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    let errorPayload = null;
    try {
      errorPayload = await response.json();
    } catch (error) {
      errorPayload = null;
    }
    const message = errorPayload?.error || `Request failed with status ${response.status}`;
    throw new Error(message);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

async function loadHealth() {
  try {
    await apiFetch("/health");
    elements.healthStatus.textContent = "在线";
  } catch (error) {
    elements.healthStatus.textContent = "不可达";
    showError(`API 健康检查失败：${error.message}`);
  }
}

async function loadAgents() {
  try {
    const payload = await apiFetch("/agents");
    if (payload.agents.length === 0) {
      elements.agentStatus.textContent = "未注册";
      return;
    }
    const agent = payload.agents[0];
    state.agentId = agent.agent_id;
    elements.agentStatus.textContent = agent.name;
  } catch (error) {
    elements.agentStatus.textContent = "加载失败";
    showError(`Agent 列表加载失败：${error.message}`);
  }
}

function renderMarkdown(markdown) {
  const lines = markdown.split("\n");
  let html = "";
  let inList = false;

  const closeList = () => {
    if (inList) {
      html += "</ul>";
      inList = false;
    }
  };

  lines.forEach((line) => {
    const safeLine = escapeHtml(line.trim());
    if (!safeLine) {
      closeList();
      return;
    }
    if (safeLine.startsWith("### ")) {
      closeList();
      html += `<h4>${safeLine.slice(4)}</h4>`;
      return;
    }
    if (safeLine.startsWith("## ")) {
      closeList();
      html += `<h3>${safeLine.slice(3)}</h3>`;
      return;
    }
    if (safeLine.startsWith("# ")) {
      closeList();
      html += `<h2>${safeLine.slice(2)}</h2>`;
      return;
    }
    if (safeLine.startsWith("- ")) {
      if (!inList) {
        html += "<ul>";
        inList = true;
      }
      html += `<li>${safeLine.slice(2)}</li>`;
      return;
    }
    closeList();
    html += `<p>${safeLine}</p>`;
  });

  closeList();
  return html || "<p>无可展示内容。</p>";
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderStageResults(stageResults) {
  elements.stageResults.innerHTML = "";
  elements.stageResults.classList.remove("empty-state");

  stageResults.forEach((stage) => {
    const node = elements.stageTemplate.content.firstElementChild.cloneNode(true);
    node.dataset.status = stage.status;
    node.querySelector(".timeline-stage").textContent = stage.stage;
    node.querySelector(".timeline-agent").textContent = stage.agent_id;
    node.querySelector(".timeline-status").textContent = `${stage.status} · ${stage.duration_ms} ms`;
    node.querySelector(".timeline-summary").textContent = stage.summary || "无阶段摘要。";
    node.querySelector(".timeline-tools").textContent =
      stage.tool_names && stage.tool_names.length > 0
        ? `Tools: ${stage.tool_names.join(", ")}`
        : "Tools: 无";
    elements.stageResults.appendChild(node);
  });
}

function renderToolCalls(toolCalls) {
  elements.toolCalls.innerHTML = "";
  elements.toolCalls.classList.remove("empty-state");

  toolCalls.forEach((record) => {
    const node = elements.toolTemplate.content.firstElementChild.cloneNode(true);
    node.dataset.success = String(record.success);
    node.querySelector(".tool-name").textContent = record.tool_name;
    node.querySelector(".tool-badge").textContent = record.success ? "success" : "fallback";
    const errorLabel = record.error ? ` · ${record.error.code}` : "";
    node.querySelector(".tool-meta").textContent =
      `${record.context.stage || "unknown"} · ${record.duration_ms} ms${errorLabel}`;
    elements.toolCalls.appendChild(node);
  });
}

function renderFollowUpPanel(task) {
  const artifacts = task.artifacts || {};
  const reportJson = artifacts.report_json || {};
  const openQuestions = Array.isArray(reportJson.open_questions) ? reportJson.open_questions : [];
  const isCompleted = task.status === "completed";
  state.openQuestions = openQuestions;

  elements.followUpQuestions.innerHTML = "";
  elements.followUpQuestions.classList.remove("empty-state");
  elements.submitFollowUp.disabled = !isCompleted || openQuestions.length === 0;

  if (openQuestions.length === 0) {
    elements.followUpQuestions.textContent = "当前报告没有待确认问题。";
    elements.followUpQuestions.classList.add("empty-state");
  } else {
    const previousAnswers = new Map(
      (artifacts.follow_up?.answers || []).map((item) => [item.question_id, item.answer])
    );
    const fragment = document.createDocumentFragment();
    openQuestions.forEach((question) => {
      const priority = String(question.priority || "medium").toLowerCase();
      const required = priority === "high";
      const item = document.createElement("article");
      item.className = "clarification-item";

      const title = document.createElement("div");
      title.className = "clarification-topline";

      const id = document.createElement("strong");
      id.textContent = `${question.question_id} · ${priority}`;

      const requirementBadge = document.createElement("span");
      requirementBadge.className = required ? "requirement-badge required" : "requirement-badge optional";
      requirementBadge.textContent = required ? "必须明确" : "建议明确";

      const text = document.createElement("p");
      text.textContent = question.question || "未返回问题内容。";

      const impact = document.createElement("small");
      impact.textContent = question.impact || "";

      const answerField = document.createElement("label");
      answerField.className = "field follow-up-answer-item";

      const answerLabel = document.createElement("span");
      answerLabel.textContent = `${question.question_id} 回答${required ? "（必填）" : "（选填）"}`;

      const answerInput = document.createElement("textarea");
      answerInput.dataset.questionId = question.question_id || "";
      answerInput.dataset.required = String(required);
      answerInput.rows = 3;
      answerInput.value = previousAnswers.get(question.question_id) || "";
      answerInput.placeholder = required ? "请明确回答该问题，作为 V2 复审依据。" : "如已有明确答案，可在这里补充。";
      answerInput.disabled = !isCompleted;

      title.append(id, requirementBadge);
      answerField.append(answerLabel, answerInput);
      item.append(title, text, impact, answerField);
      fragment.appendChild(item);
    });
    elements.followUpQuestions.appendChild(fragment);
  }

  const followUp = artifacts.follow_up;
  if (!followUp) {
    return;
  }

  elements.followUpResult.classList.remove("empty-state");
  elements.followUpResult.textContent =
    `V2 复审清晰度 ${followUp.clarity_score}/${followUp.metrics?.clarity_threshold ?? "-"}，` +
    `${followUp.gate_opened ? "已通过" : "未通过"}门禁，` +
    `回答 ${followUp.answered_question_count} 个问题。`;
  elements.followUpDiff.classList.remove("empty-state");
  elements.followUpDiff.textContent = followUp.diff_markdown || "V1 / V2 无文本差异。";
}

function parseFollowUpAnswers() {
  return Array.from(elements.followUpQuestions.querySelectorAll("textarea"))
    .map((input, index) => {
      const answer = input.value.trim();
      if (!answer) {
        return null;
      }
      const fallbackQuestion = state.openQuestions[index];
      return {
        question_id: input.dataset.questionId || fallbackQuestion?.question_id || `Q-${String(index + 1).padStart(3, "0")}`,
        answer,
      };
    })
    .filter(Boolean);
}

function getMissingRequiredFollowUpQuestions() {
  return Array.from(elements.followUpQuestions.querySelectorAll("textarea"))
    .map((input, index) => {
      if (input.dataset.required !== "true" || input.value.trim()) {
        return null;
      }
      const question = state.openQuestions[index];
      return question?.question_id || input.dataset.questionId || `Q-${String(index + 1).padStart(3, "0")}`;
    })
    .filter(Boolean);
}

function collectFollowUpAnswersForRequest() {
  const missingRequired = getMissingRequiredFollowUpQuestions();
  if (missingRequired.length > 0) {
    return {
      answers: [],
      error: `请先填写必须明确的问题：${missingRequired.join(", ")}`,
    };
  }
  return { answers: parseFollowUpAnswers(), error: "" };
}

function getDisplayReport(task) {
  const artifacts = task.artifacts || {};
  const followUp = artifacts.follow_up || {};
  if (followUp.report_markdown) {
    return {
      markdown: followUp.report_markdown,
      version: "v2",
    };
  }
  return {
    markdown: artifacts.report_markdown || task.output || "",
    version: "v1",
  };
}

function updateMetrics(task) {
  const artifacts = task.artifacts || {};
  const metadata = task.metadata || {};
  const clarity = artifacts.clarity || {};
  const toolCalls = artifacts.tool_calls || [];
  const metrics = artifacts.metrics || {};

  elements.taskId.textContent = `Task ID: ${task.task_id}`;
  elements.clarityScore.textContent =
    clarity.score !== undefined && clarity.threshold !== undefined ? `${clarity.score}/${clarity.threshold}` : "-";
  elements.clarityRationale.textContent = clarity.rationale || "暂无清晰度说明。";
  elements.gateStatus.textContent = artifacts.gate_opened ? "通过" : task.status === "completed" ? "未通过" : "-";
  elements.gateDetail.textContent = artifacts.gate_opened
    ? "允许进入方案预审"
    : task.status === "completed"
      ? "当前以澄清问题收敛为主"
      : "等待执行";

  if (toolCalls.length > 0) {
    const successCount = toolCalls.filter((record) => record.success).length;
    const failureCount = metrics.tool_failure_count ?? toolCalls.filter((record) => !record.success).length;
    elements.toolSummary.textContent = `${toolCalls.length} 次`;
    elements.toolDetail.textContent = `success ${successCount} / failed ${failureCount}`;
  } else {
    elements.toolSummary.textContent = "-";
    elements.toolDetail.textContent = "无记录";
  }

  elements.riskDecisionSummary.textContent = `${metadata.risk_count ?? metrics.risk_count ?? 0} / ${metadata.decision_count ?? metrics.decision_count ?? 0}`;
  elements.riskDecisionDetail.textContent = "风险数 / 决策数";

  const elapsedMs = metadata.elapsed_ms ?? metrics.elapsed_ms;
  elements.elapsedSummary.textContent = elapsedMs !== undefined ? `${elapsedMs} ms` : "-";
  const displayReport = getDisplayReport(task);
  elements.artifactDetail.textContent = displayReport.markdown
    ? `${displayReport.version.toUpperCase()} 审核文档可下载`
    : "等待审核文档";

  if (artifacts.stage_results) {
    renderStageResults(artifacts.stage_results);
  }
  if (toolCalls.length > 0) {
    renderToolCalls(toolCalls);
  }
  renderFollowUpPanel(task);

  if (task.status === "completed") {
    state.reportMarkdown = displayReport.markdown;

    elements.markdownPreview.innerHTML = renderMarkdown(state.reportMarkdown);
    elements.markdownPreview.classList.remove("empty-state");
    enableDownloads();

    const summary = metadata.summary || "任务已完成。";
    setStatusMessage(summary);
  }
}

function stopPolling() {
  if (state.pollTimer) {
    window.clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }
}

async function pollTask(taskId) {
  try {
    const task = await apiFetch(`/tasks/${taskId}`);
    state.currentTask = task;
    setTaskStatus(task.status);
    updateMetrics(task);

    if (task.status === "running" || task.status === "pending") {
      setStatusMessage("任务运行中，正在轮询状态。");
      state.pollTimer = window.setTimeout(() => pollTask(taskId), 1200);
      return;
    }

    if (task.status === "failed") {
      setStatusMessage("任务执行失败。");
      showError(task.error || "任务失败，但未返回具体错误。");
      return;
    }
  } catch (error) {
    showError(`查询任务状态失败：${error.message}`);
  }
}

async function handleSubmit(event) {
  event.preventDefault();
  clearError();
  stopPolling();
  resetResults();

  const requirementText = elements.requirementText.value.trim();
  if (!requirementText) {
    showError("需求文本不能为空。");
    return;
  }
  if (!state.agentId) {
    showError("当前没有可用 Agent，请先确认后端 API 是否已启动。");
    return;
  }

  elements.submitButton.disabled = true;
  setTaskStatus("submitting");
  setStatusMessage("正在创建任务并启动预审。");

  try {
    const payload = {
      title: elements.title.value.trim() || "需求预审任务",
      input: requirementText,
      agent_id: state.agentId,
      metadata: {
        title: elements.title.value.trim() || "需求预审任务",
        target_users: splitLines(elements.targetUsers.value),
        explicit_constraints: splitLines(elements.explicitConstraints.value),
        supplemental_context: splitLines(elements.supplementalContext.value),
      },
    };

    const createdTask = await apiFetch("/tasks", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.currentTask = createdTask;
    elements.taskId.textContent = `Task ID: ${createdTask.task_id}`;
    setTaskStatus(createdTask.status);

    await apiFetch(`/tasks/${createdTask.task_id}/run`, {
      method: "POST",
      body: JSON.stringify({ background: true }),
    });
    setTaskStatus("running");
    setStatusMessage("任务已启动，正在轮询执行结果。");
    pollTask(createdTask.task_id);
  } catch (error) {
    setTaskStatus("failed");
    setStatusMessage("任务创建或启动失败。");
    showError(error.message);
  } finally {
    elements.submitButton.disabled = false;
  }
}

async function handleFollowUpSubmit() {
  clearError();
  const { answers, error } = collectFollowUpAnswersForRequest();
  if (!state.currentTask?.task_id) {
    showError("请先完成一个需求预审任务。");
    return;
  }
  if (error) {
    showError(error);
    return;
  }
  if (answers.length === 0) {
    showError("请至少填写一条澄清回答。");
    return;
  }

  elements.submitFollowUp.disabled = true;
  setStatusMessage("正在基于澄清回答重新审核需求并生成 V2 报告。");
  try {
    const task = await apiFetch(`/tasks/${state.currentTask.task_id}/follow-up`, {
      method: "POST",
      body: JSON.stringify({ answers }),
    });
    state.currentTask = task;
    updateMetrics(task);
    setStatusMessage("V2 复审已完成，可查看 V1 / V2 diff。");
  } catch (error) {
    showError(`二轮复审失败：${error.message}`);
  } finally {
    elements.submitFollowUp.disabled = false;
  }
}

function downloadTextFile(filename, content, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function handleMarkdownDownload() {
  if (!state.reportMarkdown) {
    return;
  }
  const taskTitle = state.currentTask?.title || "requirement-pre-review-report";
  const reportVersion = state.currentTask?.artifacts?.follow_up?.report_markdown ? "v2" : "v1";
  const filename = `${taskTitle.replace(/\s+/g, "-").toLowerCase()}.md`;
  const versionedFilename = filename.replace(/\.md$/, `-${reportVersion}.md`);
  downloadTextFile(versionedFilename, state.reportMarkdown, "text/markdown;charset=utf-8");
  setStatusMessage(`${reportVersion.toUpperCase()} 审核文档已下载。`);
}

function handleReset() {
  stopPolling();
  clearError();
  state.currentTask = null;
  setTaskStatus("未开始");
  setStatusMessage("等待提交需求。");
  elements.form.reset();
  elements.apiBase.value = state.apiBase || DEFAULT_API_BASE;
  resetResults();
}

async function bootstrap() {
  elements.apiBase.value = DEFAULT_API_BASE;
  resetResults();
  await loadHealth();
  await loadAgents();
  if (!elements.errorPanel.textContent) {
    clearError();
  }
}

elements.form.addEventListener("submit", handleSubmit);
elements.resetButton.addEventListener("click", handleReset);
elements.downloadMarkdown.addEventListener("click", handleMarkdownDownload);
elements.submitFollowUp.addEventListener("click", handleFollowUpSubmit);

bootstrap();
