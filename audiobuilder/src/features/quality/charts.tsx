// charts.tsx — inline SVG chart components (no external chart library)

export const BAR_COLORS = [
  "#6366f1", "#8b5cf6", "#ec4899", "#f59e0b", "#10b981",
  "#3b82f6", "#ef4444", "#14b8a6", "#f97316", "#84cc16",
];

// ---------------------------------------------------------------------------
// Inline SVG chart helpers
// ---------------------------------------------------------------------------

interface BarChartProps {
  data: { label: string; value: number }[];
  color?: string;
  height?: number;
}

export function BarChartSVG({ data, color = "#6366f1", height = 160 }: BarChartProps) {
  if (data.length === 0) {
    return <p className="text-xs text-secondary-500">No data.</p>;
  }
  const maxVal = Math.max(...data.map((d) => d.value), 1);
  const barW = Math.max(8, Math.floor(280 / data.length) - 4);
  const svgW = data.length * (barW + 4) + 40;

  return (
    <div className="overflow-x-auto">
      <svg
        width={svgW}
        height={height + 30}
        aria-label="Bar chart"
        role="img"
      >
        {data.map((d, i) => {
          const barH = Math.max(2, Math.round((d.value / maxVal) * height));
          const x = 36 + i * (barW + 4);
          const y = height - barH;
          return (
            <g key={i}>
              <rect
                x={x}
                y={y}
                width={barW}
                height={barH}
                fill={color}
                rx={2}
                aria-label={`${d.label}: ${d.value}`}
              />
              <text
                x={x + barW / 2}
                y={height + 14}
                textAnchor="middle"
                fontSize={9}
                fill="currentColor"
                className="text-secondary-500"
              >
                {d.label.length > 6 ? d.label.slice(0, 5) + "…" : d.label}
              </text>
            </g>
          );
        })}
        {/* Y-axis labels */}
        <text x={32} y={8} textAnchor="end" fontSize={9} fill="currentColor" className="text-secondary-400">
          {maxVal}
        </text>
        <text x={32} y={height} textAnchor="end" fontSize={9} fill="currentColor" className="text-secondary-400">
          0
        </text>
        <line x1={36} y1={0} x2={36} y2={height} stroke="currentColor" strokeWidth={1} opacity={0.2} />
      </svg>
    </div>
  );
}

interface PieChartProps {
  data: { label: string; value: number }[];
  size?: number;
}

export function PieChartSVG({ data, size = 140 }: PieChartProps) {
  if (data.length === 0) {
    return <p className="text-xs text-secondary-500">No data.</p>;
  }
  const total = data.reduce((s, d) => s + d.value, 0);
  if (total === 0) return <p className="text-xs text-secondary-500">No data.</p>;

  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 8;

  // Build slices without mutating a variable across iterations
  const slices = data.map((d, i) => {
    const precedingAngle = data
      .slice(0, i)
      .reduce((sum, prev) => sum + (prev.value / total) * 2 * Math.PI, -Math.PI / 2);
    const angle = (d.value / total) * 2 * Math.PI;
    const startAngle = precedingAngle;
    const endAngle = startAngle + angle;
    const x1 = cx + r * Math.cos(startAngle);
    const y1 = cy + r * Math.sin(startAngle);
    const x2 = cx + r * Math.cos(endAngle);
    const y2 = cy + r * Math.sin(endAngle);
    const largeArc = angle > Math.PI ? 1 : 0;
    const path = `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2} Z`;
    const midAngle = startAngle + angle / 2;
    const lx = cx + r * 0.65 * Math.cos(midAngle);
    const ly = cy + r * 0.65 * Math.sin(midAngle);
    const pct = Math.round((d.value / total) * 100);
    return { path, color: BAR_COLORS[i % BAR_COLORS.length], label: d.label, pct, lx, ly };
  });

  return (
    <div className="flex flex-wrap items-center gap-4">
      <svg width={size} height={size} aria-label="Pie chart" role="img">
        {slices.map((s, i) => (
          <g key={i}>
            <path d={s.path} fill={s.color} stroke="white" strokeWidth={1} aria-label={`${s.label}: ${s.pct}%`} />
            {s.pct >= 8 && (
              <text x={s.lx} y={s.ly} textAnchor="middle" dominantBaseline="middle" fontSize={9} fill="white" fontWeight="bold">
                {s.pct}%
              </text>
            )}
          </g>
        ))}
      </svg>
      <ul className="space-y-1">
        {slices.map((s, i) => (
          <li key={i} className="flex items-center gap-1.5 text-xs text-secondary-700 dark:text-secondary-300">
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: s.color }} />
            {s.label} ({s.pct}%)
          </li>
        ))}
      </ul>
    </div>
  );
}
