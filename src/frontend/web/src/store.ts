import { create } from 'zustand';
import { inferInitialLocale, type Locale } from './locale';

export type TaskStatus = 'pending' | 'in_progress' | 'done' | 'cancelled' | 'failed';
export type Tab = 'team' | 'workbench' | 'chat' | 'timeline' | 'settings';
export type Theme = 'dark' | 'light';

export interface Task {
  id: string;
  title: string;
  description: string;
  status: TaskStatus;
  priority: 'high' | 'medium' | 'low';
  created_at: string;
  completed_at: string | null;
  parent_schedule_id?: string | null;
  session_thread_id?: string | null;
  output?: string;
  role?: string | null;
}

export interface Role {
  name: string;
  display_name: string;
  description: string;
  icon: string;
  system_prompt?: string;
  tools?: string[];
  model?: string;
  personality?: string;
  greeting?: string;
  signoff?: string;
  status_text?: string;
  tone?: string;
  idle_style?: string;
  busy_style?: string;
  success_style?: string;
  failure_style?: string;
  handoff_style?: string;
}

export interface TeamMember {
  name: string;
  display_name: string;
  description: string;
  icon: string;
  personality: string;
  status_text: string;
  state: 'idle' | 'busy';
  current_task_id: string | null;
  current_task_title: string | null;
}

export interface SupervisorStatus {
  thread_id?: string;
  counts: Record<string, number>;
  team: TeamMember[];
  action_items: { level: string; text: string; task_id?: string | null }[];
  learning_highlights?: { role: string; task_type: string; tools_chain: string; confidence: string }[];
  suggested_next_action?: string;
  quality?: Record<string, { status: string; reason: string }>;
  daily_report: string;
  updated_at: string;
}

export interface RoleActivity {
  role: string;
  display_name: string;
  icon: string;
  title: string;
  status_text: string;
  thread_id?: string;
  started_at: string;
}

export interface Channel {
  name: string;
  enabled: boolean;
  connected: boolean;
  display_name: string;
}

export interface SessionMessage {
  role: 'user' | 'assistant' | 'tool_call' | 'tool_result';
  content?: string;
  name?: string;
  args?: Record<string, unknown>;
  tool_call_id?: string;
}

export interface SessionData {
  thread_id: string | null;
  messages: SessionMessage[];
  title: string;
  status: string;
}

export interface Schedule {
  id: string;
  name: string;
  schedule_type: 'once' | 'recurring';
  cron_expression?: string | null;
  trigger_at?: string | null;
  enabled: boolean;
  task_title?: string;
  task_description?: string;
  last_triggered_at?: string | null;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatSession {
  thread_id: string;
  name: string;
  created_at: string;
  last_active: string;
  active: boolean;
  session_type: string;
  owner: string;
}

export interface DispatchEntry {
  role: string;
  display_name: string;
  icon: string;
  title: string;
  status: 'dispatched' | 'done' | 'failed';
  timestamp: string;
}

export interface McpServer {
  name: string;
  transport: 'stdio' | 'streamable-http' | 'sse';
  connected: boolean;
  enabled: boolean;
  tool_count: number;
  last_connected: string | null;
  config: {
    command?: string;
    args: string[];
    url?: string;
    headers: Record<string, string>;
    env: Record<string, string>;
    cwd?: string;
  };
}

export interface Pin {
  thread_id: string;
  title: string;
  summary: string;
  status: 'done' | 'failed' | 'waiting_confirm';
  created_at: string;
  read: boolean;
  task_id: string;
}

export interface WsEvent {
  event_id?: string;
  type?: string;
  payload?: Record<string, unknown>;
  trace_id?: string;
  parent_id?: string | null;
  session_id?: string | null;
  task_id?: string | null;
  agent_id?: string;
  caller?: string;
  event: string;
  data: Record<string, unknown>;
  timestamp: string;
}

export interface OfficeStateMember {
  name: string;
  status: string;
  task: string | null;
}

export interface OfficeStatePendingItem {
  task_id: string;
  reason: string;
  retry_count: number;
}

export interface OfficeState {
  office_mood: 'idle' | 'busy' | 'attention_needed';
  active_members: OfficeStateMember[];
  recent_handovers: string[];
  pending_attention: OfficeStatePendingItem[];
  suggested_next_action: string | null;
}

interface TaskHistoryEntry {
  taskId: string;
  title: string;
  status: 'started' | 'done' | 'failed';
  output: string;
  tools: string[];
  timestamp: string;
}

interface Store {
  // Theme
  theme: Theme;
  setTheme: (theme: Theme) => void;
  locale: Locale;
  setLocale: (locale: Locale) => void;

  // Navigation
  activeTab: Tab;
  setActiveTab: (tab: Tab) => void;

