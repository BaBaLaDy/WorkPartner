import { pick, type Locale } from './locale';
import type {
  DispatchEntry,
  Role,
  RoleActivity,
  SupervisorStatus,
  WsEvent,
} from './store';

export interface CollaborationCard {
  id: string;
  title: string;
  detail: string;
  tone: 'calm' | 'active' | 'success' | 'warning';
  timestamp: string;
  eventType: string;
}

export interface OfficeSnapshot {
  activeCount: number;
  pendingCount: number;
  doneCount: number;
  officeMood: string;
  suggestedPrompt: string;
  activeMembers: Array<{
    role: string;
    displayName: string;
    icon: string;
    title: string;
    statusText: string;
  }>;
  attentionItems: SupervisorStatus['action_items'];
  learningHighlights: NonNullable<SupervisorStatus['learning_highlights']>;
  latestDispatch: string;
}

function findRole(roleName: string | undefined, roles?: Role[]) {
  if (!roleName || !roles?.length) return undefined;
  return roles.find(
    (role) => role.name === roleName || role.display_name === roleName,
  );
}

function roleLine(
  locale: Locale,
  role: Role | undefined,
  kind: 'handoff' | 'success' | 'failure' | 'busy',
  fallbackZh: string,
  fallbackEn: string,
) {
  const value = (() => {
    if (!role) return '';
    if (kind === 'handoff') return role.handoff_style || role.greeting || '';
    if (kind === 'success') return role.success_style || role.signoff || '';
    if (kind === 'failure') return role.failure_style || '';
    if (kind === 'busy') return role.busy_style || role.status_text || '';
    return '';
  })();
  return value || pick(locale, fallbackZh, fallbackEn);
}

function trim(value: string, max: number) {
  return value.length > max ? `${value.slice(0, max - 1)}...` : value;
}

export function describeOfficeEvent(
  locale: Locale,
  event: WsEvent,
  roles?: Role[],
) {
  const payload = event.payload || event.data || {};
  const roleName = payload.role as string | undefined;
  const role = findRole(roleName, roles);
  const displayName =
    role?.display_name ||
    (payload.display_name as string | undefined) ||
    roleName ||
    pick(locale, '团队成员', 'A teammate');

  switch (event.event) {
    case 'task.created':
      return pick(
        locale,
        `新委托已落到前台：${trim(String(payload.title || payload.task_id || '未命名任务'), 36)}`,
        `A new request landed: ${trim(String(payload.title || payload.task_id || 'Untitled task'), 42)}`,
      );
    case 'task.started':
      return pick(
        locale,
        `团队开始推进：${trim(String(payload.title || payload.task_id || '某项任务'), 36)}`,
        `The team started moving on ${trim(String(payload.title || payload.task_id || 'a task'), 42)}`,
      );
    case 'task.done':
      return pick(
        locale,
        `已完成：${trim(String(payload.title || payload.task_id || '某项任务'), 36)}`,
        `Wrapped up ${trim(String(payload.title || payload.task_id || 'a task'), 42)}`,
      );
    case 'task.failed':
      return pick(
        locale,
        `这里有个卡点：${trim(String(payload.title || payload.task_id || '未知任务'), 36)}`,
        `A snag showed up: ${trim(String(payload.title || payload.task_id || 'unknown work'), 42)}`,
      );
    case 'role.started':
      return `${displayName}：${roleLine(locale, role, 'handoff', '接过了新的简报，正在拆解。', 'picked up a fresh brief and is breaking it down.')}`;
    case 'role.done':
      return `${displayName}：${roleLine(locale, role, 'success', '已经把这一段整理好，交回前台。', 'wrapped their piece and handed it back.')}`;
    case 'role.failed':
      return `${displayName}：${roleLine(locale, role, 'failure', '遇到阻塞，正在等下一步安排。', 'hit a blocker and is waiting for the next move.')}`;
    case 'supervisor.updated':
      return pick(locale, '大管家刚刷新了办公室看板。', 'Supervisor refreshed the office board.');
    case 'executor.wakeup':
      return pick(locale, '办公室被轻轻唤醒了一次。', 'The office got a gentle nudge.');
    default:
      return trim(
        String(event.event || pick(locale, '办公室更新', 'Office update')),
        42,
      );
  }
}

