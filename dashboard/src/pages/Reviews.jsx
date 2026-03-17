import { useQuery } from "@tanstack/react-query";
import { fetchReviews } from "../api/gitplatform";
import ReviewCard from "../components/ReviewCard";

export default function Reviews() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["reviews"],
    queryFn: fetchReviews,
  });

  const reviews = data?.reviews || [];

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-white">Reviews</h2>

      {isLoading && <p className="text-gray-500 text-sm">Loading reviews...</p>}
      {isError && <p className="text-red-400 text-sm">Failed to load reviews.</p>}

      {!isLoading && reviews.length === 0 && (
        <p className="text-gray-500 text-sm">No reviews found.</p>
      )}

      <div className="space-y-3">
        {reviews.map((r) => (
          <ReviewCard key={r.id} review={r} />
        ))}
      </div>
    </div>
  );
}
