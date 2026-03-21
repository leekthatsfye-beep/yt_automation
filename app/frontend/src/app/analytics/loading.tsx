export default function AnalyticsLoading() {
  return (
    <div className="animate-pulse" style={{ padding: "1rem 0" }}>
      <div
        className="rounded-2xl mb-6"
        style={{
          height: 80,
          background: "var(--bg-card)",
          border: "1px solid var(--glass-border)",
        }}
      />
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
      <div
        className="rounded-2xl"
        style={{
          height: 350,
          background: "var(--bg-card)",
          border: "1px solid var(--glass-border)",
        }}
      />
    </div>
  );
}
