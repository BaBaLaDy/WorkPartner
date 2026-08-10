import { localeTag, pick } from '../locale';
import { useStore, type Task } from '../store';

const priorityColors: Record<string, string> = {
  high: 'tag-high',
  medium: 'tag-medium',
  low: 'tag-low',
};

export function TaskCard({
  task,
  onCancel,
  onDelete,
  onViewSession,
  onRetry,
}: {
  task: Task;
  onCancel: () => void;
  onDelete: () => void;
  onViewSession: () => void;
  onRetry?: () => void;
}) {
  const locale = useStore((s) => s.locale);
  const roles = useStore((s) => s.roles);
  const hasSession = !!task.session_thread_id;
  const role = roles.find((item) => item.name === (task.role || 'task_agent'));
  const roleLabel = role?.display_name || task.role || null;
  const roleIcon = role?.icon || 'WP';
  const isNew = Date.now() - new Date(task.created_at).getTime() < 5000;
  const activeText = role
    ? pick(locale, `${role.display_name} 正在处理这条委托。`, `${role.display_name} is carrying this request.`)
    : pick(locale, '办公室团队正在处理这条委托。', 'The office team is carrying this request.');

  return (
    <div className={`card ${hasSession ? 'card-has-session' : ''} ${isNew ? 'task-new' : ''}`}>
      <div className="card-header">
        <h4
          className="card-title"
          onClick={hasSession ? onViewSession : undefined}
          title={hasSession ? pick(locale, '打开工作会话', 'Open the working session') : undefined}
        >
          <span className="card-title-role">{roleIcon}</span>
          <span>{task.title}</span>
        </h4>
        <div className="card-tags">
          {roleLabel && (
            <span className="tag tag-role" title={pick(locale, `指定成员：${roleLabel}`, `Assigned teammate: ${roleLabel}`)}>
              {roleLabel}
            </span>
          )}
          <span className={`tag ${priorityColors[task.priority]}`}>{task.priority}</span>
        </div>
      </div>

      {task.description && <p className="card-desc">{task.description}</p>}

      <time className="card-time">
        {new Date(task.created_at).toLocaleString(localeTag(locale))}
      </time>

      {task.status === 'pending' && (
        <div className="card-status status-pending">
          <span className="pulse-dot" />
          {pick(locale, '正在桌上等待接手', 'Waiting on the table')}
        </div>
      )}
      {task.status === 'in_progress' && (
        <div className="card-status status-active">
          <span className="pulse-dot pulse-dot-blue" />
          {activeText}
        </div>
      )}
      {task.status === 'failed' && (
        <div className="card-status status-failed">
          <span className="pulse-dot pulse-dot-red" />
          {pick(locale, '执行失败，点击重试', 'Execution failed, click to retry')}
        </div>
      )}

      <div className="card-actions">
        {task.status === 'failed' && onRetry && (
          <button onClick={onRetry} className="action-btn action-btn-retry">
            {pick(locale, '重试', 'Retry')}
          </button>
        )}
        {(task.status === 'pending' || task.status === 'in_progress') && (
          <button onClick={onCancel} className="action-btn action-btn-cancel">
            {pick(locale, '取消', 'Cancel')}
          </button>
        )}
        {hasSession && (
          <button onClick={onViewSession} className="action-btn action-btn-session">
            {pick(locale, '打开会话', 'Open Session')}
          </button>
        )}
        <button onClick={onDelete} className="action-btn action-btn-delete">
          {pick(locale, '移除', 'Remove')}
        </button>
      </div>
    </div>
  );
}
