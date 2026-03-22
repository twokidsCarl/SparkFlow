export const DEFAULT_CONFIG = {
  theme: {
    bg: "#f5f1e8",
    panel: "#fffaf0",
    border: "#2f2a24",
    grid: "#d9cfbf",
    cell: "#f8f4ec",
    snake: "#2f6f49",
    snakeHead: "#1f4d33",
    food: "#b4432f",
    text: "#2f2a24",
    muted: "#6f6558",
  },
  gameplay: {
    tickMs: 140,
  },
  copy: {
    helpText: "Arrow keys or WASD to move. Press Space or P to pause.",
  },
};

export function createConfig() {
  return structuredClone(DEFAULT_CONFIG);
}

export function applyPatch(config, patch) {
  if (!patch || typeof patch !== "object") {
    return config;
  }

  const nextConfig = structuredClone(config);

  if (patch.theme) {
    Object.assign(nextConfig.theme, patch.theme);
  }

  if (patch.gameplay) {
    Object.assign(nextConfig.gameplay, patch.gameplay);
  }

  if (patch.copy) {
    Object.assign(nextConfig.copy, patch.copy);
  }

  return nextConfig;
}

export function applyConfigToDocument(config, documentRef = document) {
  const root = documentRef.documentElement;

  root.style.setProperty("--bg", config.theme.bg);
  root.style.setProperty("--panel", config.theme.panel);
  root.style.setProperty("--border", config.theme.border);
  root.style.setProperty("--grid", config.theme.grid);
  root.style.setProperty("--cell", config.theme.cell);
  root.style.setProperty("--snake", config.theme.snake);
  root.style.setProperty("--snake-head", config.theme.snakeHead);
  root.style.setProperty("--food", config.theme.food);
  root.style.setProperty("--text", config.theme.text);
  root.style.setProperty("--muted", config.theme.muted);
}

export async function loadConfigFromServer(url = "/api/config") {
  const response = await fetch(url, { cache: "no-store" });

  if (!response.ok) {
    throw new Error("Could not load config.");
  }

  const patch = await response.json();
  return applyPatch(createConfig(), patch);
}
