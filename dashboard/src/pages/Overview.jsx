import { useQuery } from "@tanstack/react-query";
import { fetchHealth } from "../api/llm";
import { fetchFindingsSummary } from "../api/defectdojo";
import { fetchReviews } from "../api/gitplatform";
import StatusCard from "../components/StatusCard";
import ReviewCard from "../components/ReviewCard";

const severityColors = {
  critical: "bg-red-500/20 text-red-400 border-red-500/30",
  high: "bg-orange-500/20 text-orange-400 border-orange-500/30",
  medium: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  low: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  info: "bg-gray-500/20 text-gray-400 border-gray-500/30",
};

export default function Overview() {
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth });
  const summary = useQuery({ queryKey: ["findings-summary"], queryFn: fetchFindingsSummary });
  const reviews = useQuery({ queryKey: ["reviews"], queryFn: fetchReviews });

  const services = health.data?.services || {};

  return (
    <div className="space-y-8">
      <h2 className="text-2xl font-bold text-white">Overview</h2>

      {/* Service Health */}
      <section>
        <h3 className="text-sm font-medium text-gray-500 uppercase tracking-wider mb-3">Service Health</h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {Object.entries(services).map(([name, info]) => (
            <StatusCard
              key={name}
              name={name}
              status={info.status}
              detail={info.engine ? `Engine: ${info.engine}` : info.model || undefined}
            />
          ))}
          {health.isLoading && <p className="text-gray-500 text-sm col-span-3">Loading...</p>}
          {health.isError && <p className="text-red-400 text-sm col-span-3">Failed to load health status.</p>}
        </div>
      </section>

      {/* Findings Summary */}
      <section>
        <h3 className="text-sm font-medium text-gray-500 uppercase tracking-wider mb-3">Findings Summary</h3>
        {summary.isLoading && <p className="text-gray-500 text-sm">Loading...</p>}
        {summary.isError && <p className="text-red-400 text-sm">Failed to load summary.</p>}
        {summary.data && (
          <div className="flex flex-wrap gap-3">
            {Object.entries(summary.data.severity_counts || {}).map(([sev, count]) => (
              <div
                key={sev}
                className={`border rounded-xl px-5 py-3 text-center min-w-[100px] ${severityColors[sev] || severityColors.info}`}
              >
                <p className="text-2xl font-bold">{count}</p>
                <p className="text-xs capitalize mt-0.5">{sev}</p>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Recent Reviews */}
      <section>
        <h3 className="text-sm font-medium text-gray-500 uppercase tracking-wider mb-3">Recent Reviews</h3>
        {reviews.isLoading && <p className="text-gray-500 text-sm">Loading...</p>}
        {reviews.isError && <p className="text-red-400 text-sm">Failed to load reviews.</p>}
        <div className="space-y-3">
          {reviews.data?.reviews?.slice(0, 5).map((r) => (
            <ReviewCard key={r.id} review={r} />
          ))}
        </div>
      </section>
    </div>
  );
}
