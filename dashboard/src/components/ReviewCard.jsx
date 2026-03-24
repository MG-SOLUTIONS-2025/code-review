import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchReviewResult, triggerReview } from "../api/gitplatform";

function StatusBadge({ result, isLoading }) {
  if (isLoading) {
    return (
      <span className="bg-gray-500/20 text-gray-400 text-xs font-medium px-2.5 py-1 rounded-full">
        Checking…
      </span>
    );
  }
  if (!result || result.head_sha === null) {
    return (
      <span className="bg-gray-500/20 text-gray-400 text-xs font-medium px-2.5 py-1 rounded-full">
        Not reviewed
      </span>
    );
  }
  const hasIssues = result.needs_review_count > 0;
  return (
    <span
      className={`text-xs font-medium px-2.5 py-1 rounded-full ${
        hasIssues
          ? "bg-orange-500/20 text-orange-400"
          : "bg-green-500/20 text-green-400"
      }`}
    >
      {result.approved_count} approved · {result.needs_review_count} issues
    </span>
  );
}

export default function ReviewCard({ review }) {
  const platform = review.platform || "gitlab";
  const projectId = review.project_id || review.repo || "";
  const mrId = review.id;
  const [expanded, setExpanded] = useState(false);

  const safeUrl = (() => {
    try {
      const u = new URL(review.url);
      return ["http:", "https:"].includes(u.protocol) ? review.url : "#";
    } catch {
      return "#";
    }
  })();

  const queryClient = useQueryClient();
  const resultKey = ["reviewResult", platform, projectId, mrId];

  const { data: reviewResult, isLoading: resultLoading } = useQuery({
    queryKey: resultKey,
    queryFn: () => fetchReviewResult(platform, projectId, mrId),
    staleTime: 60_000,
    retry: 1,
  });

  const { mutate: runReview, isPending } = useMutation({
    mutationFn: () => triggerReview(platform, projectId, mrId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: resultKey });
    },
  });

  const files = reviewResult?.files || [];
  const isClosed = review.state === "closed" || review.state === "merged";

  return (
    <div className="bg-panel border border-border rounded-xl p-5 hover:border-indigo-500/40 transition-colors">
      {/* Header row */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <a
            href={safeUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="block"
          >
            <h3 className="text-sm font-semibold text-gray-200 truncate hover:text-indigo-400 transition-colors">
              {review.title}
            </h3>
          </a>
          <p className="text-xs text-gray-500 mt-1">
            by <span className="text-gray-400">{review.author}</span> &middot;{" "}
            {review.created_at ? new Date(review.created_at).toLocaleDateString() : "—"}
          </p>
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          <StatusBadge result={reviewResult} isLoading={resultLoading} />
          <button
            onClick={(e) => {
              e.stopPropagation();
              runReview();
            }}
            disabled={isPending || isClosed}
            title={isClosed ? "MR/PR is closed" : "Run AI review"}
            className="text-xs px-2.5 py-1 rounded-lg bg-indigo-600/20 text-indigo-400 border border-indigo-500/30
                       hover:bg-indigo-600/40 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            {isPending ? "Running…" : "Run Review"}
          </button>
        </div>
      </div>

      {/* Per-file breakdown (expandable) */}
      {files.length > 0 && (
        <div className="mt-3">
          <button
            onClick={() => setExpanded((v) => !v)}
            className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            <span>{expanded ? "▲" : "▼"}</span>
            <span>{files.length} files reviewed</span>
          </button>

          {expanded && (
            <div className="mt-2 overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border text-gray-500">
                    <th className="text-left px-3 py-2 font-medium">File</th>
                    <th className="text-left px-3 py-2 font-medium">Decision</th>
                    <th className="text-right px-3 py-2 font-medium">Issues</th>
                  </tr>
                </thead>
                <tbody>
                  {files.map((f) => (
                    <tr key={f.filename} className="border-b border-border/50 last:border-0">
                      <td className="px-3 py-2 text-gray-400 font-mono truncate max-w-xs">
                        {f.filename}
                      </td>
                      <td className="px-3 py-2">
                        {f.decision === "APPROVED" ? (
                          <span className="text-green-400">✅ Approved</span>
                        ) : (
                          <span className="text-orange-400">🔍 Needs review</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right text-gray-400">
                        {f.issue_count > 0 ? (
                          <span className="text-orange-400 font-medium">{f.issue_count}</span>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
