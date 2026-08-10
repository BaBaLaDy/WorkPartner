import { useEffect, useState } from 'react';
import { api } from '../api';
import { localeTag, pick } from '../locale';
import { useStore, type ChatSession, type SessionMessage } from '../store';
import { Msg } from './SessionMsg';

const FILTERS = [
  { value: 'all', label: { zh: '全部', en: 'All' } },
  { value: 'interactive', label: { zh: '互动', en: 'Interactive' } },
  { value: 'managed', label: { zh: '托管', en: 'Managed' } },
] as const;

type FilterValue = (typeof FILTERS)[number]['value'];

function formatDay(locale: 'zh' | 'en', dateStr: string): string {
  const date = new Date(dateStr);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  if (date.toDateString() === today.toDateString()) return pick(locale, '今天', 'Today');
  if (date.toDateString() === yesterday.toDateString()) return pick(locale, '昨天', 'Yesterday');

  return new Intl.DateTimeFormat(localeTag(locale), {
    month: 'long',
    day: 'numeric',
    ...(date.getFullYear() !== today.getFullYear() ? { year: 'numeric' } : {}),
  }).format(date);
}

function formatTime(locale: 'zh' | 'en', dateStr: string): string {
  return new Date(dateStr).toLocaleTimeString(localeTag(locale), {
    hour: 'numeric',
    minute: '2-digit',
  });
}

