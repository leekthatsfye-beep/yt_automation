import { Skeleton } from "@/components/ui/skeleton";

export default function DjLoading() {
  return (
    <div className="animate-fade-in">
      {/* Header */}
      <div className="page-header">
        <Skeleton className="h-7 w-32 mb-2" />
        <Skeleton className="h-4 w-64" />
      </div>

      {/* Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="p-5 rounded-2xl"
            style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}
          >
            <Skeleton className="w-8 h-8 rounded-lg mb-3" />
            <Skeleton className="h-8 w-16 mb-1" />
            <Skeleton className="h-3 w-20" />
          </div>
        ))}
      </div>

      {/* Table */}
      <div
        className="rounded-2xl p-6 space-y-4"
        style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}
      >
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full rounded-lg" />
        ))}
      </div>
    </div>
  );
}
