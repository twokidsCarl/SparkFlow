import { GRID_SIZE, createInitialState, queueDirection, stepGame } from "./snakeLogic.js";
import {
  applyConfigToDocument,
  applyPatch,
  createConfig,
  loadConfigFromServer,
} from "./liveConfig.js";

const boardElement = document.querySelector("#board");
const scoreElement = document.querySelector("#score");
const stateElement = document.querySelector("#game-state");
const helpTextElement = document.querySelector("#help-text");
const pauseButton = document.querySelector("#pause-button");
const restartButton = document.querySelector("#restart-button");
const controlButtons = document.querySelectorAll("[data-direction]");
const messagesElement = document.querySelector("#messages");
const chatForm = document.querySelector("#chat-form");
const chatInput = document.querySelector("#chat-input");
const sendButton = document.querySelector("#send-button");
const chatStatusElement = document.querySelector("#chat-status");
const historyListElement = document.querySelector("#history-list");
const historyStatusElement = document.querySelector("#history-status");
const sparkDockElement = document.querySelector("#spark-dock");
const dockPanelElement = document.querySelector("#dock-panel");
const dockToggleElement = document.querySelector("#dock-toggle");
const CHAT_STORAGE_KEY = "spark-chat-state";
const HISTORY_UI_STORAGE_KEY = "spark-history-ui";
const DEFAULT_SPARK_BASE_URL = "http://127.0.0.1:5050";

const cells = [];
let gameState = createInitialState();
let isPaused = false;
let config = createConfig();
let tickHandle = null;
let liveEventSource = null;
let historyEntries = [];
let isDockExpanded = false;
let sparkBaseUrl = DEFAULT_SPARK_BASE_URL;
let activeTaskId = null;
let branchFromEntryId = null;
let collapsedTaskIds = loadCollapsedTaskIds();
let activeRunId = null;
const conversation = loadStoredConversation();

buildBoard();
renderMessages();
initialize();

window.addEventListener("keydown", (event) => {
  if (isSparkFocused(event.target)) {
    if (event.key === "Escape" && isDockExpanded) {
      event.preventDefault();
      collapseDock();
    }
    return;
  }

  const direction = getDirectionFromKey(event.key);

  if (direction) {
    event.preventDefault();
    gameState = queueDirection(gameState, direction);
    return;
  }

  if (event.key === " " || event.key.toLowerCase() === "p") {
    event.preventDefault();
    togglePause();
    return;
  }

  if (event.key.toLowerCase() === "r") {
    event.preventDefault();
    restartGame();
  }
});

pauseButton.addEventListener("click", () => {
  togglePause();
});

restartButton.addEventListener("click", () => {
  restartGame();
});

controlButtons.forEach((button) => {
  button.addEventListener("click", () => {
    gameState = queueDirection(gameState, button.dataset.direction);
  });
});

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  submitChat();
});

sparkDockElement.addEventListener(
  "keydown",
  (event) => {
    if (isDockExpanded) {
      event.stopPropagation();
    }
  },
  true,
);

dockToggleElement.addEventListener("click", () => {
  if (isDockExpanded) {
    collapseDock();
  } else {
    expandDock();
  }
});

sparkDockElement.addEventListener("focusout", (event) => {
  const nextTarget = event.relatedTarget;
  if (!isDockExpanded) {
    return;
  }
  if (nextTarget && sparkDockElement.contains(nextTarget)) {
    return;
  }
  window.setTimeout(() => {
    const active = document.activeElement;
    if (!active || !sparkDockElement.contains(active)) {
      collapseDock();
    }
  }, 0);
});

document.addEventListener("pointerdown", (event) => {
  if (!isDockExpanded) {
    return;
  }
  if (!sparkDockElement.contains(event.target)) {
    collapseDock();
  }
});

window.addEventListener("beforeunload", () => {
  window.clearTimeout(tickHandle);
  if (liveEventSource) {
    liveEventSource.close();
  }
});

