/**
 * Table cell content that truncates with ellipsis and shows full value in a tooltip on hover.
 */
import { Tooltip } from 'flowbite-react';

interface TruncatedCellProps {
  value: string | null | undefined;
  maxLength?: number;
  className?: string;
  /** Placeholder when value is empty (default: "—") */
  emptyPlaceholder?: string;
}

export function TruncatedCell({
  value,
  maxLength,
  className = '',
  emptyPlaceholder = '—',
}: TruncatedCellProps) {
  const text = value ?? '';
  const isEmpty = text === '';

  if (isEmpty) {
    return <span className={`block truncate whitespace-nowrap ${className}`}>{emptyPlaceholder}</span>;
  }

  const showTooltip = maxLength == null || text.length > maxLength;
  const content = (
    <span
      className={`block truncate whitespace-nowrap min-w-0 max-w-full ${className}`}
      style={maxLength != null ? { maxWidth: '12rem' } : undefined}
    >
      {text}
    </span>
  );

  if (showTooltip) {
    return (
      <Tooltip content={text} placement="top">
        {content}
      </Tooltip>
    );
  }

  return content;
}
