import { useEffect, useState } from 'react';
import { api } from '../api';
import { pick } from '../locale';
import { useStore, type SessionMessage } from '../store';
import { Msg } from './SessionMsg';

export function SessionViewer({ taskId, onClose }: { taskId: string; onClose: () => void }) {
  const locale = useStore((s) => s.locale);
  const [loading, setLoading] = useState(true);
  const [messages, setMessages] = useState<SessionMessage[]>([]);
  const [title, setTitle] = useState(pick(locale, '任务会话', 'Task Session'));
  const [status, setStatus] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setMessages([]);

    api.getTaskSession(taskId)
      .then((data) => {
        if (!cancelled) {
          setTitle(data.title || pick(locale, '任务会话', 'Task Session'));
          setStatus(data.status || '');
          setMessages(data.messages || []);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err.message || pick(locale, '加载会话失败', 'Failed to load session'));
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [locale, taskId]);

  const messageCount = messages.length;
  const toolCount = messages.filter((m) => m.role === 'tool_call' || m.role === 'tool_result').length;

  return (
    <div
      className="session-overlay"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="session-panel">
        <div className="session-header">
          <div className="session-header-info">
            <div className="session-header-top">
              <span className="session-icon">◇</span>
              <h3 className="session-title">{title}</h3>
            </div>
            <p className="session-subtitle">
              {pick(locale, '会话历史', 'Session history')}
              {status && <span className="session-status-badge">{status}</span>}
              {messageCount > 0 && (
                <span className="session-stats">
                  <span className="session-stat">{messageCount} {pick(locale, '条消息', 'messages')}</span>
                  {toolCount > 0 && (
                    <span className="session-stat session-stat-tool">
                      {toolCount} {pick(locale, '工具调用', 'tool calls')}
                    </span>
                  )}
                </span>
              )}
            </p>
          </div>
          <button onClick={onClose} className="session-close" title={pick(locale, '关闭（Esc）', 'Close (Esc)')}>
            {pick(locale, '关闭', 'Close')}
          </button>
        </div>

        <div className="session-body">
          {loading && (
            <div className="session-empty session-loading">
              <span className="loading-spinner" />
              <p>{pick(locale, '正在加载会话...', 'Loading session...')}</p>
            </div>
          )}

          {error && (
            <div className="session-empty session-error">
              <span className="error-icon">!</span>
              <p>{pick(locale, '加载会话时出错', 'Error loading session')}</p>
              <code>{error}</code>
            </div>
          )}

          {!loading && !error && messages.length === 0 && (
            <div className="session-empty">
              <span className="empty-icon">◇</span>
              <p>{pick(locale, '这条任务暂时还没有会话记录。', 'No session data for this task yet.')}</p>
            </div>
          )}

          {!loading && !error && messages.length > 0 && (
            <div className="session-messages">
              {messages.map((message, index) => (
                <Msg key={index} msg={message} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