function buildBoard() {
  const fragment = document.createDocumentFragment();

  for (let index = 0; index < GRID_SIZE * GRID_SIZE; index += 1) {
    const cell = document.createElement("div");
    cell.className = "cell";
    cell.setAttribute("role", "gridcell");
    fragment.appendChild(cell);
    cells.push(cell);
  }

  boardElement.appendChild(fragment);
}

let lastScore = 0;

function render() {
  for (const cell of cells) {
    cell.className = "cell";
  }

  if (gameState.food) {
    getCell(gameState.food.x, gameState.food.y).classList.add("food");
  }

  const ateFood = gameState.score > lastScore;

  gameState.snake.forEach((segment, index) => {
    const cell = getCell(segment.x, segment.y);
    cell.classList.add("snake");

    if (index === 0) {
      cell.classList.add("head");
      if (ateFood) {
        cell.classList.add("flash");
        cell.addEventListener("animationend", () => cell.classList.remove("flash"), { once: true });
      }
    }
  });

  if (ateFood) {
    boardElement.classList.add("board-flash");
    boardElement.addEventListener("animationend", () => boardElement.classList.remove("board-flash"), { once: true });
  }

  lastScore = gameState.score;

  scoreElement.textContent = String(gameState.score);
  stateElement.textContent = getStatusLabel();
  helpTextElement.textContent = config.copy.helpText;
  pauseButton.innerHTML = isPaused
    ? 'Resume <kbd>Space/P</kbd>'
    : 'Pause <kbd>Space/P</kbd>';
  updateSparkTheme();
}

function getCell(x, y) {
  return cells[y * GRID_SIZE + x];
}

function restartGame() {
  gameState = createInitialState();
  isPaused = false;
  render();
  scheduleNextTick();
}

function togglePause() {
  if (gameState.status === "game-over") {
    return;
  }

  isPaused = !isPaused;
  render();
  scheduleNextTick();
}

function getStatusLabel() {
  if (gameState.status === "game-over") {
    return "Game Over";
  }

  return isPaused ? "Paused" : "Running";
}

function getDirectionFromKey(key) {
  switch (key.toLowerCase()) {
    case "arrowup":
    case "w":
      return "up";
    case "arrowdown":
    case "s":
      return "down";
    case "arrowleft":
    case "a":
      return "left";
    case "arrowright":
    case "d":
      return "right";
    default:
      return null;
  }
}

function scheduleNextTick() {
  window.clearTimeout(tickHandle);

  if (isPaused || gameState.status !== "running") {
    return;
  }

  tickHandle = window.setTimeout(() => {
    gameState = stepGame(gameState);
    render();
    scheduleNextTick();
  }, config.gameplay.tickMs);
}

async function submitChat() {
  expandDock();

  const message = chatInput.value.trim();

  if (!message) {
    return;
  }

  const requestTaskId = activeTaskId ?? createTaskId();
  const runId = `run-${Date.now()}`;
  activeRunId = runId;
  activeTaskId = requestTaskId;
  persistChatState();

  conversation.push({ role: "user", content: message, kind: "message" });
  chatInput.value = "";
  renderMessages();
  setChatStatus("Thinking");
  setChatBusy(true);

  const assistantMessage = { role: "assistant", content: "", kind: "message" };
  conversation.push(assistantMessage);
  renderMessages();

  try {
    const response = await fetch(resolveSparkUrl("/api/chat"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message,
        conversation: conversation.slice(0, -1),
        taskId: requestTaskId,
        branchFromEntryId,
      }),
    });

    if (!response.ok || !response.body) {
      throw new Error("Request failed.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();

      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.trim()) {
          continue;
        }

        const event = JSON.parse(line);
        handleChatEvent(event, assistantMessage, runId);
      }
    }

    if (buffer.trim()) {
      handleChatEvent(JSON.parse(buffer), assistantMessage, runId);
    }
  } catch (error) {
    assistantMessage.content =
      "I could not apply that change right now. Check that both examples/snake/app_server.py and spark/server.py are running.";
    renderMessages();
    setChatStatus("Error");
  } finally {
    if (!assistantMessage.content.trim()) {
      assistantMessage.content = "No visible change was applied.";
      renderMessages();
    }

    setChatBusy(false);
    branchFromEntryId = null;
    persistChatState();

    if (chatStatusElement.textContent === "Thinking") {
      setChatStatus("Ready");
    }
  }
}

