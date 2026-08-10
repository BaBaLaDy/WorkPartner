import { Component, useEffect, useRef, useState, type ReactNode } from 'react';
import { pick } from '../locale';
import { useStore, type Task } from '../store';
import { api } from '../api';
import { TaskCard } from './TaskCard';
import { SessionViewer } from './SessionViewer';

class ErrorBoundary extends Component<
  { children: ReactNode; locale: 'zh' | 'en' },
  { hasError: boolean; error: string }
> {
  constructor(props: { children: ReactNode; locale: 'zh' | 'en' }) {
    super(props);
    this.state = { hasError: false, error: '' };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error: error.message };
  }

  render() {
    const { locale } = this.props;
    if (this.state.hasError) {
      return (
        <div className="error-boundary">
          <p className="error-boundary-msg">{pick(locale, '出现了一点问题：', 'Something went wrong:')}</p>
          <pre className="error-boundary-detail">
            {this.state.error}
          </pre>
          <button
            className="error-boundary-retry"
            onClick={() => this.setState({ hasError: false, error: '' })}
          >
            {pick(locale, '重试', 'Try again')}
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

function AddTaskForm() {
  const locale = useStore((s) => s.locale);
  const [expanded, setExpanded] = useState(false);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState<'high' | 'medium' | 'low'>('medium');
  const [role, setRole] = useState('');
  const [loading, setLoading] = useState(false);
  const [roles, setRoles] = useState<{ name: string; display_name: string; icon: string }[]>([]);
  const descRef = useRef<HTMLTextAreaElement>(null);
  const setTasks = useStore((s) => s.setTasks);

  useEffect(() => {
    api.listRoles().then((r) => setRoles(r.roles)).catch(() => {});
  }, []);

  const handleAdd = async () => {
    if (!title.trim() || loading) return;
    setLoading(true);
    try {
      await api.createTask({
        title: title.trim(),
        description: description.trim(),
        priority,
        role: role || null,
      });
      setTitle('');
      setDescription('');
      setExpanded(false);
      api.getTasks().then((r) => setTasks(r.tasks)).catch(() => {});
    } catch (error) {
      console.error('Failed to create task:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="add-task-form">
      <div className="add-task-main">
        <input
          type="text"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          onFocus={() => setExpanded(true)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') handleAdd();
          }}
          placeholder={pick(locale, '写下一份委托书，派给办公室...', 'Write a brief and dispatch to the office...')}
          className="add-task-input"
        />
        <select
          value={priority}
          onChange={(event) => setPriority(event.target.value as 'high' | 'medium' | 'low')}
          className="add-task-select"
        >
          <option value="high">{pick(locale, '高', 'High')}</option>
          <option value="medium">{pick(locale, '中', 'Medium')}</option>
          <option value="low">{pick(locale, '低', 'Low')}</option>
        </select>
        <select
          value={role}
          onChange={(event) => setRole(event.target.value)}
          className="add-task-select"
          title={pick(locale, '选择处理这条委托的成员', 'Choose the teammate for this request')}
        >
          <option value="">{pick(locale, '任意成员', 'Any teammate')}</option>
          {roles.map((item) => (
            <option key={item.name} value={item.name}>
              {item.icon} {item.display_name}
            </option>
          ))}
        </select>
        <button onClick={handleAdd} disabled={loading || !title.trim()} className="add-task-btn">
          {loading ? pick(locale, '正在派件中...', 'Dispatching...') : pick(locale, '派给办公室', 'Assign to office')}
        </button>
      </div>

      <div className={`add-task-expand ${expanded ? 'open' : ''}`}>
        <textarea
          ref={descRef}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder={pick(locale, '补充背景、交接信息，或你希望得到的结果。', 'Add the context, handoff notes, or desired outcome.')}
          rows={3}
          className="add-task-textarea"
        />
      </div>
    </div>
  );
}

export function TaskList() {
  const locale = useStore((s) => s.locale);
  const tasks = useStore((s) => s.tasks);
  const setTasks = useStore((s) => s.setTasks);
  const selectedTaskId = useStore((s) => s.selectedTaskId);
  const setSelectedTaskId = useStore((s) => s.setSelectedTaskId);
  const setSessionData = useStore((s) => s.setSessionData);

  const pending = tasks.filter((task) => task.status === 'pending');
  const inProgress = tasks.filter((task) => task.status === 'in_progress');
  const done = tasks
    .filter((task) => task.status === 'done')
    .sort(
      (a, b) =>
        new Date(b.completed_at ?? b.created_at).getTime() -
        new Date(a.completed_at ?? a.created_at).getTime(),
    );
  const failed = tasks.filter((task) => task.status === 'failed');

  const refresh = () => api.getTasks().then((r) => setTasks(r.tasks)).catch(() => {});

  useEffect(() => {
    const interval = setInterval(refresh, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleCancel = async (task: Task) => {
    try {
      await api.updateTask(task.id, { status: 'cancelled' });
      refresh();
    } catch (error) {
      console.error('Failed to pause task:', error);
    }
  };

  const handleDelete = async (task: Task) => {
    try {
      await api.deleteTask(task.id);
      refresh();
    } catch (error) {
      console.error('Failed to delete task:', error);
    }
  };

  const handleViewSession = (task: Task) => {
    setSelectedTaskId(task.id);
  };

  const handleRetry = async (task: Task) => {
    try {
      await api.retryTaskFromSupervisor(task.id);
      refresh();
    } catch (error) {
      console.error('Failed to retry task:', error);
    }
  };

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setSelectedTaskId(null);
        setSessionData(null);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  return (
    <div className="task-page">
      <header className="task-header">
        <div className="task-header-left">
          <h2 className="page-title">{pick(locale, '派件桌', 'Dispatch Desk')}</h2>
          <p className="page-intro">
            {pick(
              locale,
              '这里是委托进入、处理中和已完成结果的共同桌面。',
              'A shared surface for incoming work, active follow-through, and wrapped results.',
            )}
          </p>
        </div>
        <div className="task-stats">
          <Stat label={pick(locale, '待接手', 'Queued')} count={pending.length} color="amber" />
          <Stat label={pick(locale, '处理中', 'At desks')} count={inProgress.length} color="blue" />
          <Stat label={pick(locale, '已完成', 'Wrapped')} count={done.length} color="green" />
          <Stat label={pick(locale, '失败', 'Failed')} count={failed.length} color="rust" />
        </div>
      </header>

      <AddTaskForm />

      <div className="kanban">
        <KanbanColumn
          title={pick(locale, '收件盘', 'Inbox')}
          emptyLabel={pick(locale, '这里暂时没有新的委托。', 'No requests here yet.')}
          tasks={pending}
          color="amber"
          onCancel={handleCancel}
          onDelete={handleDelete}
          onViewSession={handleViewSession}
        />
        <KanbanColumn
          title={pick(locale, '工位上', 'On Desks')}
          emptyLabel={pick(locale, '当前没有在推进的委托。', 'No active requests here.')}
          tasks={inProgress}
          color="blue"
          onCancel={handleCancel}
          onDelete={handleDelete}
          onViewSession={handleViewSession}
        />
        <KanbanColumn
          title={pick(locale, '完成夹', 'Finished Folio')}
          emptyLabel={pick(locale, '还没有完成的结果。', 'No wrapped results here yet.')}
          tasks={done}
          color="green"
          onCancel={handleCancel}
          onDelete={handleDelete}
          onViewSession={handleViewSession}
        />
        <KanbanColumn
          title={pick(locale, '待重试', 'Retry Queue')}
          emptyLabel={pick(locale, '没有失败的任务。', 'No failed tasks here.')}
          tasks={failed}
          color="rust"
          onRetry={handleRetry}
          onCancel={handleCancel}
          onDelete={handleDelete}
          onViewSession={handleViewSession}
        />
      </div>

      {selectedTaskId && (
        <ErrorBoundary locale={locale}>
          <SessionViewer
            taskId={selectedTaskId}
            onClose={() => {
              setSelectedTaskId(null);
              setSessionData(null);
            }}
          />
        </ErrorBoundary>
      )}
    </div>
  );
}

function Stat({ label, count, color }: { label: string; count: number; color: string }) {
  return (
    <div className={`stat stat-${color}`}>
      <span className="stat-count">{count}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}

function KanbanColumn({
  title,
  emptyLabel,
  tasks,
  color,
  onRetry,
  onCancel,
  onDelete,
  onViewSession,
}: {
  title: string;
  emptyLabel: string;
  tasks: Task[];
  color: string;
  onRetry?: (task: Task) => void;
  onCancel: (task: Task) => void;
  onDelete: (task: Task) => void;
  onViewSession: (task: Task) => void;
}) {
  return (
    <div className={`kanban-col kanban-col-${color}`}>
      <div className="kanban-col-header">
        <h3>{title}</h3>
        <span className="kanban-count">{tasks.length}</span>
      </div>
      <div className="kanban-col-body">
        {tasks.map((task) => (
          <TaskCard
            key={task.id}
            task={task}
            onRetry={onRetry ? () => onRetry(task) : undefined}
            onCancel={() => onCancel(task)}
            onDelete={() => onDelete(task)}
            onViewSession={() => onViewSession(task)}
          />
        ))}
        {tasks.length === 0 && <p className="kanban-empty">{emptyLabel}</p>}
      </div>
    </div>
  );
}
