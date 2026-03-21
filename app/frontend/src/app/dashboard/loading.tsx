export default function DashboardLoading() {
  return (
    <div className="animate-pulse" style={{ padding: "1rem 0" }}>
      {/* Header skeleton */}
      <div
        className="rounded-2xl mb-6"
        style={{
          height: 80,
          background: "var(--bg-card)",
          border: "1px solid var(--glass-border)",
        }}
      />

      {/* Metric cards skeleton */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {[...Array(4)].map((_, i) => (
          <div
            key={i}
            className="rounded-2xl"
            style={{
              height: 100,
              background: "var(--bg-card)",
              border: "1px solid var(--glass-border)",
            }}
          />
        ))}
      </div>

      {/* Content skeleton */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div
          className="rounded-2xl"
          style={{
            height: 300,
            background: "var(--bg-card)",
            border: "1px solid var(--glass-border)",
          }}
        />
        <div
          className="rounded-2xl"
          style={{
            height: 300,
            background: "var(--bg-card)",
            border: "1px solid var(--glass-border)",
          }}
        />
      </div>
    </div>
  );
}
