import clsx from 'clsx';

type BadgeVariant = 'default' | 'primary' | 'secondary' | 'success' | 'warning' | 'error' | 'gray' | 'purple' | 'teal';

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  size?: 'sm' | 'md';
  className?: string;
}

const variantStyles: Record<BadgeVariant, string> = {
  default: 'bg-gray-100 text-gray-700 border-gray-300 dark:bg-surface-700/50 dark:text-surface-300 dark:border-surface-600',
  primary: 'bg-accent-500/15 text-accent-600 border-accent-500/30 dark:text-accent-400',
  secondary: 'bg-highlight-500/15 text-highlight-600 border-highlight-500/30 dark:text-highlight-400',
  success: 'bg-success-500/15 text-success-600 border-success-500/30 dark:text-success-400',
  warning: 'bg-amber-500/15 text-amber-600 border-amber-500/30 dark:text-amber-400',
  error: 'bg-error-500/15 text-error-600 border-error-500/30 dark:text-error-400',
  gray: 'bg-gray-100 text-gray-700 border-gray-300 dark:bg-surface-800 dark:text-surface-400 dark:border-surface-700',
  purple: 'bg-indigo-500/15 text-indigo-600 border-indigo-500/30 dark:text-indigo-400',
  teal: 'bg-teal-500/15 text-teal-600 border-teal-500/30 dark:text-teal-400',
};

export default function Badge({
  children,
  variant = 'default',
  size = 'sm',
  className,
}: BadgeProps) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-md font-mono font-medium border',
        variantStyles[variant],
        size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-sm',
        className
      )}
    >
      {children}
    </span>
  );
}