function handleChatEvent(event, assistantMessage, runId) {
  switch (event.type) {
    case "phase":
      upsertPhaseMessage(event, runId);
      setChatStatus(event.label);
      break;
    case "token":
      assistantMessage.content += event.text;
      renderMessages();
      break;
    case "source-edits":
      addActivityMessage(`Edited files: ${event.files.join(", ")}`);
      break;
    case "patch":
      config = applyPatch(config, event.patch);
      applyConfigToDocument(config);
      render();
      scheduleNextTick();
      break;
    case "status":
      if (shouldLogStatus(event.label)) {
        addActivityMessage(event.label);
      }
      setChatStatus(event.label);
      break;
    case "done":
      setChatStatus("Ready");
      break;
    default:
      break;
  }
}

function renderMessages() {
  persistChatState();

  messagesElement.replaceChildren(
    ...conversation.map((message) => {
      const article = document.createElement("article");
      article.className = `message ${message.role} ${message.kind ?? "message"}`;
      article.textContent = message.content;
      return article;
    }),
  );

  messagesElement.scrollTop = messagesElement.scrollHeight;
}

function setChatStatus(label) {
  chatStatusElement.textContent = label;
  persistChatState();
}

function setChatBusy(isBusy) {
  sendButton.disabled = isBusy;
  chatInput.disabled = isBusy;
}

async function initialize() {
  restorePostReloadNotice();
  renderMessages();
  sparkBaseUrl = await loadSparkBaseUrl();

  try {
    config = await loadConfigFromServer(resolveSparkUrl("/api/config"));
  } catch (error) {
    config = createConfig();
  }

  await refreshHistory();
  applyConfigToDocument(config);
  render();
  scheduleNextTick();
  connectLiveUpdates();
}

function connectLiveUpdates() {
  liveEventSource = new EventSource(resolveSparkUrl("/events"));

  liveEventSource.addEventListener("config-updated", async () => {
    try {
      config = await loadConfigFromServer(resolveSparkUrl("/api/config"));
      applyConfigToDocument(config);
      render();
      scheduleNextTick();
      setChatStatus("Updated");
      window.setTimeout(() => {
        if (chatStatusElement.textContent === "Updated") {
          setChatStatus("Ready");
        }
      }, 700);
    } catch (error) {
      setChatStatus("Sync Error");
    }
  });

  liveEventSource.addEventListener("history-updated", async () => {
    await refreshHistory();
  });

  liveEventSource.addEventListener("source-changed", () => {
    markPendingReload();
    setChatStatus("Reloading");
    window.location.reload();
  });

  liveEventSource.onerror = () => {
    setChatStatus("Disconnected");
  };
}

async function refreshHistory() {
  setHistoryStatus("Loading");

  try {
    const response = await fetch(resolveSparkUrl("/api/history"), { cache: "no-store" });

    if (!response.ok) {
      throw new Error("History request failed.");
    }

  historyEntries = await response.json();
  renderHistory();
  setHistoryStatus(historyEntries.length ? "Ready" : "Empty");
  } catch (error) {
    historyEntries = [];
    renderHistory();
    setHistoryStatus("Unavailable");
  }
}

