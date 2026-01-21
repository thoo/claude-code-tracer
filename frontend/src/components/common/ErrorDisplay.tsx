import { useNavigate } from 'react-router-dom';

interface ErrorDisplayProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  showBackButton?: boolean;
}

export default function ErrorDisplay({
  title = 'Error',
  message,
  onRetry,
  showBackButton = true,
}: ErrorDisplayProps) {
  const navigate = useNavigate();

  const handleGoBack = () => {
    // Try to go back in history, or navigate to home if no history
    if (window.history.length > 1) {
      navigate(-1);
    } else {
      navigate('/');
    }
  };

  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-error-500/10 text-error-400 border border-error-500/20">
        <svg className="h-8 w-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
          />
        </svg>
      </div>
      <h3 className="text-lg font-semibold text-gray-900 dark:text-surface-200">{title}</h3>
      <p className="mt-2 max-w-sm text-sm text-gray-500 dark:text-surface-400 font-mono">{message}</p>
      <div className="mt-6 flex items-center gap-3">
        {showBackButton && (
          <button onClick={handleGoBack} className="btn-secondary">
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M10 19l-7-7m0 0l7-7m-7 7h18"
              />
            </svg>
            Go back
          </button>
        )}
        {onRetry && (
          <button onClick={onRetry} className="btn-primary">
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
            Try again
          </button>
        )}
      </div>
    </div>
  );
}
