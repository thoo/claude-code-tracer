import clsx from 'clsx';

interface StatsCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon?: React.ReactNode;
  trend?: {
    value: number;
    isPositive: boolean;
  };
  breakdown?: { label: string; value: string }[];
  className?: string;
  variant?: 'default' | 'accent' | 'highlight';
}

export default function StatsCard({
  title,
  value,
  subtitle,
  icon,
  trend,
  breakdown,
  className,
  variant = 'default',
}: StatsCardProps) {
  return (
    <div
      className={clsx(
        'stats-card group',
        variant === 'accent' && 'border-accent-500/20',
        variant === 'highlight' && 'border-highlight-500/20',
        className
      )}
    >
      <div className="flex items-start justify-between relative z-10">
        <div className="flex-1 min-w-0">
          <p className="stats-label">{title}</p>
          <div className="mt-2 flex items-baseline gap-3">
            <p className="stats-value truncate">
              {value}
            </p>
            {trend && (
              <span
                className={clsx(
                  'inline-flex items-center gap-0.5 text-sm font-mono font-medium',
                  trend.isPositive ? 'text-success-400' : 'text-error-400'
                )}
              >
                <svg
                  className={clsx('h-4 w-4', !trend.isPositive && 'rotate-180')}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M5 10l7-7m0 0l7 7m-7-7v18"
                  />
                </svg>
                {Math.abs(trend.value)}%
              </span>
            )}
          </div>
          {subtitle && (
            <p className="mt-1.5 text-sm text-gray-500 dark:text-surface-400 font-mono">{subtitle}</p>
          )}
        </div>
        {icon && (
          <div className={clsx(
            'flex h-12 w-12 items-center justify-center rounded-xl transition-all duration-300',
            'bg-gray-100 text-gray-700 group-hover:bg-gray-200 group-hover:text-gray-900 dark:bg-surface-800 dark:text-surface-200 dark:group-hover:bg-surface-700 dark:group-hover:text-surface-100'
          )}>
            {icon}
          </div>
        )}
      </div>

      {breakdown && breakdown.length > 0 && (
        <div className="relative z-10 mt-4 space-y-2 border-t border-gray-200 dark:border-surface-800 pt-4">
          {breakdown.map((item, index) => (
            <div key={index} className="flex items-center justify-between text-sm">
              <span className="text-gray-500 dark:text-surface-400">{item.label}</span>
              <span className="font-mono text-gray-700 dark:text-surface-300">{item.value}</span>
            </div>
          ))}
        </div>
      )}

      {/* Hover gradient effect */}
      <div className={clsx(
        'absolute inset-0 rounded-xl opacity-0 transition-opacity duration-300 group-hover:opacity-100',
        variant === 'accent'
          ? 'bg-gradient-to-br from-accent-500/5 via-transparent to-transparent'
          : variant === 'highlight'
          ? 'bg-gradient-to-br from-highlight-500/5 via-transparent to-transparent'
          : 'bg-gradient-to-br from-surface-700/20 via-transparent to-transparent'
      )} />
    </div>
  );
}
