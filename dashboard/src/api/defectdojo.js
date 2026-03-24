export async function fetchFindings({ page = 1, severity, scan_type, limit = 20 } = {}) {
  const offset = (page - 1) * limit;
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (severity) params.set("severity", severity);
  if (scan_type) params.set("scan_type", scan_type);
  const res = await fetch(`/api/findings?${params}`);
  if (!res.ok) throw new Error("Failed to fetch findings");
  return res.json();
}

export async function fetchFindingsSummary() {
  const res = await fetch("/api/findings/summary");
  if (!res.ok) throw new Error("Failed to fetch findings summary");
  return res.json();
}