function renderHistory() {
  const nodes = buildHistoryCanvas(historyEntries, collapsedTaskIds);

  if (!nodes.length) {
    const empty = document.createElement("p");
    empty.className = "history-empty";
    empty.textContent = "No saved versions yet.";
    historyListElement.replaceChildren(empty);
    return;
  }

  historyListElement.classList.add("history-canvas");
  historyListElement.replaceChildren(
    ...nodes.map((group) => {
      const item = document.createElement("article");
      item.className = "history-item";
      item.style.setProperty("--branch-depth", String(group.depth));
      if (group.depth > 0) {
        item.classList.add("branched");
      }
      if (group.collapsed) {
        item.classList.add("collapsed");
      }

      const meta = document.createElement("p");
      meta.className = "history-meta";
      meta.textContent = `${formatHistoryTime(group.updatedAt)} · ${group.sourceLabel}`;

      const prompt = document.createElement("p");
      prompt.className = "history-prompt";
      prompt.textContent = group.summary;

      const files = document.createElement("p");
      files.className = "history-files";
      files.textContent = summarizeHistoryGroup(group);

      const detail = document.createElement("p");
      detail.className = "history-files";
      detail.textContent = `${group.steps.length} edit${group.steps.length > 1 ? "s" : ""}`;

      const lane = document.createElement("div");
      lane.className = "history-lane";

      const branchLine = document.createElement("div");
      branchLine.className = "history-branch-line";

      const dot = document.createElement("div");
      dot.className = "history-dot";

      const body = document.createElement("div");
      body.className = "history-body";

      const header = document.createElement("div");
      header.className = "history-card-header";

      const actions = document.createElement("div");
      actions.className = "history-actions";

      if (group.branchFromTaskId) {
        const branch = document.createElement("p");
        branch.className = "history-branch-label";
        branch.textContent = `Branch from ${group.branchFromTaskId.slice(-4)}`;
        body.append(branch);
      }

      if (group.hasChildren) {
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "history-toggle";
        toggle.textContent = group.collapsed
          ? `Expand ${group.hiddenChildrenCount}`
          : "Collapse";
        toggle.addEventListener("click", () => {
          toggleTaskCollapsed(group.taskId);
        });
        actions.append(toggle);
      }

      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Rollback";
      button.addEventListener("click", () => {
        rollbackTo(group.latestEntryId);
      });
      actions.append(button);

      lane.append(branchLine, dot);
      header.append(meta, actions);
      body.append(header, prompt, files, detail);
      item.append(lane, body);
      return item;
    }),
  );
}

async function rollbackTo(id) {
  expandDock();
  setHistoryStatus("Rolling back");

  try {
    const response = await fetch(resolveSparkUrl("/api/rollback"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ id }),
    });

    if (!response.ok) {
      throw new Error("Rollback failed.");
    }

    activeTaskId = null;
    branchFromEntryId = id;
    addActivityMessage(`Rolled back to ${id}. New changes will branch from here.`);
    setHistoryStatus("Restored");
  } catch (error) {
    setHistoryStatus("Failed");
  }
}

function summarizeHistoryGroup(group) {
  const files = Array.from(group.files);
  const fileLabel = files.length ? files.join(", ") : "config only";
  return `Files: ${fileLabel}`;
}

