import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api, sendChatMessage } from '../api';
import { pick } from '../locale';
import { buildCollaborationCards, buildOfficeSnapshot } from '../office';
import { useStore } from '../store';

type LiveSystemCard = {
  id: string;
  tone: 'active' | 'success' | 'warning';
  title: string;
  detail: string;
};

function humanizeToolName(locale: 'zh' | 'en', name: string) {
  const known: Record<string, { zh: string; en: string }> = {
    file_read: { zh: '读取文件', en: 'Read file' },
    file_write: { zh: '写入文件', en: 'Write file' },
    file_patch: { zh: '修改文件', en: 'Patch file' },
    web_search: { zh: '网页搜索', en: 'Web search' },
    web_extract: { zh: '网页提取', en: 'Extract page' },
    todo_list: { zh: '读取待办', en: 'Read todos' },
    todo_update: { zh: '更新待办', en: 'Update todo' },
    subagent_batch: { zh: '分派成员', en: 'Dispatch teammates' },
  };
  const item = known[name];
  if (item) return pick(locale, item.zh, item.en);
  return name.replace(/_/g, ' ');
}

function summarizeToolArgs(value: unknown) {
  if (!value || typeof value !== 'object') return '';
  const record = value as Record<string, unknown>;
  const preferredKeys = ['path', 'query', 'url', 'title', 'task_id', 'name', 'target'];
  for (const key of preferredKeys) {
    const raw = record[key];
    if (typeof raw === 'string' && raw.trim()) {
      return raw.length > 56 ? `${raw.slice(0, 53)}...` : raw;
    }
  }
  const first = Object.entries(record)[0];
  if (!first) return '';
  const [key, raw] = first;
  const valueText = String(raw);
  return `${key}: ${valueText.length > 44 ? `${valueText.slice(0, 41)}...` : valueText}`;
}

function summarizeToolOutput(locale: 'zh' | 'en', value: unknown) {
  if (!value) return '';
  try {
    const raw = typeof value === 'string' ? value : JSON.stringify(value);
    const clean = raw.replace(/\s+/g, ' ').trim();
    if (!clean) return '';
    if (clean.length > 84 || clean.startsWith('{') || clean.startsWith('[')) {
      return pick(locale, '结果已回收进回复。', 'Result folded into the reply.');
    }
    return clean;
  } catch {
    return pick(locale, '结果已返回。', 'Result received.');
  }
}

