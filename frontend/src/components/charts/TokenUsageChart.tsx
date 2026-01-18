import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import { format, parseISO } from 'date-fns';
import { formatTokens } from '../../lib/formatting';
import type { DailyMetrics } from '../../types';

interface TokenUsageChartProps {
  data: DailyMetrics[];
}

export default function TokenUsageChart({ data }: TokenUsageChartProps) {
  if (data.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center text-gray-500">
        No token usage data available
      </div>
    );
  }

  const chartData = data.map((d) => ({
    date: d.date,
    input: d.input_tokens,
    output: d.output_tokens,
    cacheCreation: d.cache_creation,
    cacheRead: d.cache_read,
  }));

  return (
    <ResponsiveContainer width="100%" height={300}>
      <AreaChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="colorInput" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#667eea" stopOpacity={0.8} />
            <stop offset="95%" stopColor="#667eea" stopOpacity={0.1} />
          </linearGradient>
          <linearGradient id="colorOutput" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#10b981" stopOpacity={0.8} />
            <stop offset="95%" stopColor="#10b981" stopOpacity={0.1} />
          </linearGradient>
          <linearGradient id="colorCache" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.8} />
            <stop offset="95%" stopColor="#f59e0b" stopOpacity={0.1} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="date"
          tickFormatter={(value) => format(parseISO(value), 'MMM d')}
          tick={{ fontSize: 12 }}
        />
        <YAxis tickFormatter={(value) => formatTokens(value)} tick={{ fontSize: 12 }} />
        <Tooltip
          content={({ active, payload, label }) => {
            if (active && payload && payload.length) {
              return (
                <div className="rounded-lg border border-gray-200 dark:border-surface-700 bg-white dark:bg-surface-800 p-3 shadow-lg">
                  <p className="mb-2 font-medium text-gray-900 dark:text-surface-100">
                    {format(parseISO(label), 'MMM d, yyyy')}
                  </p>
                  {payload.map((entry, index) => (
                    <p
                      key={index}
                      className="text-sm"
                      style={{ color: entry.color }}
                    >
                      {entry.name}: {formatTokens(entry.value as number)}
                    </p>
                  ))}
                </div>
              );
            }
            return null;
          }}
        />
        <Legend />
        <Area
          type="monotone"
          dataKey="input"
          name="Input"
          stackId="1"
          stroke="#667eea"
          fill="url(#colorInput)"
        />
        <Area
          type="monotone"
          dataKey="output"
          name="Output"
          stackId="1"
          stroke="#10b981"
          fill="url(#colorOutput)"
        />
        <Area
          type="monotone"
          dataKey="cacheRead"
          name="Cache Read"
          stackId="1"
          stroke="#f59e0b"
          fill="url(#colorCache)"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