export function buildCollaborationCards(
  locale: Locale,
  events: WsEvent[],
  roles: Role[],
  limit = 6,
): CollaborationCard[] {
  return [...events]
    .filter((event) => event.event !== 'supervisor.updated')
    .slice(-limit)
    .reverse()
    .map((event) => {
      const payload = event.payload || event.data || {};
      const tone: CollaborationCard['tone'] =
        event.event === 'task.failed' || event.event === 'role.failed'
          ? 'warning'
          : event.event === 'task.done' || event.event === 'role.done'
            ? 'success'
            : event.event === 'role.started' || event.event === 'task.started'
              ? 'active'
              : 'calm';
      return {
        id: event.event_id || `${event.event}-${event.timestamp}`,
        title: describeOfficeEvent(locale, event, roles),
        detail: trim(String(payload.title || payload.error || payload.status_text || ''), 84),
        tone,
        timestamp: event.timestamp,
        eventType: event.event,
      };
    });
}

export function buildOfficeSnapshot(
  locale: Locale,
  supervisorStatus: SupervisorStatus | null,
  roleActivities: Record<string, RoleActivity>,
  dispatchLog: DispatchEntry[],
) : OfficeSnapshot {
  const counts = supervisorStatus?.counts ?? {};
  const activeMembers = Object.values(roleActivities).map((activity) => ({
    role: activity.role,
    displayName: activity.display_name,
    icon: activity.icon,
    title: activity.title,
    statusText: activity.status_text,
  }));
  const latestDispatchEntry = [...dispatchLog].reverse().find((entry) => entry.status === 'dispatched');
  const latestDispatch = latestDispatchEntry
    ? pick(
        locale,
        `${latestDispatchEntry.display_name} 正在处理「${trim(latestDispatchEntry.title, 20)}」`,
        `${latestDispatchEntry.display_name} is on "${trim(latestDispatchEntry.title, 24)}"`,
      )
    : pick(locale, '办公室暂时很安静。', 'The office is quiet for now.');

  const attentionItems = supervisorStatus?.action_items ?? [];
  const learningHighlights = supervisorStatus?.learning_highlights ?? [];
  let officeMood = pick(locale, '节奏平稳', 'Steady rhythm');
  let suggestedPrompt = supervisorStatus?.suggested_next_action || pick(locale, '可以问问今天进展，或者直接交办一件事。', 'Ask for status, or hand over a fresh task.');

  if ((counts.in_progress ?? 0) > 0 || activeMembers.length > 0) {
    officeMood = pick(locale, '团队正在推进工作', 'The team is in motion');
    suggestedPrompt = supervisorStatus?.suggested_next_action || pick(locale, '可以追问当前谁在做什么。', 'You can ask who is handling what right now.');
  }
  if (attentionItems.some((item) => item.level === 'error')) {
    officeMood = pick(locale, '有卡点需要注意', 'A blocker needs attention');
    suggestedPrompt = supervisorStatus?.suggested_next_action || pick(locale, '可以直接问失败原因，或让大管家接手处理。', 'Ask what failed, or have the supervisor take over.');
  }
  if ((counts.pending ?? 0) > 0 && activeMembers.length === 0) {
    officeMood = pick(locale, '前台有待办在排队', 'Requests are queued at the front desk');
    suggestedPrompt = supervisorStatus?.suggested_next_action || pick(locale, '可以让团队立刻开始处理待办。', 'Tell the team to start on the queue.');
  }

  return {
    activeCount: Math.max(counts.in_progress ?? 0, activeMembers.length),
    pendingCount: counts.pending ?? 0,
    doneCount: counts.done ?? 0,
    officeMood,
    suggestedPrompt,
    activeMembers,
    attentionItems,
    learningHighlights,
    latestDispatch,
  };
}
