import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import { format, parseISO } from 'date-fns';
import { formatCost } from '../../lib/formatting';
import type { DailyMetrics } from '../../types';

interface CostChartProps {
  data: DailyMetrics[];
}

export default function CostChart({ data }: CostChartProps) {
  if (data.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center text-gray-500">
        No cost data available
      </div>
    );
  }

  const chartData = data.map((d) => ({
    date: d.date,
    cost: d.cost,
  }));

  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="date"
          tickFormatter={(value) => format(parseISO(value), 'MMM d')}
          tick={{ fontSize: 12 }}
        />
        <YAxis tickFormatter={(value) => formatCost(value)} tick={{ fontSize: 12 }} />
        <Tooltip
          content={({ active, payload, label }) => {
            if (active && payload && payload.length) {
              return (
                <div className="rounded-lg border border-gray-200 bg-white p-3 shadow-lg">
                  <p className="mb-2 font-medium text-gray-900">
                    {format(parseISO(label), 'MMM d, yyyy')}
                  </p>
                  <p className="text-sm text-primary-600">
                    Cost: {formatCost(payload[0].value as number)}
                  </p>
                </div>
              );
            }
            return null;
          }}
        />
        <Legend />
        <Bar
          dataKey="cost"
          name="Daily Cost"
          fill="#667eea"
          radius={[4, 4, 0, 0]}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}
