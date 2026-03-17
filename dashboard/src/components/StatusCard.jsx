export default function StatusCard({ name, status, detail }) {
  const isUp = status === "ok" || status === "healthy" || status === "running";
  return (
    <div className="bg-panel border border-border rounded-xl p-5">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-medium text-gray-300 capitalize">{name}</h3>
        <span className={`inline-block w-2.5 h-2.5 rounded-full ${isUp ? "bg-emerald-400" : "bg-red-400"}`} />
      </div>
      <p className={`text-lg font-semibold ${isUp ? "text-emerald-400" : "text-red-400"}`}>
        {isUp ? "Online" : "Offline"}
      </p>
      {detail && <p className="text-xs text-gray-500 mt-1">{detail}</p>}
    </div>
  );
}
