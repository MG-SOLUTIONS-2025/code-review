export default function ReviewCard({ review }) {
  return (
    <a
      href={review.url}
      target="_blank"
      rel="noopener noreferrer"
      className="block bg-panel border border-border rounded-xl p-5 hover:border-indigo-500/40 transition-colors"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-gray-200 truncate">{review.title}</h3>
          <p className="text-xs text-gray-500 mt-1">
            by <span className="text-gray-400">{review.author}</span> &middot;{" "}
            {new Date(review.created_at).toLocaleDateString()}
          </p>
        </div>
        <span className="flex-shrink-0 bg-indigo-500/20 text-indigo-400 text-xs font-medium px-2.5 py-1 rounded-full">
          {review.comments?.length || 0} comments
        </span>
      </div>
    </a>
  );
}