  // Tasks
  tasks: Task[];
  setTasks: (tasks: Task[]) => void;
  updateTask: (task: Task) => void;

  // Schedules
  schedules: Schedule[];
  setSchedules: (schedules: Schedule[]) => void;

  // Chat
  messages: ChatMessage[];
  addMessage: (msg: ChatMessage) => void;
  setMessages: (msgs: ChatMessage[]) => void;
  isStreaming: boolean;
  setStreaming: (v: boolean) => void;

  // Chat sessions
  chatSessions: ChatSession[];
  setChatSessions: (sessions: ChatSession[]) => void;
  activeThreadId: string | null;
  setActiveThreadId: (id: string | null) => void;

  // Event log
  events: WsEvent[];
  addEvent: (event: WsEvent) => void;
  clearEvents: () => void;

  // Task history
  taskHistory: TaskHistoryEntry[];
  addTaskHistory: (entry: TaskHistoryEntry) => void;

  // Per-task streaming text buffer
  taskTextBuffers: Record<string, string>;
  appendTaskText: (taskId: string, text: string) => void;

  // WebSocket
  wsStatus: 'connected' | 'disconnected';
  setWsStatus: (status: 'connected' | 'disconnected') => void;

  // Session viewer
  selectedTaskId: string | null;
  setSelectedTaskId: (id: string | null) => void;
  sessionData: SessionData | null;
  setSessionData: (data: SessionData | null) => void;
  sessionLoading: boolean;
  setSessionLoading: (loading: boolean) => void;

  // Task form
  taskFormOpen: boolean;
  setTaskFormOpen: (open: boolean) => void;

  // Settings — roles
  roles: Role[];
  setRoles: (roles: Role[]) => void;

  // Team / supervisor
  supervisorStatus: SupervisorStatus | null;
  setSupervisorStatus: (status: SupervisorStatus | null) => void;
  roleActivities: Record<string, RoleActivity>;
  startRoleActivity: (activity: RoleActivity) => void;
  endRoleActivity: (role: string) => void;

  // Role editor
  editorOpen: boolean;
  setEditorOpen: (open: boolean) => void;
  editingRole: Role | null;  // null = new role
  setEditingRole: (role: Role | null) => void;
  editorForm: {
    name: string;
    display_name: string;
    description: string;
    icon: string;
    system_prompt: string;
    tools: string;
    model: string;
    personality: string;
    greeting: string;
    signoff: string;
    status_text: string;
  };
  setEditorField: (field: string, value: string) => void;
  resetEditorForm: () => void;

  // Channels
  channels: Channel[];
  setChannels: (channels: Channel[]) => void;
  updateChannel: (channel: Channel) => void;

  // Executor settings
  pollInterval: number;
  setPollInterval: (interval: number) => void;
  wakeupLoading: boolean;
  setWakeupLoading: (loading: boolean) => void;

  // Dispatcher log (小管家调度视角)
  dispatchLog: DispatchEntry[];
  addDispatchEntry: (entry: DispatchEntry) => void;
  updateDispatchEntry: (role: string, status: 'done' | 'failed') => void;
  clearDispatchLog: () => void;

  // Office state
  officeState: OfficeState | null;
  setOfficeState: (state: OfficeState | null) => void;

  // Pins
  pins: Pin[];
  setPins: (pins: Pin[]) => void;
  updatePin: (pin: Pin) => void;
  unreadPinCount: number;