function formatFullDate(locale: 'zh' | 'en', dateStr: string): string {
  return new Date(dateStr).toLocaleString(localeTag(locale), {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function groupByDate(locale: 'zh' | 'en', sessions: ChatSession[]) {
  const map = new Map<string, ChatSession[]>();

  for (const session of sessions) {
    const key = new Date(session.created_at).toDateString();
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(session);
  }

  return Array.from(map.entries())
    .map(([key, items]) => ({
      dateKey: key,
      dateLabel: formatDay(locale, items[0].created_at),
      sessions: [...items].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      ),
    }))
    .sort(
      (a, b) =>
        new Date(b.sessions[0].created_at).getTime() -
        new Date(a.sessions[0].created_at).getTime(),
    );
}

function truncate(text: string, max = 72) {
  if (!text) return '';
  return text.length > max ? `${text.slice(0, max)}...` : text;
}

export function TimelineTab() {
  const locale = useStore((s) => s.locale);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [filter, setFilter] = useState<FilterValue>('all');
  const [msgCache, setMsgCache] = useState<Map<string, SessionMessage[]>>(new Map());
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getSessions()
      .then((response) => {
        setSessions(response.sessions);
        setLoading(false);

        Promise.allSettled(
          response.sessions.map((session) =>
            api.getSessionMessages(session.thread_id)
              .then((data) => ({ id: session.thread_id, messages: data.messages })),
          ),
        ).then((results) => {
          const cache = new Map<string, SessionMessage[]>();
          for (const result of results) {
            if (result.status === 'fulfilled') {
              cache.set(result.value.id, result.value.messages);
            }
          }
          setMsgCache(cache);
        });
      })
      .catch(() => setLoading(false));
  }, []);

  const filtered = filter === 'all'
    ? sessions
    : sessions.filter((session) => session.session_type === filter);

  const grouped = groupByDate(locale, filtered);
  const activeSession = activeId ? sessions.find((session) => session.thread_id === activeId) : null;
  const activeMessages = activeId ? msgCache.get(activeId) ?? null : null;
  const isManaged = activeSession?.session_type === 'managed';

  return (
    <div className="tl-page">
      <div className="tl-topbar">
        <div className="tl-topbar-copy">
          <span className="tl-topbar-title">{pick(locale, '纪事簿', 'Story Ledger')}</span>
          <p className="tl-topbar-subtitle">
            {pick(
              locale,
              '这里会柔和地记录互动会话和托管会话的完整轨迹。',
              'A softer record of interactive chats and managed sessions.',
            )}
          </p>
        </div>
        <div className="tl-filters">
          {FILTERS.map((item) => (
            <button
              key={item.value}
              className={`tl-filter-btn ${filter === item.value ? 'active' : ''}`}
              onClick={() => setFilter(item.value)}
            >
              {pick(locale, item.label.zh, item.label.en)}
            </button>
          ))}
        </div>
      </div>

      <div className="ledger-shell">
        <div className="tl-list ledger-list">
          {loading && <div className="tl-empty">{pick(locale, '正在加载会话...', 'Loading sessions...')}</div>}
          {!loading && filtered.length === 0 && (
            <div className="tl-empty">{pick(locale, '这里还没有任何记录。', 'No stories have been recorded yet.')}</div>
          )}

          {!loading && grouped.map((group, groupIndex) => (
            <div key={group.dateKey} className="tl-group">
              <div className="tl-date-header">
                <span>{group.dateLabel}</span>
              </div>

              {group.sessions.map((session, sessionIndex) => {
                const isActive = session.thread_id === activeId;
                const sessionManaged = session.session_type === 'managed';
                const firstUser = msgCache
                  .get(session.thread_id)
                  ?.find((message) => message.role === 'user');
                const summary = truncate(String(firstUser?.content ?? ''), 64);
                const isLastItem =
                  groupIndex === grouped.length - 1 && sessionIndex === group.sessions.length - 1;

                return (
                  <div
                    key={session.thread_id}
                    className={`tl-entry ${isActive ? 'active' : ''}`}
                    onClick={() =>
                      setActiveId((prev) => (prev === session.thread_id ? null : session.thread_id))
                    }
                  >
                    <div className="tl-spine">
                      <div
                        className={`tl-dot ${sessionManaged ? 'dot-managed' : 'dot-interactive'} ${isActive ? 'dot-active' : ''}`}
                      />
                      {!isLastItem && <div className="tl-line" />}
                    </div>

                    <div className="tl-entry-content">
                      <div className="tl-entry-row1">
                        <span className="tl-entry-name">{session.name}</span>
                        <span className="tl-entry-time">{formatTime(locale, session.created_at)}</span>
                      </div>
                      {summary && <div className="tl-entry-summary">{summary}</div>}
                      <span
                        className={`tl-badge ${sessionManaged ? 'tl-badge-managed' : 'tl-badge-interactive'}`}
                      >
                        {sessionManaged
                          ? pick(locale, '托管', 'managed')
                          : pick(locale, '互动', 'interactive')}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>

        {activeId ? (
          <div className="tl-detail" key={activeId}>
            <div className="tl-detail-header">
              <div className="tl-detail-header-info">
                <span className="tl-detail-title">{activeSession?.name ?? activeId}</span>
                <span className={`tl-badge ${isManaged ? 'tl-badge-managed' : 'tl-badge-interactive'}`}>
                  {isManaged ? pick(locale, '托管', 'managed') : pick(locale, '互动', 'interactive')}
                </span>
              </div>
              <div className="tl-detail-header-right">
                {activeSession?.created_at && (
                  <span className="tl-detail-date">{formatFullDate(locale, activeSession.created_at)}</span>
                )}
                <button className="tl-detail-close" onClick={() => setActiveId(null)} title={pick(locale, '关闭', 'Close')}>
                  {pick(locale, '关闭', 'Close')}
                </button>
              </div>
            </div>

            <div className="tl-detail-body">
              {activeMessages === null ? (
                <div className="tl-empty">{pick(locale, '正在加载...', 'Loading...')}</div>
              ) : activeMessages.length === 0 ? (
                <div className="tl-empty">{pick(locale, '这个会话暂时还没有消息。', 'This session has no messages yet.')}</div>
              ) : (
                <div className="session-messages">
                  {activeMessages.map((message, index) => (
                    <Msg key={index} msg={message} />
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="tl-detail ledger-placeholder">
            <div className="ledger-placeholder-copy">
              <h3>{pick(locale, '从左侧打开一条记录', 'Open a story from the left')}</h3>
              <p>
                {pick(
                  locale,
                  '选择任意会话或托管记录，就能在不改变页面布局的情况下阅读完整轨迹。',
                  'Pick any conversation or managed session to read the full trail without shifting the whole page layout.',
                )}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