export function ChatTab() {
  const locale = useStore((s) => s.locale);
  const messages = useStore((s) => s.messages);
  const setMessages = useStore((s) => s.setMessages);
  const addMessage = useStore((s) => s.addMessage);
  const isStreaming = useStore((s) => s.isStreaming);
  const setStreaming = useStore((s) => s.setStreaming);
  const chatSessions = useStore((s) => s.chatSessions);
  const setChatSessions = useStore((s) => s.setChatSessions);
  const activeThreadId = useStore((s) => s.activeThreadId);
  const setActiveThreadId = useStore((s) => s.setActiveThreadId);
  const supervisorStatus = useStore((s) => s.supervisorStatus);
  const roleActivities = useStore((s) => s.roleActivities);
  const dispatchLog = useStore((s) => s.dispatchLog);
  const roles = useStore((s) => s.roles);
  const events = useStore((s) => s.events);

  const [input, setInput] = useState('');
  const [streamingText, setStreamingText] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [showNewSessionInput, setShowNewSessionInput] = useState(false);
  const [newSessionName, setNewSessionName] = useState('');
  const [thinkingNote, setThinkingNote] = useState('');
  const [liveCards, setLiveCards] = useState<LiveSystemCard[]>([]);
  const [sessionFilter, setSessionFilter] = useState<'free' | 'task'>('free');
  const [allSessions, setAllSessions] = useState<typeof chatSessions>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const officeSnapshot = useMemo(
    () => buildOfficeSnapshot(locale, supervisorStatus, roleActivities, dispatchLog),
    [dispatchLog, locale, roleActivities, supervisorStatus],
  );
  const recentCards = useMemo(
    () => buildCollaborationCards(locale, events, roles, 4),
    [events, locale, roles],
  );
  const visibleCards = useMemo(() => {
    const recent = recentCards.map((card) => ({
      id: card.id,
      tone:
        card.tone === 'calm'
          ? 'active'
          : card.tone === 'warning'
            ? 'warning'
            : 'success',
      title: card.title,
      detail: card.detail,
    }));
    return [...liveCards, ...recent].slice(0, 2);
  }, [liveCards, recentCards]);

  const filteredSessions = useMemo(() => {
    const all = allSessions.length > 0 ? allSessions : chatSessions;
    if (sessionFilter === 'free') return all.filter((s) => s.session_type === 'interactive');
    return all.filter((s) => s.session_type === 'managed');
  }, [allSessions, chatSessions, sessionFilter]);

  const quickActions = useMemo(
    () => [
      pick(locale, '现在谁在忙什么？', 'Who is handling what right now?'),
      pick(locale, '先推进最重要的待办。', 'Start with the most important queued work.'),
      pick(locale, '今天完成了哪些事？', 'What got wrapped today?'),
    ],
    [locale],
  );

  const pushLiveCard = useCallback((card: LiveSystemCard) => {
    setLiveCards((current) => [card, ...current].slice(0, 2));
  }, []);

  const loadMessages = useCallback(
    (threadId: string) => {
      api.getSessionMessages(threadId)
        .then((data) => {
          const chatMsgs = data.messages
            .filter((message) => message.role === 'user' || message.role === 'assistant')
            .map((message) => ({
              role: message.role as 'user' | 'assistant',
              content: message.content ?? '',
            }));
          setMessages(chatMsgs);
        })
        .catch(() => {});
    },
    [setMessages],
  );

  useEffect(() => {
    api.getSessions()
      .then((data) => {
        setChatSessions(data.sessions);
        setAllSessions(data.sessions);
        setActiveThreadId(data.active_thread_id);
        if (data.active_thread_id) {
          loadMessages(data.active_thread_id);
        }
      })
      .catch(() => {});
  }, [loadMessages, setActiveThreadId, setChatSessions]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [isStreaming, messages, streamingText]);

  const handleSelectSession = async (session: (typeof chatSessions)[number]) => {
    if (session.thread_id === activeThreadId) {
      setSidebarOpen(false);
      return;
    }

    try {
      await api.updateSession(session.thread_id, { action: 'switch' });
      setActiveThreadId(session.thread_id);
      setMessages([]);
      loadMessages(session.thread_id);
    } catch (error) {
      console.error('Failed to switch session:', error);
    }

    setSidebarOpen(false);
  };

  const handleCreateSession = async () => {
    const name =
      newSessionName.trim() ||
      pick(locale, `会话 ${chatSessions.length + 1}`, `Conversation ${chatSessions.length + 1}`);

    try {
      const data = await api.createSession(name);
      await api.updateSession(data.thread_id, { action: 'switch' });
      setActiveThreadId(data.thread_id);
      setMessages([]);
      setChatSessions([
        ...chatSessions,
        {
          thread_id: data.thread_id,
          name: data.name,
          created_at: new Date().toISOString(),
          last_active: new Date().toISOString(),
          active: true,
          session_type: 'interactive',
          owner: 'ui',
        },
      ]);
    } catch (error) {
      console.error('Failed to create session:', error);
    }

    setNewSessionName('');
    setShowNewSessionInput(false);
  };

  const handleDeleteSession = async (
    session: (typeof chatSessions)[number],
    event: React.MouseEvent,
  ) => {
    event.stopPropagation();

    try {
      await api.updateSession(session.thread_id, { action: 'delete' });
      const remaining = chatSessions.filter((item) => item.thread_id !== session.thread_id);
      setChatSessions(remaining);

      if (session.thread_id === activeThreadId) {
        if (remaining.length > 0) {
          const latest = remaining[remaining.length - 1];
          await api.updateSession(latest.thread_id, { action: 'switch' });
          setActiveThreadId(latest.thread_id);
          loadMessages(latest.thread_id);
        } else {
          const data = await api.createSession(pick(locale, '新会话', 'New Conversation'));
          await api.updateSession(data.thread_id, { action: 'switch' });
          setActiveThreadId(data.thread_id);
          setMessages([]);
          setChatSessions([
            {
              thread_id: data.thread_id,
              name: data.name,
              created_at: new Date().toISOString(),
              last_active: new Date().toISOString(),
              active: true,
              session_type: 'interactive',
              owner: 'ui',
            },
          ]);
        }
      }
    } catch (error) {
      console.error('Failed to delete session:', error);
    }
  };

  const handleSend = async () => {
    if (!input.trim() || isStreaming) return;

    const userMsg = input.trim();
    setInput('');
    addMessage({ role: 'user', content: userMsg });
    setStreaming(true);
    setStreamingText('');
    setThinkingNote('');
    setLiveCards([]);

    let accumulated = '';
    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      await sendChatMessage(
        userMsg,
        (text) => {
          accumulated += text;
          setStreamingText(accumulated);
        },
        () => {
          if (accumulated) {
            addMessage({ role: 'assistant', content: accumulated });
          }
          setStreaming(false);
          setStreamingText('');
          setThinkingNote('');
          abortControllerRef.current = null;
          api.getSessions()
            .then((data) => {
              setChatSessions(data.sessions);
              setActiveThreadId(data.active_thread_id);
            })
            .catch(() => {});
        },
        activeThreadId || undefined,
        controller.signal,
        (event) => {
          if (event.type === 'thinking' && event.content) {
            setThinkingNote(event.content);
            return;
          }

          if (event.type === 'tool_start') {
            const name = String(event.data?.name || pick(locale, '某个工具', 'a tool'));
            pushLiveCard({
              id: `start-${Date.now()}-${name}`,
              tone: 'active',
              title: pick(
                locale,
                `大管家开始调用 ${humanizeToolName(locale, name)}`,
                `Supervisor started ${humanizeToolName(locale, name)}`,
              ),
              detail: summarizeToolArgs(event.data?.input),
            });
            return;
          }

          if (event.type === 'tool_end') {
            const name = String(event.data?.name || pick(locale, '某个工具', 'a tool'));
            pushLiveCard({
              id: `end-${Date.now()}-${name}`,
              tone: 'success',
              title: pick(
                locale,
                `${humanizeToolName(locale, name)} 已返回结果`,
                `${humanizeToolName(locale, name)} came back with output`,
              ),
              detail: summarizeToolOutput(locale, event.data?.output),
            });
          }
        },
      );
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        setStreaming(false);
        setStreamingText('');
        setThinkingNote('');
        if (accumulated) {
          addMessage({ role: 'assistant', content: accumulated });
        }
      } else {
        addMessage({ role: 'assistant', content: `Error: ${error}` });
        pushLiveCard({
          id: `error-${Date.now()}`,
          tone: 'warning',
          title: pick(locale, '这次交办中途被打断了', 'This handoff was interrupted'),
          detail: String(error),
        });
        setStreaming(false);
        setStreamingText('');
        setThinkingNote('');
      }
      abortControllerRef.current = null;
    }
  };

  const handleAbort = () => {
    abortControllerRef.current?.abort();
  };

  const activeSession = chatSessions.find((session) => session.thread_id === activeThreadId);

  return (
    <div className="lounge-page">
      <header className="lounge-header">
        <div className="lounge-header-copy">
          <span className="lounge-kicker">{pick(locale, '大管家', 'Supervisor')}</span>
          <h2 className="page-title">
            {activeSession?.name || pick(locale, '和大管家聊聊', 'Chat with Supervisor')}
          </h2>
          <p className="page-intro">
            {pick(
              locale,
              '这里不是普通聊天框，而是你和办公室前台交办、追问、跟进进展的地方。',
              'This is where you brief, follow up, and close the loop with the office front desk.',
            )}
          </p>
        </div>
        <button className="lounge-rooms-btn" onClick={() => setSidebarOpen(!sidebarOpen)}>
          {pick(locale, '会话列表', 'Rooms')}
        </button>
      </header>

      <div className="lounge-shell">
        <aside className={`lounge-sidebar ${sidebarOpen ? 'open' : ''}`}>
          <div className="lounge-sidebar-head">
            <div>
              <h3>{pick(locale, '会话列表', 'Conversation list')}</h3>
              <p>{pick(locale, '切换、创建或清理会话。', 'Switch, create, or clean up sessions.')}</p>
            </div>
            <button className="lounge-new-btn" onClick={() => setShowNewSessionInput(true)}>
              + {pick(locale, '新建', 'New')}
            </button>
          </div>

          {showNewSessionInput && (
            <div className="lounge-new-card">
              <input
                type="text"
                value={newSessionName}
                onChange={(event) => setNewSessionName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') handleCreateSession();
                }}
                placeholder={pick(locale, '给这个会话起个名字', 'Name this conversation')}
                autoFocus
              />
              <div className="lounge-new-actions">
                <button onClick={handleCreateSession}>{pick(locale, '创建', 'Create')}</button>
                <button
                  onClick={() => {
                    setShowNewSessionInput(false);
                    setNewSessionName('');
                  }}
                >
                  {pick(locale, '取消', 'Cancel')}
                </button>
              </div>
            </div>
          )}

          <div className="lounge-filter">
            <button
              className={`lounge-filter-btn ${sessionFilter === 'free' ? 'active' : ''}`}
              onClick={() => setSessionFilter('free')}
            >
              {pick(locale, '💬 自由对话', '💬 Free chat')}
            </button>
            <button
              className={`lounge-filter-btn ${sessionFilter === 'task' ? 'active' : ''}`}
              onClick={() => setSessionFilter('task')}
            >
              {pick(locale, '📋 任务对话', '📋 Task chat')}
            </button>
          </div>

          <div className="lounge-session-list">
            {filteredSessions.map((session) => (
              <button
                key={session.thread_id}
                className={`lounge-session-item ${session.thread_id === activeThreadId ? 'active' : ''}`}
                onClick={() => handleSelectSession(session)}
              >
                <div className="lounge-session-copy">
                  <span className="lounge-session-title">{session.name}</span>
                  <span className="lounge-session-time">{timeAgo(locale, session.last_active)}</span>
                </div>
                <span
                  className="lounge-session-delete"
                  onClick={(event) => handleDeleteSession(session, event)}
                  title={pick(locale, '删除会话', 'Delete conversation')}
                  role="button"
                >
                  ×
                </span>
              </button>
            ))}
          </div>
        </aside>

        {sidebarOpen && (
          <button
            className="lounge-backdrop"
            onClick={() => setSidebarOpen(false)}
            aria-label={pick(locale, '关闭会话列表', 'Close conversation list')}
          />
        )}

        <section className="lounge-main">
          <div className="lounge-thread">
            {messages.length === 0 && !streamingText && (
              <div className="lounge-empty">
                <h3>{pick(locale, '🐒大管家', '🐒Supervisor is online')}</h3>
                <p>
                  {pick(
                    locale,
                    '你可以问今天进展、失败原因，也可以直接把下一件事交给办公室。',
                    'Ask for status, blockers, or hand the next task straight to the office.',
                  )}
                </p>
              </div>
            )}

            {messages.map((message, index) => (
              <article
                key={index}
                className={`lounge-message lounge-message-${message.role}`}
              >
                {message.role === 'user' && (
                  <div className="lounge-bubble lounge-bubble-user">
                    <p>{message.content}</p>
                  </div>
                )}
                <div className="lounge-message-meta">
                  <span className="lounge-avatar">
                    {message.role === 'user' ? pick(locale, '你', 'You') : '🪑'}
                  </span>
                </div>
                {message.role === 'assistant' && (
                  <div className="lounge-bubble lounge-bubble-assistant">
                    <div className="lounge-markdown">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {message.content}
                      </ReactMarkdown>
                    </div>
                  </div>
                )}
              </article>
            ))}

            {streamingText && (
              <article className="lounge-message lounge-message-assistant">
                <div className="lounge-message-meta">
                  <span className="lounge-avatar">🪑</span>
                </div>
                <div className="lounge-bubble lounge-bubble-assistant">
                  <div className="lounge-markdown">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {streamingText}
                    </ReactMarkdown>
                  </div>
                  <span className="lounge-cursor" />
                </div>
              </article>
            )}

            {isStreaming && !streamingText && (
              <article className="lounge-message lounge-message-assistant">
                <div className="lounge-message-meta">
                  <span className="lounge-avatar">🪑</span>
                </div>
                <div className="lounge-thinking">
                  <span>{pick(locale, '正在整理中', 'Working through it')}</span>
                  <span className="lounge-thinking-dots">
                    <span />
                    <span />
                    <span />
                  </span>
                </div>
              </article>
            )}

            <div ref={bottomRef} />
          </div>

          <div className="lounge-dock">
            {(thinkingNote || visibleCards.length > 0) && (
              <div className="lounge-dock-section lounge-dock-activity">
                {thinkingNote && (
                  <div className="lounge-dock-line">
                    <strong>{pick(locale, '思路', 'Thinking')}</strong>
                    <span>{thinkingNote}</span>
                  </div>
                )}
                {visibleCards.map((card) => (
                  <div key={card.id} className={`lounge-dock-line lounge-dock-line-${card.tone}`}>
                    <strong>{card.title}</strong>
                    {card.detail && <span>{card.detail}</span>}
                  </div>
                ))}
              </div>
            )}

            <div className="lounge-dock-section">
              <div className="lounge-dock-line">
                <strong>{pick(locale, '建议', 'Next')}</strong>
                <span>{officeSnapshot.suggestedPrompt}</span>
              </div>
              {officeSnapshot.attentionItems[0] && (
                <div className="lounge-dock-line lounge-dock-line-warning">
                  <strong>{pick(locale, '提醒', 'Attention')}</strong>
                  <span>{officeSnapshot.attentionItems[0].text}</span>
                </div>
              )}
              {officeSnapshot.learningHighlights[0] && (
                <div className="lounge-dock-line">
                  <strong>{pick(locale, '最近学到', 'Learned')}</strong>
                  <span>
                    {pick(
                      locale,
                      `${officeSnapshot.learningHighlights[0].role} 更适合「${officeSnapshot.learningHighlights[0].task_type}」`,
                      `${officeSnapshot.learningHighlights[0].role} fits "${officeSnapshot.learningHighlights[0].task_type}" better`,
                    )}
                  </span>
                </div>
              )}
            </div>

            <div className="lounge-dock-actions">
              {quickActions.map((prompt) => (
                <button
                  key={prompt}
                  className="lounge-quick-btn"
                  onClick={() => setInput(prompt)}
                  disabled={isStreaming}
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>

          <div className="lounge-composer">
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  handleSend();
                }
              }}
              placeholder={pick(
                locale,
                '交办一件事、追问当前进展，或请大管家帮你汇总结果。',
                'Hand over work, ask for status, or ask the supervisor to close the loop.',
              )}
              disabled={isStreaming}
              className="lounge-input"
              rows={3}
            />
            {isStreaming ? (
              <button
                onClick={handleAbort}
                className="lounge-send-btn lounge-send-btn-abort"
              >
                {pick(locale, '中止', 'Abort')}
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!input.trim()}
                className="lounge-send-btn"
              >
                {pick(locale, '派发', 'Dispatch')}
              </button>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function timeAgo(locale: 'zh' | 'en', iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return pick(locale, '刚刚', 'just now');
  if (mins < 60) return pick(locale, `${mins} 分钟前`, `${mins}m ago`);
  const hours = Math.floor(mins / 60);
  if (hours < 24) return pick(locale, `${hours} 小时前`, `${hours}h ago`);
  const days = Math.floor(hours / 24);
  return pick(locale, `${days} 天前`, `${days}d ago`);
}
