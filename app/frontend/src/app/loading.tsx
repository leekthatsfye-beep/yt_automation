export default function Loading() {
  return (
    <div
      className="flex items-center justify-center"
      style={{ minHeight: "60vh" }}
    >
      <div className="text-center">
        <div
          style={{
            width: 36,
            height: 36,
            border: "3px solid var(--border)",
            borderTopColor: "var(--accent)",
            borderRadius: "50%",
            margin: "0 auto 1rem",
            animation: "spin 0.8s linear infinite",
          }}
        />
        <p
          className="text-sm font-medium"
          style={{ color: "var(--text-tertiary)" }}
        >
          Loading…
        </p>
      </div>
    </div>
  );
}
