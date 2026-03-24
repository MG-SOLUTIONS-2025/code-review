const severityColors = {
  Critical: "bg-red-500/20 text-red-400",
  High: "bg-orange-500/20 text-orange-400",
  Medium: "bg-yellow-500/20 text-yellow-400",
  Low: "bg-blue-500/20 text-blue-400",
  Info: "bg-gray-500/20 text-gray-400",
};

export default function FindingsTable({ findings }) {
  if (!findings?.length) {
    return <p className="text-gray-500 text-sm">No findings to display.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-gray-500">
            <th className="pb-3 pr-4 font-medium">Severity</th>
            <th className="pb-3 pr-4 font-medium">Title</th>
            <th className="pb-3 pr-4 font-medium">Status</th>
            <th className="pb-3 font-medium">Date</th>
          </tr>
        </thead>
        <tbody>
          {findings.map((f) => (
            <tr key={f.id} className="border-b border-border/50 hover:bg-white/[0.02]">
              <td className="py-3 pr-4">
                <span className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-medium ${severityColors[f.severity] || "text-gray-400"}`}>
                  {f.severity || "Unknown"}
                </span>
              </td>
              <td className="py-3 pr-4 text-gray-300 max-w-md truncate">{f?.title || "Untitled"}</td>
              <td className="py-3 pr-4">
                <span className={f.active ? "text-yellow-400" : "text-gray-500"}>
                  {f.active ? "Active" : "Resolved"}
                </span>
              </td>
              <td className="py-3 text-gray-500">{f?.date || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
