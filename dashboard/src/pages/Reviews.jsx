import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchReviews } from "../api/gitplatform";
import ReviewCard from "../components/ReviewCard";

const PAGE_SIZE = 20;
const STATUS_OPTIONS = ["all", "open", "closed", "merged"];

export default function Reviews() {
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["reviews", page],
    queryFn: () => fetchReviews(PAGE_SIZE, (page - 1) * PAGE_SIZE),
  });

  const allReviews = data?.reviews || [];

  const filtered = allReviews.filter((r) => {
    const matchesStatus = statusFilter === "all" || r.state === statusFilter;
    const q = searchQuery.toLowerCase();
    const matchesSearch =
      !q ||
      (r.title || "").toLowerCase().includes(q) ||
      (r.author || "").toLowerCase().includes(q);
    return matchesStatus && matchesSearch;
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-2xl font-bold text-white">Reviews</h2>
        <div className="flex gap-3">
          <input
            type="text"
            placeholder="Search title or author..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="bg-panel border border-border rounded-lg px-3 py-2 text-sm text-gray-300 placeholder-gray-600 focus:outline-none focus:border-indigo-500"
          />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-panel border border-border rounded-lg px-3 py-2 text-sm text-gray-300 focus:outline-none focus:border-indigo-500"
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s.charAt(0).toUpperCase() + s.slice(1)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {isLoading && <p className="text-gray-500 text-sm">Loading reviews...</p>}
      {isError && <p className="text-red-400 text-sm">Failed to load reviews.</p>}

      {!isLoading && filtered.length === 0 && (
        <p className="text-gray-500 text-sm">No reviews found.</p>
      )}

      <div className="space-y-3">
        {filtered.map((r) => (
          <ReviewCard key={`${r.platform}-${r.project_id}-${r.id}`} review={r} />
        ))}
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between pt-2">
        <p className="text-xs text-gray-500">{allReviews.length} loaded</p>
        <div className="flex gap-2">
          <button
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
            className="px-3 py-1.5 rounded-lg text-sm bg-panel border border-border disabled:opacity-30 hover:bg-white/5 transition-colors"
          >
            Previous
          </button>
          <span className="px-3 py-1.5 text-sm text-gray-400">Page {page}</span>
          <button
            disabled={allReviews.length < PAGE_SIZE}
            onClick={() => setPage((p) => p + 1)}
            className="px-3 py-1.5 rounded-lg text-sm bg-panel border border-border disabled:opacity-30 hover:bg-white/5 transition-colors"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
