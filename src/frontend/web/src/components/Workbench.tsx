import { useEffect, useState } from 'react';
import { pick } from '../locale';
import { useStore, type Task } from '../store';
import { api } from '../api';
import { TaskCard } from './TaskCard';
import { SessionViewer } from './SessionViewer';
import { ScheduleTab } from './ScheduleTab';

export function Workbench() {
	const locale = useStore((s) => s.locale);
	const tasks = useStore((s) => s.tasks);
	const setTasks = useStore((s) => s.setTasks);
	const selectedTaskId = useStore((s) => s.selectedTaskId);
	const setSelectedTaskId = useStore((s) => s.setSelectedTaskId);
	const setSessionData = useStore((s) => s.setSessionData);
	const [activeView, setActiveView] = useState<'tasks' | 'calendar'>('tasks');

	const pending = tasks.filter((task) => task.status === 'pending');
	const inProgress = tasks.filter((task) => task.status === 'in_progress');
	const done = tasks
		.filter((task) => task.status === 'done')
		.sort(
			(a, b) =>
				new Date(b.completed_at ?? b.created_at).getTime() -
				new Date(a.completed_at ?? a.created_at).getTime(),
		);

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
		<div className="workbench-page">
			<header className="workbench-header">
				<div className="workbench-header-left">
					<h2 className="page-title">{pick(locale, '工作台', 'Workbench')}</h2>
					<p className="page-intro">
						{pick(
							locale,
							'所有委托和日程在同一张桌上，一目了然。',
							'All requests and schedules on one surface, clear at a glance.',
						)}
					</p>
				</div>
				<div className="workbench-stats">
					<Stat label={pick(locale, '待接手', 'Queued')} count={pending.length} color="amber" />
					<Stat label={pick(locale, '处理中', 'At desks')} count={inProgress.length} color="blue" />
					<Stat label={pick(locale, '已完成', 'Wrapped')} count={done.length} color="green" />
				</div>
			</header>

			<div className="workbench-tabs">
				<button
					className={`workbench-tab-btn ${activeView === 'tasks' ? 'active' : ''}`}
					onClick={() => setActiveView('tasks')}
				>
					{pick(locale, '委托', 'Requests')}
				</button>
				<button
					className={`workbench-tab-btn ${activeView === 'calendar' ? 'active' : ''}`}
					onClick={() => setActiveView('calendar')}
				>
					{pick(locale, '日程', 'Calendar')}
				</button>
			</div>

			{activeView === 'tasks' ? (
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
				</div>
			) : (
				<ScheduleTab />
			)}

			{selectedTaskId && (
				<SessionViewer
					taskId={selectedTaskId}
					onClose={() => {
						setSelectedTaskId(null);
						setSessionData(null);
					}}
				/>
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
	onCancel,
	onDelete,
	onViewSession,
}: {
	title: string;
	emptyLabel: string;
	tasks: Task[];
	color: string;
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
