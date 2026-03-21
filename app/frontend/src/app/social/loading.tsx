export default function SocialLoading() {
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
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div
          className="rounded-2xl"
          style={{
            height: 400,
            background: "var(--bg-card)",
            border: "1px solid var(--glass-border)",
          }}
        />
        <div
          className="rounded-2xl"
          style={{
            height: 400,
            background: "var(--bg-card)",
            border: "1px solid var(--glass-border)",
          }}
        />
      </div>
    </div>
  );
}