function formatHistoryTime(value) {
  if (!value) {
    return "Unknown time";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString();
}

function setHistoryStatus(label) {
  historyStatusElement.textContent = label;
}

function updateSparkTheme() {
  const luminance = getColorLuminance(config.theme.bg);
  sparkDockElement.dataset.theme = luminance > 0.67 ? "light" : "dark";
}

function expandDock() {
  isDockExpanded = true;
  sparkDockElement.classList.remove("is-collapsed");
  dockToggleElement.setAttribute("aria-expanded", "true");
  window.setTimeout(() => {
    dockPanelElement.focus();
    chatInput.focus();
  }, 0);
}

function collapseDock() {
  isDockExpanded = false;
  sparkDockElement.classList.add("is-collapsed");
  dockToggleElement.setAttribute("aria-expanded", "false");
}

function addActivityMessage(content) {
  const lastMessage = conversation.at(-1);
  if (lastMessage?.role === "system" && lastMessage?.content === content) {
    return;
  }

  conversation.push({
    role: "system",
    content,
    kind: "activity",
  });
  renderMessages();
}

function upsertPhaseMessage(event, runId) {
  const content = formatPhaseContent(event);
  let existing = null;

  for (let index = conversation.length - 1; index >= 0; index -= 1) {
    const message = conversation[index];
    if (
      message.role === "system" &&
      message.kind === "phase" &&
      message.phase === event.phase &&
      message.runId === runId
    ) {
      existing = message;
      break;
    }
  }

  if (existing) {
    existing.content = content;
  } else {
    conversation.push({
      role: "system",
      kind: "phase",
      phase: event.phase,
      runId,
      content,
    });
  }

  renderMessages();
}

function shouldLogStatus(label) {
  return ["Thinking", "Applying", "Error", "Missing API Key"].includes(label);
}

function buildHistoryGroups(entries) {
  const groupsByTaskId = new Map();

  for (const entry of entries) {
    const taskId = entry.task_id ?? `legacy-${entry.id}`;
    let group = groupsByTaskId.get(taskId);

    if (!group) {
      group = {
        taskId,
        latestEntryId: entry.id,
        updatedAt: entry.created_at,
        summary: entry.summary || entry.reply || entry.prompt,
        sourceLabel: entry.source,
        files: new Set(),
        steps: [],
        branchFromTaskId: entry.branch_from_task_id ?? null,
      };
      groupsByTaskId.set(taskId, group);
    } else if (entry.created_at >= group.updatedAt) {
      group.latestEntryId = entry.id;
      group.updatedAt = entry.created_at;
      group.summary = entry.summary || entry.reply || entry.prompt;
      group.sourceLabel = entry.source;
    }

    group.steps.push(entry);

    for (const file of entry.changed_files ?? []) {
      group.files.add(file);
    }
  }

  const groups = Array.from(groupsByTaskId.values()).sort((a, b) =>
    b.updatedAt.localeCompare(a.updatedAt),
  );

  const depthCache = new Map();
  const groupMap = new Map(groups.map((group) => [group.taskId, group]));

  function getDepth(taskId) {
    if (depthCache.has(taskId)) {
      return depthCache.get(taskId);
    }

    const group = groupMap.get(taskId);
    if (!group || !group.branchFromTaskId || !groupMap.has(group.branchFromTaskId)) {
      depthCache.set(taskId, 0);
      return 0;
    }

    const depth = getDepth(group.branchFromTaskId) + 1;
    depthCache.set(taskId, depth);
    return depth;
  }

  return groups.map((group) => ({
    ...group,
    depth: getDepth(group.taskId),
  }));
}

function buildHistoryCanvas(entries, collapsedIds) {
  const groups = buildHistoryGroups(entries).map((group) => ({
    ...group,
    children: [],
  }));
  const groupMap = new Map(groups.map((group) => [group.taskId, group]));

  for (const group of groups) {
    if (group.branchFromTaskId && groupMap.has(group.branchFromTaskId)) {
      groupMap.get(group.branchFromTaskId).children.push(group);
    }
  }

  const sortByRecent = (left, right) => right.updatedAt.localeCompare(left.updatedAt);
  const roots = groups
    .filter((group) => !group.branchFromTaskId || !groupMap.has(group.branchFromTaskId))
    .sort(sortByRecent);

  for (const group of groups) {
    group.children.sort(sortByRecent);
  }

  const visibleNodes = [];

  function countDescendants(node) {
    return node.children.reduce((count, child) => count + 1 + countDescendants(child), 0);
  }

  function visit(node, depth) {
    const collapsed = collapsedIds.has(node.taskId);
    visibleNodes.push({
      ...node,
      depth,
      collapsed,
      hasChildren: node.children.length > 0,
      hiddenChildrenCount: collapsed ? countDescendants(node) : 0,
    });

    if (collapsed) {
      return;
    }

    for (const child of node.children) {
      visit(child, depth + 1);
    }
  }

  for (const root of roots) {
    visit(root, 0);
  }

  return visibleNodes;
}

async function loadSparkBaseUrl() {
  try {
    const response = await fetch("/app-config.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error("Config request failed.");
    }

    const config = await response.json();
    if (typeof config.sparkBaseUrl === "string" && config.sparkBaseUrl.trim()) {
      return config.sparkBaseUrl.replace(/\/$/, "");
    }
  } catch (error) {
    // Ignore and fall back to the default Spark URL.
  }

  return DEFAULT_SPARK_BASE_URL;
}

function resolveSparkUrl(path) {
  return `${sparkBaseUrl}${path}`;
}

function isSparkFocused(target) {
  if (!target) {
    return false;
  }
  return sparkDockElement.contains(target) || sparkDockElement.contains(document.activeElement);
}

function getColorLuminance(hex) {
  const normalized = String(hex || "").replace("#", "");
  if (normalized.length !== 6) {
    return 0;
  }

  const values = [0, 2, 4].map((index) => parseInt(normalized.slice(index, index + 2), 16) / 255);
  const linear = values.map((value) =>
    value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4,
  );

  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function formatPhaseContent(event) {
  const lines = [event.label];

  if (Array.isArray(event.files) && event.files.length) {
    lines.push(event.files.join(", "));
  }

  if (Array.isArray(event.configSections) && event.configSections.length) {
    lines.push(`Config: ${event.configSections.join(", ")}`);
  }

  return lines.join("\n");
}

function loadStoredConversation() {
  const fallback = [
    {
      role: "assistant",
      content:
        "I can update the page live. Describe what you want to change, and I will keep the chat history after reloads.",
    },
  ];

  try {
    const raw = window.localStorage.getItem(CHAT_STORAGE_KEY);
    if (!raw) {
      return fallback;
    }

    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed.conversation) || !parsed.conversation.length) {
      return fallback;
    }

    activeTaskId = parsed.activeTaskId ?? null;
    branchFromEntryId = parsed.branchFromEntryId ?? null;

    return parsed.conversation;
  } catch (error) {
    return fallback;
  }
}

