import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';
import { useTheme } from '../../hooks/useTheme';
import type { ToolUsageStats } from '../../types';

interface ToolUsageChartProps {
  tools: ToolUsageStats[];
  maxItems?: number;
}

const COLORS = [
  '#f97316', // accent orange
  '#fb923c', // lighter orange
  '#06b6d4', // cyan/highlight
  '#22d3ee', // lighter cyan
  '#22c55e', // success green
  '#4ade80', // lighter green
  '#a855f7', // purple
  '#c084fc', // lighter purple
  '#f59e0b', // amber
  '#fbbf24', // lighter amber
];

export default function ToolUsageChart({ tools, maxItems = 10 }: ToolUsageChartProps) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === 'dark';
  
  // Sort by count and take top items
  const sortedTools = [...tools]
    .sort((a, b) => b.count - a.count)
    .slice(0, maxItems);

  const data = sortedTools.map((tool) => ({
    name: tool.name,
    count: tool.count,
    errors: tool.error_count,
  }));

  if (data.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center text-gray-500 dark:text-surface-400">
        No tool usage data available
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={Math.max(200, data.length * 40)}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 5, right: 30, left: 100, bottom: 5 }}
      >
        <CartesianGrid
          strokeDasharray="3 3"
          horizontal={true}
          vertical={false}
          strokeOpacity={0.5}
          stroke={isDark ? '#334155' : '#e5e7eb'}
        />
        <XAxis
          type="number"
          tick={{ fill: isDark ? '#94a3b8' : '#6b7280', fontSize: 11, fontFamily: 'JetBrains Mono' }}
          axisLine={{ stroke: isDark ? '#334155' : '#e5e7eb' }}
          tickLine={{ stroke: isDark ? '#334155' : '#e5e7eb' }}
        />
        <YAxis
          dataKey="name"
          type="category"
          width={90}
          tick={{ fill: isDark ? '#e2e8f0' : '#374151', fontSize: 11, fontFamily: 'JetBrains Mono' }}
          tickLine={false}
          axisLine={false}
        />
        <Tooltip
          content={({ active, payload }) => {
            if (active && payload && payload.length) {
              const data = payload[0].payload;
              return (
                <div className="rounded-lg border border-gray-200 dark:border-surface-700 bg-white dark:bg-surface-800 p-3 shadow-xl">
                  <p className="font-mono font-medium text-gray-900 dark:text-surface-100">{data.name}</p>
                  <p className="text-sm text-gray-500 dark:text-surface-400 font-mono">
                    <span className="font-medium text-accent-600 dark:text-accent-400">{data.count}</span> calls
                  </p>
                  {data.errors > 0 && (
                    <p className="text-sm font-mono">
                      <span className="font-medium text-error-600 dark:text-error-400">{data.errors}</span> errors
                    </p>
                  )}
                </div>
              );
            }
            return null;
          }}
        />
        <Bar dataKey="count" radius={[0, 4, 4, 0]}>
          {data.map((_, index) => (
            <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
