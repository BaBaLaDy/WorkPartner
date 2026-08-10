import { useStore, type Task, type Schedule, type SessionData, type ChatSession, type SessionMessage, type Role, type SupervisorStatus, type OfficeState, type Pin } from './store';

const API_BASE = '/api';

// -- HTTP client --

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

export const api = {
  // Tasks
  getTasks: (status?: string) =>
    request<{ tasks: Task[] }>(`/tasks${status ? `?status=${status}` : ''}`),

  createTask: (data: { title: string; description?: string; priority?: string; role?: string | null; auto_run?: boolean }) =>
    request<Task>('/tasks', { method: 'POST', body: JSON.stringify(data) }),

  updateTask: (id: string, data: Record<string, unknown>) =>
    request<Task>(`/tasks/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  deleteTask: (id: string) =>
    request<{ ok: boolean }>(`/tasks/${id}`, { method: 'DELETE' }),

  // Schedules
  getSchedules: () => request<{ schedules: Schedule[] }>('/schedules'),

  createSchedule: (data: Record<string, unknown>) =>
    request<Schedule>('/schedules', { method: 'POST', body: JSON.stringify(data) }),

  pauseSchedule: (id: string) =>
    request<Schedule>(`/schedules/${id}/pause`, { method: 'PATCH' }),

  resumeSchedule: (id: string) =>
    request<Schedule>(`/schedules/${id}/resume`, { method: 'PATCH' }),

  deleteSchedule: (id: string) =>
    request<{ ok: boolean }>(`/schedules/${id}`, { method: 'DELETE' }),

  // Status
  getStatus: () =>
    request<{ running: boolean; pending_tasks: number; active_schedules: number; websocket_connections: number }>('/status'),

  // Executor
  getExecutorStatus: () =>
    request<{ running: boolean; poll_interval: number; active_count: number; active_tasks: string[] }>('/executor/status'),

  wakeupExecutor: () =>
    request<{ ok: boolean; status: Record<string, unknown> }>('/executor/wakeup', { method: 'POST' }),

  setPollInterval: (minutes: number) =>
    request<{ ok: boolean; poll_interval?: number; error?: string }>(`/executor/poll-interval?poll_interval=${minutes}`, { method: 'PUT' }),

  // Supervisor
  getSupervisorStatus: () =>
    request<SupervisorStatus>('/supervisor/status'),

  generateDailyReport: () =>
    request<{ report: string; generated_at: string }>('/supervisor/daily-report', { method: 'POST' }),

  runMemoryMaintenance: () =>
    request<{ ok: boolean; patterns_updated: boolean }>('/supervisor/memory-maintenance', { method: 'POST' }),

  retryTaskFromSupervisor: (taskId: string) =>
    request<{ ok: boolean; task?: Task; retry_count?: number; error?: string }>(`/supervisor/retry/${taskId}`, { method: 'POST' }),

  getSupervisorChatHistory: () =>
    request<{ role: 'user' | 'assistant'; content: string }[]>('/supervisor/chat/history'),

  // Task session
  getTaskSession: (id: string) =>
    request<SessionData>(`/tasks/${id}/session`),

  // Chat sessions
  getSessions: () =>
    request<{ sessions: ChatSession[]; active_thread_id: string | null }>('/sessions'),

  createSession: (name: string) =>
    request<{ thread_id: string; name: string }>('/sessions', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),

  updateSession: (threadId: string, data: { name?: string; action?: string }) =>
    request<{ ok: boolean; name?: string; thread_id?: string }>(`/sessions/${threadId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  getSessionMessages: (threadId: string) =>
    request<{ thread_id: string; messages: SessionMessage[]; title: string }>(
      `/sessions/${threadId}/messages`,
    ),

  // Roles
  listRoles: () =>
    request<{ roles: Role[] }>('/roles'),

  getRole: (name: string) =>
    request<{ role: Role }>(`/roles/${name}`),

  createRole: (data: { name: string; display_name: string; description: string; icon?: string; system_prompt: string; tools?: string[]; model?: string; personality?: string; greeting?: string; signoff?: string; status_text?: string }) =>
    request<Role>('/roles', { method: 'POST', body: JSON.stringify(data) }),

  updateRole: (name: string, data: Record<string, unknown>) =>
    request<Role>(`/roles/${name}`, { method: 'PUT', body: JSON.stringify(data) }),

  deleteRole: (name: string) =>
    request<{ ok: boolean }>(`/roles/${name}`, { method: 'DELETE' }),

  // Channels
  listChannels: () =>
    request<{ channels: { name: string; enabled: boolean; connected: boolean; display_name: string }[] }>('/channels'),

  connectChannel: (name: string) =>
    request<{ status: string; channel: string }>(`/channels/${name}/connect`, { method: 'POST' }),

  disconnectChannel: (name: string) =>
    request<{ status: string; channel: string }>(`/channels/${name}/disconnect`, { method: 'POST' }),

  // Office state
  getOfficeState: () =>
    request<OfficeState>('/office/state'),

  // Pins
  getPins: () =>
    request<{ pins: Pin[]; unread_count: number }>('/pins'),

  markPinRead: (threadId: string) =>
    request<Pin>(`/pins/${threadId}/read`, { method: 'POST' }),

  archivePin: (threadId: string) =>
    request<Pin>(`/pins/${threadId}/archive`, { method: 'POST' }),

  // Skills
  getSkills: () =>
    request<{ skills: { name: string; description: string; version: string; should_auto_load: boolean; path: string }[] }>('/skills'),

  refreshSkills: () =>
    request<{ count: number; added: string[]; removed: string[]; skills: { name: string; description: string; version: string; should_auto_load: boolean }[] }>('/skills/refresh', { method: 'POST' }),

  // MCP servers
  getMcpServers: () =>
    request<{ servers: { name: string; transport: string; connected: boolean; enabled: boolean; tool_count: number; last_connected: string | null; config: { command?: string; args: string[]; url?: string; headers: Record<string, string>; env: Record<string, string>; cwd?: string } }[] }>('/mcp/servers'),

  connectMcpServer: (data: { name: string; command?: string; args?: string[]; url?: string; headers?: Record<string, string>; env?: Record<string, string>; cwd?: string }) =>
    request('/mcp/servers', { method: 'POST', body: JSON.stringify(data) }),

  replaceMcpConfig: (data: { mcpServers: Record<string, any> }) =>
    request<{ ok: boolean; results: Record<string, any> }>('/mcp/config', { method: 'PUT', body: JSON.stringify(data) }),

  updateMcpServer: (name: string, data: { command?: string; args?: string[]; url?: string; headers?: Record<string, string>; env?: Record<string, string>; cwd?: string }) =>
    request(`/mcp/servers/${name}`, { method: 'PATCH', body: JSON.stringify(data) }),

  removeMcpServer: (name: string) =>
    request(`/mcp/servers/${name}`, { method: 'DELETE' }),

  disconnectMcpServer: (name: string) =>
    request(`/mcp/servers/${name}/disconnect`, { method: 'POST' }),

  reloadMcpServer: (name: string) =>
    request(`/mcp/servers/${name}/reload`, { method: 'POST' }),

  toggleMcpServer: (name: string) =>
    request<{ ok: boolean; enabled: boolean }>(`/mcp/servers/${name}/toggle`, { method: 'POST' }),
};

// -- WebSocket client --

let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

/** Events that should appear in the EventFeed (lifecycle only, not text deltas). */
const FEED_EVENTS = new Set([
  'task.created', 'task.started', 'task.done', 'task.failed',
  'task.retrying', 'task.cancelled', 'tool_start', 'tool_end',
  'executor.wakeup', 'supervisor.updated',
  'role.started', 'role.done', 'role.failed',
]);

function processEvent(raw: string) {
  try {
    const parsed = JSON.parse(raw);
    const evtName = parsed.type || parsed.event || '';
    const evtData = parsed.payload || parsed.data || {};
    const timestamp = parsed.timestamp || new Date().toISOString();

    const {
      addEvent,
      addTaskHistory,
      appendTaskText,
      updateTask,
      setTasks,
      tasks,
      startRoleActivity,
      endRoleActivity,
      addDispatchEntry,
      updateDispatchEntry,
      roles,
      setSupervisorStatus,
    } = useStore.getState();

    // Accumulate streaming text per task (don't show in feed)
    if (evtName === 'text_delta' && evtData.text) {
      appendTaskText(evtData.task_id as string, evtData.text);
      return;
    }

    // Add to event feed (only lifecycle events)
    if (FEED_EVENTS.has(evtName)) {
      addEvent({
        event_id: parsed.event_id,
        type: evtName,
        payload: evtData,
        trace_id: parsed.trace_id,
        parent_id: parsed.parent_id ?? null,
        session_id: parsed.session_id ?? evtData.session_id ?? null,
        task_id: parsed.task_id ?? evtData.task_id ?? null,
        agent_id: parsed.agent_id,
        caller: parsed.caller,
        event: evtName,
        data: evtData,
        timestamp,
      });
    }

    if (evtName === 'supervisor.updated') {
      setSupervisorStatus(evtData as unknown as SupervisorStatus);
      // Refresh office state on supervisor updates
      api.getOfficeState().then((s) => {
        useStore.getState().setOfficeState(s);
      }).catch(() => {});
    }

    if (evtName === 'role.started' && evtData.role) {
      startRoleActivity({
        role: evtData.role as string,
        display_name: evtData.display_name as string || evtData.role as string,
        icon: evtData.icon as string || '◈',
        title: evtData.title as string || '处理中',
        status_text: evtData.status_text as string || '正在处理任务',
        thread_id: evtData.thread_id as string | undefined,
        started_at: timestamp,
      });

      // 小管家调度视角：记录派发条目
      const roleInfo = roles.find((r) => r.name === evtData.role);
      addDispatchEntry({
        role: evtData.role as string,
        display_name: (evtData.display_name as string) || roleInfo?.display_name || evtData.role as string,
        icon: (evtData.icon as string) || roleInfo?.icon || '◈',
        title: evtData.title as string || '处理中',
        status: 'dispatched',
        timestamp,
      });
    }

    if ((evtName === 'role.done' || evtName === 'role.failed') && evtData.role) {
      endRoleActivity(evtData.role as string);
      updateDispatchEntry(evtData.role as string, evtName === 'role.done' ? 'done' : 'failed');
      // Refresh office state on role completion/failure
      api.getOfficeState().then((s) => {
        useStore.getState().setOfficeState(s);
      }).catch(() => {});
    }

    // Pin updates
    if (evtName === 'pin.updated' && evtData.thread_id) {
      const { pins, updatePin } = useStore.getState();
      const existing = pins.find(p => p.thread_id === evtData.thread_id);
      if (existing) {
        updatePin({
          ...existing,
          summary: evtData.summary as string || existing.summary,
          task_id: evtData.task_id as string || existing.task_id,
        });
      } else {
        // Refresh pins if we don't have this one yet
        api.getPins().then(r => useStore.getState().setPins(r.pins)).catch(() => {});
      }
    }

    if (evtName === 'pin.created') {
      api.getPins().then(r => useStore.getState().setPins(r.pins)).catch(() => {});
    }

    // Auto-update tasks store on task events
    if (evtName?.startsWith('task.') && evtData.task_id) {
      const idx = tasks.findIndex((t) => t.id === evtData.task_id);
      if (idx >= 0) {
        const updated = { ...tasks[idx], ...evtData };
        updateTask(updated);
      } else if (evtName === 'task.started') {
        api.getTasks().then((r) => setTasks(r.tasks)).catch(() => {});
      }
    }

    // Record completed task output in history
    if (evtName === 'task.done' && evtData.task_id) {
      const textBuf = useStore.getState().taskTextBuffers[evtData.task_id as string] || '';
      addTaskHistory({
        taskId: evtData.task_id as string,
        title: evtData.title as string || 'Unknown task',
        status: 'done',
        output: textBuf || (evtData.result as string) || '',
        tools: [],
        timestamp,
      });
    }
    if (evtName === 'task.failed' && evtData.task_id) {
      addTaskHistory({
        taskId: evtData.task_id as string,
        title: evtData.title as string || 'Unknown task',
        status: 'failed',
        output: evtData.error as string || 'Unknown error',
        tools: [],
        timestamp,
      });
    }

  } catch {
    // ignore parse errors
  }
}

export function connectWs() {
  if (ws) return;

  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  ws = new WebSocket(`${proto}//${host}/ws/events`);

  ws.onopen = () => {
    useStore.getState().setWsStatus('connected');
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  ws.onclose = () => {
    useStore.getState().setWsStatus('disconnected');
    ws = null;
    reconnectTimer = setTimeout(connectWs, 3000);
  };

  ws.onerror = () => {
    ws?.close();
  };

  ws.onmessage = (e) => processEvent(e.data);
}

export function disconnectWs() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  ws?.close();
  ws = null;
}

// -- Chat streaming --

export async function sendChatMessage(
  message: string,
  onText: (text: string) => void,
  onDone: () => void,
  threadId?: string,
  signal?: AbortSignal,
  onEvent?: (event: { type: string; content?: string; data?: Record<string, unknown> }) => void,
) {
  const res = await fetch('/api/supervisor/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, thread_id: threadId }),
    signal,
  });

  if (!res.ok) throw new Error(`Chat API error: ${res.status}`);

  const reader = res.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder();
  let buf = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });

    // Parse SSE lines
    const lines = buf.split('\n');
    buf = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const parsed = JSON.parse(line.slice(6));
          if (parsed.type === 'text') onText(parsed.content);
          if (parsed.type !== 'text' && parsed.type !== 'done') {
            onEvent?.(parsed);
          }
          if (parsed.type === 'done') {
            onDone();
            return;
          }
        } catch {
          // skip malformed
        }
      }
    }
  }
  onDone();
}
