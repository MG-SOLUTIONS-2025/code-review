export async function fetchReviews(limit = 20, offset = 0) {
  const params = new URLSearchParams({ limit, offset });
  const res = await fetch(`/api/reviews?${params}`);
  if (!res.ok) throw new Error("Failed to fetch reviews");
  return res.json();
}

export async function triggerReview(platform, projectId, mrId, force = false) {
  const res = await fetch("/api/reviews/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ platform, project_id: String(projectId), mr_id: mrId, force }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to trigger review");
  }
  return res.json();
}

export async function fetchReviewResult(platform, projectId, mrId) {
  const params = new URLSearchParams({ project_id: String(projectId), mr_id: mrId });
  const res = await fetch(`/api/reviews/result?${params}`);
  if (!res.ok) throw new Error("Failed to fetch review result");
  return res.json();
}