  // MCP servers
  mcpServers: McpServer[];
  setMcpServers: (servers: McpServer[]) => void;
  updateMcpServer: (server: McpServer) => void;
}

export const useStore = create<Store>((set) => ({
  theme: (typeof window !== 'undefined' && localStorage.getItem('theme') as Theme) || 'dark',
  setTheme: (theme) => {
    localStorage.setItem('theme', theme);
    document.documentElement.setAttribute('data-theme', theme);
    set({ theme });
  },
  locale: inferInitialLocale(),
  setLocale: (locale) => {
    localStorage.setItem('locale', locale);
    document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en';
    set({ locale });
  },

  activeTab: 'team',
  setActiveTab: (tab) => set({ activeTab: tab }),

  tasks: [],
  setTasks: (tasks) => set({ tasks }),
  updateTask: (task) =>
    set((state) => ({
      tasks: state.tasks.map((t) => (t.id === task.id ? task : t)),
    })),

  schedules: [],
  setSchedules: (schedules) => set({ schedules }),

  messages: [],
  addMessage: (msg) => set((state) => ({ messages: [...state.messages, msg] })),
  setMessages: (msgs) => set({ messages: msgs }),
  isStreaming: false,
  setStreaming: (v) => set({ isStreaming: v }),

  chatSessions: [],
  setChatSessions: (sessions) => set({ chatSessions: sessions }),
  activeThreadId: null,
  setActiveThreadId: (id) => set({ activeThreadId: id }),

  events: [],
  addEvent: (event) => set((state) => ({ events: [...state.events, event] })),
  clearEvents: () => set({ events: [] }),

  taskHistory: [],
  addTaskHistory: (entry) =>
    set((state) => ({ taskHistory: [...state.taskHistory, entry] })),

  taskTextBuffers: {},
  appendTaskText: (taskId, text) =>
    set((state) => ({
      taskTextBuffers: {
        ...state.taskTextBuffers,
        [taskId]: (state.taskTextBuffers[taskId] || '') + text,
      },
    })),

  wsStatus: 'disconnected',
  setWsStatus: (status) => set({ wsStatus: status }),

  selectedTaskId: null,
  setSelectedTaskId: (id) => set({ selectedTaskId: id }),
  sessionData: null,
  setSessionData: (data) => set({ sessionData: data }),
  sessionLoading: false,
  setSessionLoading: (loading) => set({ sessionLoading: loading }),

  taskFormOpen: false,
  setTaskFormOpen: (open) => set({ taskFormOpen: open }),

  // Settings — roles
  roles: [],
  setRoles: (roles) => set({ roles }),

  // Team / supervisor
  supervisorStatus: null,
  setSupervisorStatus: (status) => set({ supervisorStatus: status }),
  roleActivities: {},
  startRoleActivity: (activity) =>
    set((state) => ({
      roleActivities: {
        ...state.roleActivities,
        [activity.role]: activity,
      },
    })),
  endRoleActivity: (role) =>
    set((state) => {
      const next = { ...state.roleActivities };
      delete next[role];
      return { roleActivities: next };
    }),

  // Role editor
  editorOpen: false,
  setEditorOpen: (open) => set({ editorOpen: open }),
  editingRole: null,
  setEditingRole: (role) => set({ editingRole: role }),
  editorForm: {
    name: '',
    display_name: '',
    description: '',
    icon: '◈',
    system_prompt: '',
    tools: '',
    model: '',
    personality: '',
    greeting: '',
    signoff: '',
    status_text: '',
  },
  setEditorField: (field, value) =>
    set((state) => ({
      editorForm: { ...state.editorForm, [field]: value },
    })),
  resetEditorForm: () =>
    set({
      editorForm: {
        name: '',
        display_name: '',
        description: '',
        icon: '◈',
        system_prompt: '',
        tools: '',
        model: '',
        personality: '',
        greeting: '',
        signoff: '',
        status_text: '',
      },
    }),

  // Channels
  channels: [],
  setChannels: (channels) => set({ channels }),
  updateChannel: (channel) =>
    set((state) => ({
      channels: state.channels.map((c) => (c.name === channel.name ? channel : c)),
    })),

  // Executor settings
  pollInterval: 30,
  setPollInterval: (interval) => set({ pollInterval: interval }),
  wakeupLoading: false,
  setWakeupLoading: (loading) => set({ wakeupLoading: loading }),

  // Dispatcher log (小管家调度视角)
  dispatchLog: [],
  addDispatchEntry: (entry) =>
    set((state) => ({
      dispatchLog: [...state.dispatchLog, entry],
    })),
  updateDispatchEntry: (role, status) =>
    set((state) => ({
      dispatchLog: state.dispatchLog.map((e) =>
        e.role === role ? { ...e, status } : e,
      ),
    })),
  clearDispatchLog: () => set({ dispatchLog: [] }),

  // Office state
  officeState: null,
  setOfficeState: (state) => set({ officeState: state }),

  // Pins
  pins: [],
  setPins: (pins) => set({ pins, unreadPinCount: pins.filter(p => !p.read).length }),
  updatePin: (pin) =>
    set((state) => ({
      pins: state.pins.map((p) => (p.thread_id === pin.thread_id ? pin : p)),
      unreadPinCount: state.pins
        .map((p) => (p.thread_id === pin.thread_id ? pin : p))
        .filter((p) => !p.read).length,
    })),
  unreadPinCount: 0,

  // MCP servers
  mcpServers: [],
  setMcpServers: (servers) => set({ mcpServers: servers }),
  updateMcpServer: (server) =>
    set((state) => ({
      mcpServers: state.mcpServers.map((s) => (s.name === server.name ? server : s)),
    })),
}));

// -- Derived office state selectors --

export function useOfficeMood(): string {
  return useStore((s) => s.officeState?.office_mood ?? 'idle');
}

export function useActiveMembers(): OfficeStateMember[] {
  return useStore((s) => s.officeState?.active_members.filter((m) => m.status !== 'idle') ?? []);
}

export function usePendingAttention(): OfficeStatePendingItem[] {
  return useStore((s) => s.officeState?.pending_attention ?? []);
}
