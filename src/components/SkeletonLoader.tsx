export function SkeletonLoader() {
  return (
    <div className="skeleton-card">
      <div className="skeleton-header">
        <div className="skeleton-dot" />
        <div className="skeleton-line w-24" />
        <div className="skeleton-line w-12" />
      </div>
      <div className="skeleton-body">
        <div className="skeleton-line w-full" />
        <div className="skeleton-line w-11/12" />
        <div className="skeleton-line w-4/5" />
      </div>
      <div className="skeleton-footer">
        <div className="skeleton-line w-32" />
        <div className="skeleton-line w-20" />
      </div>
    </div>
  );
}
