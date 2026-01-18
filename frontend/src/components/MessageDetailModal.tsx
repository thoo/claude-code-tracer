import { useState, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Light as SyntaxHighlighter } from 'react-syntax-highlighter';
import json from 'react-syntax-highlighter/dist/esm/languages/hljs/json';
import bash from 'react-syntax-highlighter/dist/esm/languages/hljs/bash';
import typescript from 'react-syntax-highlighter/dist/esm/languages/hljs/typescript';
import python from 'react-syntax-highlighter/dist/esm/languages/hljs/python';
import javascript from 'react-syntax-highlighter/dist/esm/languages/hljs/javascript';
import go from 'react-syntax-highlighter/dist/esm/languages/hljs/go';
import rust from 'react-syntax-highlighter/dist/esm/languages/hljs/rust';
import css from 'react-syntax-highlighter/dist/esm/languages/hljs/css';
import xml from 'react-syntax-highlighter/dist/esm/languages/hljs/xml';
import sql from 'react-syntax-highlighter/dist/esm/languages/hljs/sql';
import yaml from 'react-syntax-highlighter/dist/esm/languages/hljs/yaml';
import markdown from 'react-syntax-highlighter/dist/esm/languages/hljs/markdown';
import { atomOneDark, atomOneLight } from 'react-syntax-highlighter/dist/esm/styles/hljs';
import { useMessageDetail } from '../hooks/useApi';
import { useTheme } from '../hooks/useTheme';
import { formatDateTime, formatTokens } from '../lib/formatting';
import Badge from './common/Badge';
import LoadingSpinner from './common/LoadingSpinner';
import type { ToolUse, ToolResult, MessageDetailResponse } from '../types';

// Register languages
SyntaxHighlighter.registerLanguage('json', json);
SyntaxHighlighter.registerLanguage('bash', bash);
SyntaxHighlighter.registerLanguage('typescript', typescript);
SyntaxHighlighter.registerLanguage('python', python);
SyntaxHighlighter.registerLanguage('javascript', javascript);
SyntaxHighlighter.registerLanguage('go', go);
SyntaxHighlighter.registerLanguage('rust', rust);
SyntaxHighlighter.registerLanguage('css', css);
SyntaxHighlighter.registerLanguage('xml', xml);
SyntaxHighlighter.registerLanguage('html', xml); // xml handles html
SyntaxHighlighter.registerLanguage('sql', sql);
SyntaxHighlighter.registerLanguage('yaml', yaml);
SyntaxHighlighter.registerLanguage('markdown', markdown);

function tryFormatJson(text: string): string | null {
  try {
    const trimmed = text.trim();
    if ((trimmed.startsWith('{') || trimmed.startsWith('[')) && (trimmed.endsWith('}') || trimmed.endsWith(']'))) {
      const parsed = JSON.parse(trimmed);
      const formatted = JSON.stringify(parsed, null, 2);
      // Replace literal \n with actual newlines for readability within the JSON view
      return formatted.replace(/\\n/g, '\n');
    }
  } catch (e) {
    return null;
  }
  return null;
}

function tryParseJson(text: string): any {
  try {
    const trimmed = text.trim();
    if ((trimmed.startsWith('{') || trimmed.startsWith('[')) && (trimmed.endsWith('}') || trimmed.endsWith(']'))) {
      return JSON.parse(trimmed);
    }
  } catch (e) {
    return null;
  }
  return null;
}

// Parse hook message content (XML-like tags)
interface HookContent {
  type: 'command' | 'caveat' | 'stdout' | 'prompt-hook' | 'unknown';
  commandName?: string;
  commandMessage?: string;
  commandArgs?: string;
  content?: string;
}

function parseHookContent(content: string): HookContent {
  // Remove surrounding quotes if present (JSON encoded)
  let text = content;
  if (text.startsWith('"') && text.endsWith('"')) {
    text = text.slice(1, -1);
  }

  // Check for command-name pattern (slash commands)
  const commandMatch = text.match(/<command-name>([^<]*)<\/command-name>/);
  if (commandMatch) {
    const messageMatch = text.match(/<command-message>([^<]*)<\/command-message>/);
    const argsMatch = text.match(/<command-args>([^<]*)<\/command-args>/);
    return {
      type: 'command',
      commandName: commandMatch[1],
      commandMessage: messageMatch?.[1] || '',
      commandArgs: argsMatch?.[1] || '',
    };
  }

  // Check for local-command-caveat
  const caveatMatch = text.match(/<local-command-caveat>([^]*?)<\/local-command-caveat>/);
  if (caveatMatch) {
    return {
      type: 'caveat',
      content: caveatMatch[1],
    };
  }

  // Check for local-command-stdout
  const stdoutMatch = text.match(/<local-command-stdout>([^]*?)<\/local-command-stdout>/);
  if (stdoutMatch !== null) {
    return {
      type: 'stdout',
      content: stdoutMatch[1] || '(empty)',
    };
  }

  // Check for user-prompt-submit-hook
  const hookMatch = text.match(/<user-prompt-submit-hook>([^]*?)<\/user-prompt-submit-hook>/);
  if (hookMatch) {
    return {
      type: 'prompt-hook',
      content: hookMatch[1],
    };
  }

  return { type: 'unknown', content: text };
}

