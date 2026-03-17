import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchFindings } from "../api/defectdojo";
import FindingsTable from "../components/FindingsTable";

const SEVERITIES = ["All", "Critical", "High", "Medium", "Low", "Info"];
const SCAN_TYPES = ["All", "Semgrep", "Gitleaks", "Trivy", "Triage"];

export default function ScanResults() {
  const [page, setPage] = useState(1);
  const [severity, setSeverity] = useState("All");
  const [scanType, setScanType] = useState("All");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["findings", page, severity, scanType],
    queryFn: () =>
      fetchFindings({
        page,
        severity: severity === "All" ? undefined : severity,
        scan_type: scanType === "All" ? undefined : scanType,
      }),
  });

  const findings = data?.results || [];
  const total = data?.count || 0;
  const pageSize = 20;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-white">Scan Results</h2>
        <div className="flex gap-3">
          <select
            value={scanType}
            onChange={(e) => {
              setScanType(e.target.value);
              setPage(1);
            }}
            className="bg-panel border border-border rounded-lg px-3 py-2 text-sm text-gray-300 focus:outline-none focus:border-indigo-500"
          >
            {SCAN_TYPES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <select
            value={severity}
            onChange={(e) => {
              setSeverity(e.target.value);
              setPage(1);
            }}
            className="bg-panel border border-border rounded-lg px-3 py-2 text-sm text-gray-300 focus:outline-none focus:border-indigo-500"
          >
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
      </div>

      {isLoading && <p className="text-gray-500 text-sm">Loading findings...</p>}
      {isError && <p className="text-red-400 text-sm">Failed to load findings.</p>}

      <FindingsTable findings={findings} />

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-2">
          <p className="text-xs text-gray-500">{total} total findings</p>
          <div className="flex gap-2">
            <button
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
              className="px-3 py-1.5 rounded-lg text-sm bg-panel border border-border disabled:opacity-30 hover:bg-white/5 transition-colors"
            >
              Previous
            </button>
            <span className="px-3 py-1.5 text-sm text-gray-400">
              {page} / {totalPages}
            </span>
            <button
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
              className="px-3 py-1.5 rounded-lg text-sm bg-panel border border-border disabled:opacity-30 hover:bg-white/5 transition-colors"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
