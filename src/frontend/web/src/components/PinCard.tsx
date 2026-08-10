import { useMemo } from 'react';
import { useStore, type Pin } from '../store';
import { localeTag, pick } from '../locale';

const STATUS_LABELS: Record<string, Record<string, string>> = {
  done: { zh: '已完成', en: 'Done' },
  failed: { zh: '执行失败', en: 'Failed' },
  waiting_confirm: { zh: '需要你决定', en: 'Needs decision' },
};

interface PinCardProps {
  pin: Pin;
  onExpand: (pin: Pin) => void;
  onAsk: (pin: Pin) => void;
  onArchive: (pin: Pin) => void;
}

export function PinCard({ pin, onExpand, onAsk, onArchive }: PinCardProps) {
  const locale = useStore((s) => s.locale);

  const isRecent = useMemo(() => {
    const created = new Date(pin.created_at);
    const threeDaysAgo = new Date();
    threeDaysAgo.setDate(threeDaysAgo.getDate() - 3);
    return created >= threeDaysAgo;
  }, [pin.created_at]);

  const visible = isRecent || !pin.read;

  if (!visible) return null;

  const timeLabel = useMemo(() => {
    const created = new Date(pin.created_at);
    const now = new Date();
    const diffMs = now.getTime() - created.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    const diffHr = Math.floor(diffMs / 3600000);
    const diffDay = Math.floor(diffMs / 86400000);

    if (diffMin < 60) return pick(locale, `${diffMin}分钟前`, `${diffMin}m ago`);
    if (diffHr < 24) return pick(locale, `${diffHr}小时前`, `${diffHr}h ago`);
    return pick(locale, `${diffDay}天前`, `${diffDay}d ago`);
  }, [pin.created_at, locale]);

  const statusLabel = STATUS_LABELS[pin.status]?.[localeTag(locale)] || pin.status;

  return (
    <div
      className={`pin-card ${!pin.read ? 'pin-card--unread' : 'pin-card--read'}`}
      onClick={() => onExpand(pin)}
    >
      {!pin.read && <span className="pin-card__dot" />}
      <div className="pin-card__header">
        <span className="pin-card__title">{pin.title}</span>
        <span className="pin-card__time">{timeLabel}</span>
      </div>
      <div className="pin-card__body">
        <span className={`pin-card__status pin-card__status--${pin.status}`}>
          {statusLabel}
        </span>
        <p className="pin-card__summary">{pin.summary}</p>
      </div>
      <div className="pin-card__actions">
        <button
          className="pin-card__btn pin-card__btn--expand"
          onClick={(e) => { e.stopPropagation(); onExpand(pin); }}
        >
          {pick(locale, '展开', 'Expand')}
        </button>
        <button
          className="pin-card__btn pin-card__btn--ask"
          onClick={(e) => { e.stopPropagation(); onAsk(pin); }}
        >
          {pick(locale, '追问', 'Ask')}
        </button>
        <button
          className="pin-card__btn pin-card__btn--archive"
          onClick={(e) => { e.stopPropagation(); onArchive(pin); }}
        >
          {pick(locale, '归档', 'Archive')}
        </button>
      </div>
    </div>
  );
}