function escapeMarkdown(text: string): string {
  // Split by code blocks:
  // 1. Fenced code blocks ```...```
  // 2. Double-backtick inline code ``...``
  // 3. Single-backtick inline code `...`
  // capturing the code blocks to preserve them
  return text.split(/(```[\s\S]*?```|``[\s\S]*?``|`[^`]*`)/g).map((part, index) => {
    // If index is odd, it's a captured code block
    if (index % 2 === 1) {
      return part;
    }
    // Otherwise it's normal text:
    // 1. Escape tildes to prevent accidental strikethrough
    // 2. Unescape literal "\n" sequences to actual newlines for proper display
    return part.replace(/~/g, '\\~').replace(/\\n/g, '\n');
  }).join('');
}

interface MessageDetailModalProps {
  projectHash: string;
  sessionId: string;
  messageUuid: string;
  onClose: () => void;
  onNavigate?: (uuid: string) => void;
  apiBasePath?: string;
}

export default function MessageDetailModal({
  projectHash,
  sessionId,
  messageUuid,
  onClose,
  onNavigate,
  apiBasePath,
}: MessageDetailModalProps) {
  const [copiedField, setCopiedField] = useState<string | null>(null);

  // Use custom API path if provided, otherwise use default session path
  const effectiveApiPath = apiBasePath || `/api/sessions/${projectHash}/${sessionId}`;
  const { data: message, isLoading } = useMessageDetail(projectHash, sessionId, messageUuid, effectiveApiPath);

  // Handle keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      } else if (e.key === 'ArrowLeft' && message && message.message_index > 1) {
        navigateToIndex(message.message_index - 1);
      } else if (e.key === 'ArrowRight' && message && message.message_index < message.total_messages) {
        navigateToIndex(message.message_index + 1);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [message, onClose]);

  const navigateToIndex = useCallback(async (index: number) => {
    try {
      const fetchPath = apiBasePath
        ? `${apiBasePath}/messages/by-index/${index}`
        : `/api/sessions/${projectHash}/${sessionId}/messages/by-index/${index}`;
      const response = await fetch(fetchPath);
      if (response.ok) {
        const data: MessageDetailResponse = await response.json();
        if (onNavigate) {
          onNavigate(data.uuid);
        }
      }
    } catch (error) {
      console.error('Navigation failed:', error);
    }
  }, [projectHash, sessionId, onNavigate, apiBasePath]);

  const copyToClipboard = (text: string, field: string) => {
    navigator.clipboard.writeText(text);
    setCopiedField(field);
    setTimeout(() => setCopiedField(null), 2000);
  };

  if (isLoading) {
    return (
      <div className="modal-overlay flex items-center justify-center" onClick={onClose}>
        <div className="modal-content p-8" onClick={(e) => e.stopPropagation()}>
          <LoadingSpinner />
        </div>
      </div>
    );
  }

  if (!message) {
    return null;
  }

  return (
    <div
      className="modal-overlay flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="modal-content max-w-4xl w-full max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 dark:border-surface-700 px-6 py-4">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-surface-100">Message Details</h2>
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigateToIndex(message.message_index - 1)}
              disabled={message.message_index <= 1}
              className="px-3 py-1.5 text-sm border border-gray-300 dark:border-surface-700 rounded-lg bg-white dark:bg-surface-800 text-gray-700 dark:text-surface-300 disabled:opacity-30 disabled:cursor-not-allowed hover:bg-gray-50 dark:hover:bg-surface-700 hover:border-gray-400 dark:hover:border-surface-600 transition-colors"
            >
              &larr; Previous
            </button>
            <span className="text-sm text-gray-500 dark:text-surface-400 font-mono">
              {message.message_index} of {message.total_messages}
            </span>
            <button
              onClick={() => navigateToIndex(message.message_index + 1)}
              disabled={message.message_index >= message.total_messages}
              className="px-3 py-1.5 text-sm border border-gray-300 dark:border-surface-700 rounded-lg bg-white dark:bg-surface-800 text-gray-700 dark:text-surface-300 disabled:opacity-30 disabled:cursor-not-allowed hover:bg-gray-50 dark:hover:bg-surface-700 hover:border-gray-400 dark:hover:border-surface-600 transition-colors"
            >
              Next &rarr;
            </button>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600 dark:text-surface-400 dark:hover:text-surface-300 text-2xl leading-none transition-colors"
            >
              &times;
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Metadata */}
          <div className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <span className="text-gray-500 dark:text-surface-400 font-medium">Type:</span>
            <span>
              <Badge variant={message.type === 'assistant' ? 'primary' : message.type === 'user' ? 'teal' : message.type === 'tool_result' ? 'purple' : message.type === 'hook' ? 'secondary' : 'gray'}>
                {message.type}
              </Badge>
            </span>

            <span className="text-gray-500 dark:text-surface-400 font-medium">Timestamp:</span>
            <span className="text-gray-900 dark:text-surface-200 font-mono">{formatDateTime(message.timestamp)}</span>

            <span className="text-gray-500 dark:text-surface-400 font-medium">Session ID:</span>
            <span className="text-gray-900 dark:text-surface-200 font-mono text-xs flex items-center gap-2">
              {message.session_id}
              <CopyButton
                copied={copiedField === 'session'}
                onClick={() => copyToClipboard(message.session_id, 'session')}
              />
            </span>

            {message.message_id && (
              <>
                <span className="text-gray-500 dark:text-surface-400 font-medium">Message ID:</span>
                <span className="text-gray-900 dark:text-surface-200 font-mono text-xs flex items-center gap-2">
                  {message.message_id}
                  <CopyButton
                    copied={copiedField === 'message'}
                    onClick={() => copyToClipboard(message.message_id!, 'message')}
                  />
                </span>
              </>
            )}

            {message.model && (
              <>
                <span className="text-gray-500 dark:text-surface-400 font-medium">Model:</span>
                <span className="text-gray-900 dark:text-surface-200">{message.model}</span>
              </>
            )}

            {(message.tokens.input_tokens > 0 || message.tokens.output_tokens > 0) && (
              <>
                <span className="text-gray-500 dark:text-surface-400 font-medium">Tokens:</span>
                <div className="text-gray-700 dark:text-surface-300 font-mono text-xs">
                  <div>Input: {formatTokens(message.tokens.input_tokens)}</div>
                  <div>Output: {formatTokens(message.tokens.output_tokens)}</div>
                  {message.tokens.cache_creation_input_tokens > 0 && (
                    <div>Cache Created: {formatTokens(message.tokens.cache_creation_input_tokens)}</div>
                  )}
                  {message.tokens.cache_read_input_tokens > 0 && (
                    <div>Cache Read: {formatTokens(message.tokens.cache_read_input_tokens)}</div>
                  )}
                </div>
              </>
            )}

            {message.cwd && (
              <>
                <span className="text-gray-500 dark:text-surface-400 font-medium">Working Dir:</span>
                <span className="text-gray-900 dark:text-surface-200 font-mono text-xs">{message.cwd}</span>
              </>
            )}
          </div>

          {/* Message Content */}
          {message.content && (
            <div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-surface-100 mb-2">Message Content</h3>
              <div className="bg-gray-50 dark:bg-surface-800 rounded-lg p-4 text-sm text-gray-900 dark:text-surface-100 border border-gray-200 dark:border-surface-700">
                {(() => {
                  // Check for hook messages first
                  if (message.type === 'hook') {
                    return <HookContentDisplay content={message.content} />;
                  }

                  const parsed = tryParseJson(message.content);
                  if (Array.isArray(parsed) && parsed.length > 0 && parsed[0].type) {
                    return (
                      <div className="space-y-4">
                        {parsed.map((block, i) => (
                          <ContentBlockDisplay key={i} block={block} />
                        ))}
                      </div>
                    );
                  }

                  const formatted = tryFormatJson(message.content);
                  if (formatted) {
                    return (
                      <CodeBlockWithCopy
                        language="json"
                        content={formatted}
                        customStyle={{
                          margin: 0,
                          padding: 0,
                          backgroundColor: 'transparent',
                        }}
                      />
                    );
                  }

                  return (
                    <div className="prose prose-sm dark:prose-invert max-w-none prose-pre:p-0 prose-pre:bg-transparent prose-p:text-gray-900 dark:prose-p:text-surface-100 prose-headings:text-gray-900 dark:prose-headings:text-surface-100 prose-strong:text-gray-900 dark:prose-strong:text-surface-100 prose-li:text-gray-900 dark:prose-li:text-surface-100">
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                          code({ node, inline, className, children, ...props }: any) {
                            const match = /language-(\w+)/.exec(className || '');
                            const codeContent = String(children).replace(/\n$/, '');
                            return !inline ? (
                              <CodeBlockWithCopy
                                language={match ? match[1] : 'plaintext'}
                                content={codeContent}
                                {...props}
                              />
                            ) : (
                              <code className={`${className} bg-gray-200 dark:bg-surface-700 px-1 py-0.5 rounded text-gray-900 dark:text-surface-100`} {...props}>
                                {children}
                              </code>
                            );
                          },
                          // Style other markdown elements
                          p: ({ children }) => <p className="mb-4 last:mb-0 text-gray-900 dark:text-surface-100">{children}</p>,
                          ul: ({ children }) => <ul className="list-disc pl-4 mb-4 space-y-1 text-gray-900 dark:text-surface-100">{children}</ul>,
                          ol: ({ children }) => <ol className="list-decimal pl-4 mb-4 space-y-1 text-gray-900 dark:text-surface-100">{children}</ol>,
                          li: ({ children }) => <li className="text-gray-900 dark:text-surface-100">{children}</li>,
                          h1: ({ children }) => <h1 className="text-xl font-bold mb-4 mt-6 text-gray-900 dark:text-surface-100">{children}</h1>,
                          h2: ({ children }) => <h2 className="text-lg font-bold mb-3 mt-5 text-gray-900 dark:text-surface-100">{children}</h2>,
                          h3: ({ children }) => <h3 className="text-base font-bold mb-2 mt-4 text-gray-900 dark:text-surface-100">{children}</h3>,
                          blockquote: ({ children }) => <blockquote className="border-l-4 border-gray-300 dark:border-surface-600 pl-4 italic my-4 text-gray-700 dark:text-surface-200">{children}</blockquote>,
                          a: ({ href, children }) => <a href={href} className="text-accent-600 dark:text-accent-400 hover:underline" target="_blank" rel="noopener noreferrer">{children}</a>,
                        }}
                      >
                        {escapeMarkdown(message.content)}
                      </ReactMarkdown>
                    </div>
                  );
                })()}
              </div>
            </div>
          )}

          {/* Tools Used */}
          {message.tools.length > 0 && (
            <div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-surface-100 mb-2">Tools Used</h3>
              <div className="space-y-4">
                {message.tools.map((tool, index) => (
                  <ToolUseDisplay key={tool.id || index} tool={tool} />
                ))}
              </div>
            </div>
          )}

          {/* Tool Results */}
          {message.tool_results.length > 0 && (
            <div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-surface-100 mb-2">Tool Results</h3>
              <div className="space-y-4">
                {message.tool_results.map((result, index) => {
                  const tool = message.tools.find(t => t.id === result.tool_use_id);
                  return (
                    <ToolResultDisplay
                      key={result.tool_use_id || index}
                      result={result}
                      toolName={tool?.name}
                      toolInput={tool?.input}
                    />
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ContentBlockDisplay({ block }: { block: any }) {
  if (!block || typeof block !== 'object') return null;

  switch (block.type) {
    case 'text':
      return (
        <div className="prose prose-sm dark:prose-invert max-w-none prose-pre:p-0 prose-pre:bg-transparent prose-p:text-gray-900 dark:prose-p:text-surface-100 prose-headings:text-gray-900 dark:prose-headings:text-surface-100 prose-strong:text-gray-900 dark:prose-strong:text-surface-100 prose-li:text-gray-900 dark:prose-li:text-surface-100">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              code({ node, inline, className, children, ...props }: any) {
                const match = /language-(\w+)/.exec(className || '');
                const codeContent = String(children).replace(/\n$/, '');
                return !inline ? (
                  <CodeBlockWithCopy
                    language={match ? match[1] : 'plaintext'}
                    content={codeContent}
                    {...props}
                  />
                ) : (
                  <code className={`${className} bg-gray-200 dark:bg-surface-700 px-1 py-0.5 rounded text-gray-900 dark:text-surface-100`} {...props}>
                    {children}
                  </code>
                );
              },
              p: ({ children }) => <p className="mb-4 last:mb-0 text-gray-900 dark:text-surface-100">{children}</p>,
              ul: ({ children }) => <ul className="list-disc pl-4 mb-4 space-y-1 text-gray-900 dark:text-surface-100">{children}</ul>,
              ol: ({ children }) => <ol className="list-decimal pl-4 mb-4 space-y-1 text-gray-900 dark:text-surface-100">{children}</ol>,
              li: ({ children }) => <li className="text-gray-900 dark:text-surface-100">{children}</li>,
              h1: ({ children }) => <h1 className="text-xl font-bold mb-4 mt-6 text-gray-900 dark:text-surface-100">{children}</h1>,
              h2: ({ children }) => <h2 className="text-lg font-bold mb-3 mt-5 text-gray-900 dark:text-surface-100">{children}</h2>,
              h3: ({ children }) => <h3 className="text-base font-bold mb-2 mt-4 text-gray-900 dark:text-surface-100">{children}</h3>,
              blockquote: ({ children }) => <blockquote className="border-l-4 border-gray-300 dark:border-surface-600 pl-4 italic my-4 text-gray-700 dark:text-surface-200">{children}</blockquote>,
              a: ({ href, children }) => <a href={href} className="text-accent-600 dark:text-accent-400 hover:underline" target="_blank" rel="noopener noreferrer">{children}</a>,
            }}
          >
            {escapeMarkdown(block.text || '')}
          </ReactMarkdown>
        </div>
      );
    case 'tool_use':
      return <ToolUseDisplay tool={block as ToolUse} />;
    case 'tool_result':
      return <ToolResultDisplay result={block as ToolResult} />;
    case 'thinking':
      return (
        <div className="bg-highlight-500/10 border border-highlight-500/30 p-4 rounded-lg">
          <div className="text-xs font-semibold text-highlight-400 mb-2 uppercase tracking-wider">Thinking Process</div>
          <div className="text-sm text-gray-700 dark:text-surface-200 whitespace-pre-wrap leading-relaxed">{block.thinking}</div>
        </div>
      );
    default:
      return (
        <div className="bg-gray-100 dark:bg-surface-800 p-3 rounded text-xs font-mono overflow-x-auto text-gray-900 dark:text-surface-200">
          {JSON.stringify(block, null, 2)}
        </div>
      );
  }
}

function HookContentDisplay({ content }: { content: string }) {
  const parsed = parseHookContent(content);

  switch (parsed.type) {
    case 'command':
      return (
        <div className="border border-blue-200 dark:border-blue-800 rounded-lg overflow-hidden">
          <div className="bg-blue-50 dark:bg-blue-900/30 px-4 py-2 border-b border-blue-200 dark:border-blue-800">
            <span className="text-blue-700 dark:text-blue-300 font-semibold">Slash Command</span>
          </div>
          <div className="p-4 space-y-2 bg-white dark:bg-surface-900/50">
            <div className="flex items-center gap-3">
              <span className="text-sm font-medium text-gray-500 dark:text-surface-400 w-20">Command:</span>
              <code className="px-2 py-1 bg-blue-100 dark:bg-blue-900/50 text-blue-800 dark:text-blue-200 rounded font-mono text-sm">
                {parsed.commandName}
              </code>
            </div>
            {parsed.commandArgs && (
              <div className="flex items-start gap-3">
                <span className="text-sm font-medium text-gray-500 dark:text-surface-400 w-20">Args:</span>
                <span className="text-sm text-gray-700 dark:text-surface-300">{parsed.commandArgs}</span>
              </div>
            )}
          </div>
        </div>
      );

    case 'caveat':
      return (
        <div className="border border-amber-200 dark:border-amber-800 rounded-lg overflow-hidden">
          <div className="bg-amber-50 dark:bg-amber-900/30 px-4 py-2 border-b border-amber-200 dark:border-amber-800">
            <span className="text-amber-700 dark:text-amber-300 font-semibold">System Notice</span>
          </div>
          <div className="p-4 bg-white dark:bg-surface-900/50">
            <p className="text-sm text-gray-700 dark:text-surface-300 italic">{parsed.content}</p>
          </div>
        </div>
      );

    case 'stdout':
      return (
        <div className="border border-gray-200 dark:border-surface-700 rounded-lg overflow-hidden">
          <div className="bg-gray-100 dark:bg-surface-800 px-4 py-2 border-b border-gray-200 dark:border-surface-700">
            <span className="text-gray-700 dark:text-surface-200 font-semibold">Command Output</span>
          </div>
          <div className="p-4 bg-white dark:bg-surface-900/50">
            {parsed.content && parsed.content !== '(empty)' ? (
              <pre className="text-sm font-mono text-gray-700 dark:text-surface-300 whitespace-pre-wrap bg-gray-50 dark:bg-surface-950 p-3 rounded border border-gray-100 dark:border-surface-800">
                {parsed.content}
              </pre>
            ) : (
              <span className="text-sm text-gray-400 italic">(no output)</span>
            )}
          </div>
        </div>
      );

    case 'prompt-hook':
      return (
        <div className="border border-purple-200 dark:border-purple-800 rounded-lg overflow-hidden">
          <div className="bg-purple-50 dark:bg-purple-900/30 px-4 py-2 border-b border-purple-200 dark:border-purple-800">
            <span className="text-purple-700 dark:text-purple-300 font-semibold">Prompt Hook</span>
          </div>
          <div className="p-4 bg-white dark:bg-surface-900/50">
            <pre className="text-sm font-mono text-gray-700 dark:text-surface-300 whitespace-pre-wrap">
              {parsed.content}
            </pre>
          </div>
        </div>
      );

    default:
      return (
        <div className="bg-gray-50 dark:bg-surface-800 p-4 rounded-lg border border-gray-200 dark:border-surface-700">
          <pre className="text-sm font-mono text-gray-700 dark:text-surface-300 whitespace-pre-wrap">{content}</pre>
        </div>
      );
  }
}

function CodeBlockWithCopy({
  language,
  content,
  customStyle,
  wrapLines,
  showLineNumbers,
  lineProps
}: {
  language: string;
  content: string;
  customStyle?: React.CSSProperties;
  wrapLines?: boolean;
  showLineNumbers?: boolean;
  lineProps?: any;
}) {
  const [copied, setCopied] = useState(false);
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === 'dark';

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="relative group border border-gray-200 dark:border-none rounded-lg">
      <div className="absolute right-2 top-2 z-10 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={handleCopy}
          className="p-1.5 rounded-lg text-gray-500 hover:text-gray-700 hover:bg-gray-200 dark:text-surface-400 dark:hover:text-surface-200 dark:hover:bg-surface-700 transition-colors"
          title="Copy code"
        >
          {copied ? (
            <svg className="h-4 w-4 text-green-500 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          ) : (
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" />
            </svg>
          )}
        </button>
      </div>
      <SyntaxHighlighter
        style={isDark ? atomOneDark : atomOneLight}
        language={language}
        PreTag="div"
        customStyle={{
          margin: 0, // Removed margin to fit border container better
          padding: '1em',
          borderRadius: '0.5rem',
          backgroundColor: isDark ? '#0f172a' : '#f3f4f6', // darker gray for light mode
          ...customStyle,
        }}
        wrapLines={wrapLines}
        showLineNumbers={showLineNumbers}
        lineProps={lineProps}
      >
        {content}
      </SyntaxHighlighter>
    </div>
  );
}

function CopyButton({
  copied,
  onClick,
}: {
  copied: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="p-1 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100 dark:text-surface-500 dark:hover:text-surface-300 dark:hover:bg-surface-800 transition-colors"
      title="Copy ID"
    >
      {copied ? (
        <svg className="h-3.5 w-3.5 text-green-500 dark:text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
      ) : (
        <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
        </svg>
      )}
    </button>
  );
}

function ToolUseDisplay({ tool }: { tool: ToolUse }) {
  const isEditTool = tool.name === 'Edit';
  const isWriteTool = tool.name === 'Write';

  return (
    <div className="border border-gray-200 dark:border-surface-700 rounded-lg overflow-hidden">
      <div className="bg-gray-100 dark:bg-surface-800 px-4 py-2 border-b border-gray-200 dark:border-surface-700">
        <span className="text-accent-600 dark:text-accent-400 font-semibold font-mono">{tool.name}</span>
      </div>
      <div className="p-4 bg-gray-50 dark:bg-surface-900/50">
        {isEditTool ? (
          <EditToolDisplay input={tool.input} />
        ) : isWriteTool ? (
          <WriteToolDisplay input={tool.input} />
        ) : (
          <CodeBlockWithCopy
            language="json"
            content={JSON.stringify(tool.input, null, 2)}
            customStyle={{
              margin: 0,
              padding: '1rem',
              backgroundColor: 'transparent',
              borderRadius: '0.5rem',
              fontSize: '0.875rem',
            }}
          />
        )}
      </div>
    </div>
  );
}

function EditToolDisplay({ input }: { input: Record<string, unknown> }) {
  const filePath = input.file_path as string;
  const oldString = input.old_string as string;
  const newString = input.new_string as string;

  return (
    <div className="space-y-3">
      {filePath && (
        <div className="font-mono text-sm text-gray-500 dark:text-surface-400">
          <span className="font-semibold text-gray-700 dark:text-surface-300">File:</span> {filePath}
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <div className="text-sm font-semibold text-error-600 dark:text-error-400 mb-1">Old String (Removed)</div>
          <div className="bg-error-500/10 border border-error-500/30 rounded-lg overflow-hidden relative group">
            <CodeBlockWithCopy
              language={getLanguageFromPath(filePath)}
              content={oldString || '(empty)'}
              customStyle={{
                margin: 0,
                padding: '1rem',
                backgroundColor: 'rgba(239, 68, 68, 0.1)',
                fontSize: '0.75rem',
              }}
              wrapLines={true}
              lineProps={{ style: { backgroundColor: 'rgba(239, 68, 68, 0.15)' } }}
            />
          </div>
        </div>
        <div>
          <div className="text-sm font-semibold text-success-600 dark:text-success-400 mb-1">New String (Added)</div>
          <div className="bg-success-500/10 border border-success-500/30 rounded-lg overflow-hidden relative group">
             <CodeBlockWithCopy
              language={getLanguageFromPath(filePath)}
              content={newString || '(empty)'}
              customStyle={{
                margin: 0,
                padding: '1rem',
                backgroundColor: 'rgba(34, 197, 94, 0.1)',
                fontSize: '0.75rem',
              }}
              wrapLines={true}
              lineProps={{ style: { backgroundColor: 'rgba(34, 197, 94, 0.15)' } }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function WriteToolDisplay({ input }: { input: Record<string, unknown> }) {
  const filePath = input.file_path as string;
  const content = input.content as string;

  return (
    <div className="space-y-3">
      {filePath && (
        <div className="font-mono text-sm text-gray-500 dark:text-surface-400">
          <span className="font-semibold text-gray-700 dark:text-surface-300">File:</span> {filePath}
        </div>
      )}
      <div>
        <div className="text-sm font-semibold text-success-600 dark:text-success-400 mb-1">Content (New File)</div>
        <div className="bg-success-500/10 border border-success-500/30 rounded-lg overflow-hidden max-h-96 overflow-y-auto">
          <CodeBlockWithCopy
            language={getLanguageFromPath(filePath)}
            content={content || '(empty)'}
            customStyle={{
              margin: 0,
              padding: '1rem',
              backgroundColor: 'rgba(34, 197, 94, 0.1)',
              fontSize: '0.75rem',
            }}
            showLineNumbers={true}
          />
        </div>
      </div>
    </div>
  );
}

function ToolResultDisplay({ 
  result, 
  toolName, 
  toolInput 
}: { 
  result: ToolResult; 
  toolName?: string;
  toolInput?: Record<string, unknown>;
}) {
  let content = result.content;
  let language = 'plaintext';

  // Helper to safely stringify if needed
  const safeStringify = (val: unknown) => JSON.stringify(val, null, 2);

  if (Array.isArray(content)) {
    // Try to extract text from content blocks
    const textParts = content
      .filter((block: any) => block && block.type === 'text' && typeof block.text === 'string')
      .map((block: any) => block.text);
    
    if (textParts.length > 0) {
      content = textParts.join('\n');
    } else {
      content = safeStringify(content);
      language = 'json';
    }
  } else if (typeof content !== 'string') {
    content = safeStringify(content);
    language = 'json';
  }

  // Detect language based on tool context if we have a string content
  if (typeof content === 'string' && language === 'plaintext') {
    if ((toolName === 'read_file' || toolName === 'Read') && toolInput?.file_path) {
      language = getLanguageFromPath(toolInput.file_path as string);
      // Strip line number prefixes (e.g., "     1→") from Read tool output
      content = content.replace(/^[ \t]*\d+→/gm, '');
    } else if (toolName === 'run_shell_command' || toolName === 'Bash') {
      language = 'bash';
    } else if (toolName === 'Glob' || toolName === 'Grep') {
      // File listing tools - show as plaintext but strip line numbers if present
      content = content.replace(/^[ \t]*\d+→/gm, '');
    }
  }

  // Auto-detect language from content if still plaintext
  if (typeof content === 'string' && language === 'plaintext' && content.length > 0) {
    // Strip line number prefixes before detection (may be present from various tools)
    const strippedContent = content.replace(/^[ \t]*\d+→/gm, '');
    const detected = detectLanguageFromContent(strippedContent);
    if (detected !== 'plaintext') {
      language = detected;
      content = strippedContent;
    }
  }

  // Try to format as JSON if it looks like JSON
  if (typeof content === 'string' && language === 'plaintext') {
    const formattedJson = tryFormatJson(content);
    if (formattedJson) {
      content = formattedJson;
      language = 'json';
    }
  }

  return (
    <div className={`border rounded-lg overflow-hidden ${result.is_error ? 'border-error-500/30 bg-error-500/5' : 'border-gray-200 dark:border-surface-700'}`}>
      <div className={`px-4 py-2 border-b ${result.is_error ? 'bg-error-500/10 border-error-500/30' : 'bg-gray-100 dark:bg-surface-800 border-gray-200 dark:border-surface-700'}`}>
        <span className={`font-semibold font-mono ${result.is_error ? 'text-error-600 dark:text-error-400' : 'text-gray-900 dark:text-surface-200'}`}>
          {result.is_error ? 'Error Result' : 'Tool Result'}
        </span>
        <span className="text-xs text-gray-500 dark:text-surface-400 ml-2 font-mono">({result.tool_use_id})</span>
        {toolName && <span className="text-xs text-gray-500 dark:text-surface-400 ml-2 font-mono">• {toolName}</span>}
      </div>
      <div className="p-4 overflow-x-auto bg-gray-50 dark:bg-surface-900/50">
        {result.is_error ? (
          <pre className="text-sm whitespace-pre-wrap text-error-600 dark:text-error-400 font-mono">{typeof content === 'string' ? content : safeStringify(content)}</pre>
        ) : (
          <CodeBlockWithCopy
            language={language}
            content={content as string}
            customStyle={{
              margin: 0,
              padding: 0,
              backgroundColor: 'transparent',
              fontSize: '0.875rem',
            }}
            wrapLines={true}
            showLineNumbers={language !== 'plaintext' && language !== 'bash' && (content as string).split('\n').length > 5}
          />
        )}
      </div>
    </div>
  );
}

function detectLanguageFromContent(content: string): string {
  const lines = content.trim().split('\n');
  const firstLine = lines[0] || '';
  const firstFewLines = lines.slice(0, 10).join('\n');

  // Shebang detection
  if (firstLine.startsWith('#!/usr/bin/env python') || firstLine.startsWith('#!/usr/bin/python')) return 'python';
  if (firstLine.startsWith('#!/bin/bash') || firstLine.startsWith('#!/bin/sh') || firstLine.startsWith('#!/usr/bin/env bash')) return 'bash';
  if (firstLine.startsWith('#!/usr/bin/env node')) return 'javascript';

  // Python patterns
  if (/^(from\s+\S+\s+import|import\s+\S+)/.test(firstLine)) return 'python';
  if (/^(def\s+\w+\s*\(|class\s+\w+[:\(]|async\s+def\s+)/.test(firstLine)) return 'python';
  if (/"""/.test(firstFewLines) || /^@\w+/.test(firstLine)) return 'python';

  // TypeScript/JavaScript patterns
  if (/^(import\s+.*from\s+['"]|export\s+(default\s+)?(function|class|const|interface|type))/.test(firstLine)) return 'typescript';
  if (/^(const|let|var)\s+\w+\s*(:|=)/.test(firstLine)) return 'typescript';
  if (/^(function\s+\w+|async\s+function)/.test(firstLine)) return 'javascript';
  if (/^(interface|type)\s+\w+\s*(=|{|\<)/.test(firstLine)) return 'typescript';

  // Go patterns
  if (/^package\s+\w+/.test(firstLine)) return 'go';
  if (/^(func|type|var|const)\s+/.test(firstLine) && /\{$/.test(firstLine)) return 'go';

  // Rust patterns
  if (/^(use\s+|fn\s+|mod\s+|pub\s+(fn|struct|enum|mod)|impl\s+|struct\s+|enum\s+)/.test(firstLine)) return 'rust';
  if (/^#\[(derive|cfg|allow|warn)\(/.test(firstLine)) return 'rust';

  // JSON detection
  if ((firstLine.startsWith('{') || firstLine.startsWith('[')) && /^[\s\[\]{}"':,\d\w\-\.]+$/.test(firstFewLines)) {
    try {
      JSON.parse(content.trim());
      return 'json';
    } catch {
      // Not valid JSON
    }
  }

  // YAML patterns
  if (/^[\w\-]+:\s*(\S|$)/.test(firstLine) && !firstLine.includes('{')) return 'yaml';

  // HTML/XML patterns
  if (/^<(!DOCTYPE|html|xml|\?xml)/.test(firstLine.trim())) return 'xml';
  if (/^<\w+[\s>]/.test(firstLine.trim()) && /<\/\w+>/.test(content)) return 'xml';

  // SQL patterns
  if (/^(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|WITH)\s+/i.test(firstLine)) return 'sql';

  // CSS patterns
  if (/^(\.|#|@media|@import|[\w\-]+\s*\{)/.test(firstLine) && /\{[\s\S]*\}/.test(firstFewLines)) return 'css';

  // Bash/shell patterns (command output, etc.)
  if (/^\$\s+/.test(firstLine) || /^(cd|ls|cat|grep|find|echo|export|source)\s+/.test(firstLine)) return 'bash';

  return 'plaintext';
}

function getLanguageFromPath(filePath: string | undefined): string {
  if (!filePath) return 'plaintext';

  const ext = filePath.split('.').pop()?.toLowerCase();
  switch (ext) {
    case 'ts':
    case 'tsx':
      return 'typescript';
    case 'js':
    case 'jsx':
      return 'javascript';
    case 'py':
      return 'python';
    case 'json':
      return 'json';
    case 'sh':
    case 'bash':
      return 'bash';
    case 'go':
      return 'go';
    case 'rs':
      return 'rust';
    case 'css':
      return 'css';
    case 'html':
    case 'xml':
      return 'xml';
    case 'sql':
      return 'sql';
    case 'yaml':
    case 'yml':
      return 'yaml';
    case 'md':
      return 'markdown';
    default:
      return 'plaintext';
  }
}