function persistChatState() {
  try {
    window.localStorage.setItem(
      CHAT_STORAGE_KEY,
      JSON.stringify({
        conversation,
        status: chatStatusElement.textContent,
        activeTaskId,
        branchFromEntryId,
        pendingReload: readStoredState().pendingReload ?? null,
      }),
    );
  } catch (error) {
    // Ignore storage failures and keep the UI working.
  }
}

function loadCollapsedTaskIds() {
  try {
    const raw = window.localStorage.getItem(HISTORY_UI_STORAGE_KEY);
    if (!raw) {
      return new Set();
    }

    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed.collapsedTaskIds)) {
      return new Set();
    }

    return new Set(parsed.collapsedTaskIds);
  } catch (error) {
    return new Set();
  }
}

function persistHistoryUiState() {
  try {
    window.localStorage.setItem(
      HISTORY_UI_STORAGE_KEY,
      JSON.stringify({
        collapsedTaskIds: Array.from(collapsedTaskIds),
      }),
    );
  } catch (error) {
    // Ignore storage failures and keep the UI working.
  }
}

function toggleTaskCollapsed(taskId) {
  if (collapsedTaskIds.has(taskId)) {
    collapsedTaskIds.delete(taskId);
  } else {
    collapsedTaskIds.add(taskId);
  }

  persistHistoryUiState();
  renderHistory();
}

function readStoredState() {
  try {
    return JSON.parse(window.localStorage.getItem(CHAT_STORAGE_KEY) ?? "{}");
  } catch (error) {
    return {};
  }
}

function markPendingReload() {
  const state = readStoredState();
  try {
    window.localStorage.setItem(
      CHAT_STORAGE_KEY,
      JSON.stringify({
        conversation,
        status: "Reloading",
        activeTaskId,
        branchFromEntryId,
        pendingReload: {
          at: Date.now(),
          message: "The page reloaded after applying source changes.",
        },
      }),
    );
  } catch (error) {
    // Ignore storage failures and keep the UI working.
  }
}

function restorePostReloadNotice() {
  const state = readStoredState();
  if (!state.pendingReload) {
    return;
  }

  conversation.push({
    role: "assistant",
    content: state.pendingReload.message,
  });

  try {
    window.localStorage.setItem(
      CHAT_STORAGE_KEY,
      JSON.stringify({
        conversation,
        status: "Ready",
        activeTaskId,
        branchFromEntryId,
        pendingReload: null,
      }),
    );
  } catch (error) {
    // Ignore storage failures and keep the UI working.
  }
}

function createTaskId() {
  return `task-${Date.now()}`;
}
