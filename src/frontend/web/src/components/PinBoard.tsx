import { useEffect, useState } from 'react';
import { api } from '../api';
import { useStore, type Pin } from '../store';
import { localeTag, pick } from '../locale';
import { PinCard } from './PinCard';

export function PinBoard({
  onExpand,
  onAsk,
}: {
  onExpand: (pin: Pin) => void;
  onAsk: (pin: Pin) => void;
}) {
  const locale = useStore((s) => s.locale);
  const pins = useStore((s) => s.pins);
  const setPins = useStore((s) => s.setPins);
  const updatePin = useStore((s) => s.updatePin);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getPins()
      .then((r) => setPins(r.pins))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [setPins]);

  const handleArchive = async (pin: Pin) => {
    try {
      await api.archivePin(pin.thread_id);
      updatePin({ ...pin, read: true });
    } catch {
      // silently ignore
    }
  };

  if (loading) {
    return (
      <section className="pin-board">
        <h2 className="pin-board__title">
          {pick(locale, '📌 便签墙', '📌 Pin Board')}
        </h2>
        <div className="pin-board__loading">
          {pick(locale, '加载中...', 'Loading...')}
        </div>
      </section>
    );
  }

  const visiblePins = pins.filter((pin) => {
    if (!pin.read) return true;
    const created = new Date(pin.created_at);
    const threeDaysAgo = new Date();
    threeDaysAgo.setDate(threeDaysAgo.getDate() - 3);
    return created >= threeDaysAgo;
  });

  return (
    <section className="pin-board">
      <h2 className="pin-board__title">
        {pick(locale, '📌 便签墙', '📌 Pin Board')}
      </h2>
      {visiblePins.length === 0 ? (
        <div className="pin-board__empty">
          {pick(locale, '还没有便签，派发一个任务试试吧', 'No pins yet — dispatch a task to get started')}
        </div>
      ) : (
        <div className="pin-board__grid">
          {visiblePins.map((pin) => (
            <PinCard
              key={pin.thread_id}
              pin={pin}
              onExpand={onExpand}
              onAsk={onAsk}
              onArchive={handleArchive}
            />
          ))}
        </div>
      )}
    </section>
  );
}
