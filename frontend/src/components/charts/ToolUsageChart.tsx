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
import type { ToolUsageStats } from '../../types';

interface ToolUsageChartProps {
  tools: ToolUsageStats[];
  maxItems?: number;
}

const COLORS = [
  '#667eea', // primary
  '#7c3aed', // purple
  '#06b6d4', // cyan
  '#10b981', // emerald
  '#f59e0b', // amber
  '#ef4444', // red
  '#ec4899', // pink
  '#8b5cf6', // violet
  '#14b8a6', // teal
  '#f97316', // orange
];

export default function ToolUsageChart({ tools, maxItems = 10 }: ToolUsageChartProps) {
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
      <div className="flex h-64 items-center justify-center text-gray-500">
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
        <CartesianGrid strokeDasharray="3 3" horizontal={true} vertical={false} />
        <XAxis type="number" />
        <YAxis
          dataKey="name"
          type="category"
          width={90}
          tick={{ fontSize: 12 }}
          tickLine={false}
        />
        <Tooltip
          content={({ active, payload }) => {
            if (active && payload && payload.length) {
              const data = payload[0].payload;
              return (
                <div className="rounded-lg border border-gray-200 bg-white p-3 shadow-lg">
                  <p className="font-medium text-gray-900">{data.name}</p>
                  <p className="text-sm text-gray-600">
                    <span className="font-medium">{data.count}</span> calls
                  </p>
                  {data.errors > 0 && (
                    <p className="text-sm text-red-600">
                      <span className="font-medium">{data.errors}</span> errors
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
