export async function fetchHealth() {
  const res = await fetch("/api/health");
  if (!res.ok) throw new Error("Failed to fetch health");
  return res.json();
}

export async function fetchModels() {
  const res = await fetch("/api/models");
  if (!res.ok) throw new Error("Failed to fetch models");
  return res.json();
}

export async function fetchConfig() {
  const res = await fetch("/api/config");
  if (!res.ok) throw new Error("Failed to fetch config");
  return res.json();
}

export async function updateConfig(config) {
  const res = await fetch("/api/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config }),
  });
  if (!res.ok) throw new Error("Failed to update config");
  return res.json();
}

export async function fetchPrompts() {
  const res = await fetch("/api/prompts");
  if (!res.ok) throw new Error("Failed to fetch prompts");
  return res.json();
}

export async function fetchPrompt(name) {
  const res = await fetch(`/api/prompts/${name}`);
  if (!res.ok) throw new Error("Failed to fetch prompt");
  return res.json();
}

export async function updatePrompt(name, content) {
  const res = await fetch(`/api/prompts/${name}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error("Failed to update prompt");
  return res.json();
}
