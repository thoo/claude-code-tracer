import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from 'recharts';

interface ModelUsageChartProps {
  models: { name: string; count: number }[];
}

const COLORS = ['#667eea', '#7c3aed', '#06b6d4', '#10b981', '#f59e0b'];

export default function ModelUsageChart({ models }: ModelUsageChartProps) {
  if (models.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center text-gray-500">
        No model usage data available
      </div>
    );
  }

  const data = models.map((m) => ({
    name: formatModelName(m.name),
    value: m.count,
    fullName: m.name,
  }));

  return (
    <ResponsiveContainer width="100%" height={300}>
      <PieChart>
        <Pie
          data={data}
          cx="50%"
          cy="50%"
          innerRadius={60}
          outerRadius={100}
          paddingAngle={2}
          dataKey="value"
        >
          {data.map((_, index) => (
            <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip
          content={({ active, payload }) => {
            if (active && payload && payload.length) {
              const entry = payload[0].payload;
              return (
                <div className="rounded-lg border border-gray-200 dark:border-surface-700 bg-white dark:bg-surface-800 p-3 shadow-lg">
                  <p className="font-medium text-gray-900 dark:text-surface-100">{entry.fullName}</p>
                  <p className="text-sm text-gray-600 dark:text-surface-400">
                    <span className="font-medium">{entry.value}</span> messages
                  </p>
                </div>
              );
            }
            return null;
          }}
        />
        <Legend
          formatter={(value) => <span className="text-sm text-gray-600">{value}</span>}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}

function formatModelName(name: string): string {
  // Shorten model names for display
  if (name.includes('opus')) return 'Opus';
  if (name.includes('sonnet')) return 'Sonnet';
  if (name.includes('haiku')) return 'Haiku';
  return name.split('-')[0];
}
