import { useEffect, useMemo } from 'react';
import {
  useStore,
  type Role,
  type RoleActivity,
  type SupervisorStatus,
  type Tab,
  type TeamMember,
} from './store';
import { api, connectWs, disconnectWs } from './api';
import { localeTag, pick } from './locale';
import { Workbench } from './components/Workbench';
import { ChatTab } from './components/ChatTab';
import { TimelineTab } from './components/TimelineTab';
import { SettingsTab } from './components/SettingsTab';
import { TeamTab } from './components/TeamTab';
import './OfficeTheme.css';

const MAIN_TABS: { id: Tab; label: { zh: string; en: string }; icon: string }[] = [
  { id: 'team', label: { zh: '工作室', en: 'Studio' }, icon: 'ST' },
  { id: 'workbench', label: { zh: '工作台', en: 'Workbench' }, icon: 'WB' },
  { id: 'chat', label: { zh: '会客厅', en: 'Lounge' }, icon: 'LG' },
  { id: 'timeline', label: { zh: '纪事簿', en: 'Ledger' }, icon: 'LD' },
];

function buildTeam(
  roles: Role[],
  supervisorStatus: SupervisorStatus | null,
  roleActivities: Record<string, RoleActivity>,
): TeamMember[] {
  const fallback = roles.map<TeamMember>((role) => ({
    name: role.name,
    display_name: role.display_name,
    description: role.description,
    icon: role.icon,
    personality: role.personality || '',
    status_text: role.status_text || 'Ready for the next request',
    state: 'idle',
    current_task_id: null,
    current_task_title: null,
  }));

  const baseTeam = supervisorStatus?.team?.length ? supervisorStatus.team : fallback;

  return baseTeam.map((member) => {
    const activity = roleActivities[member.name];
    if (!activity) return member;
    return {
      ...member,
      state: 'busy',
      icon: activity.icon || member.icon,
      status_text: activity.status_text,
      current_task_id: activity.thread_id || member.current_task_id,
      current_task_title: activity.title,
    };
  });
}

function MetricCard({ value, label }: { value: number; label: string }) {
  return (
    <div className="team-metric">
      <span className="team-metric-value">{value}</span>
      <span className="team-metric-label">{label}</span>
    </div>
  );
}

function PortraitSVG({ label }: { label: string }) {
  const jacket = '#c4956a';
  const skin = '#fde8d0';
  const hair = '#5a3e28';
  return (
    <svg viewBox="0 0 180 120" width="60" height="54" role="img" aria-label={label}>
      <rect x="42" y="40" width="96" height="56" rx="16" fill={jacket} opacity="0.12" />
      <path d="M62 110 C64 92 76 82 90 82 C104 82 116 92 118 110" fill={jacket} />
      <ellipse cx="90" cy="46" rx="26" ry="28" fill={skin} />
      <path d="M62 44 C62 22 78 12 90 12 C102 12 118 22 118 44 L118 54 C112 42 102 34 90 34 C78 34 68 42 62 54 Z" fill={hair} />
      <path d="M81 52 Q84 48 87 52" stroke="#3d2b1f" strokeWidth="2" strokeLinecap="round" fill="none" />
      <path d="M93 52 Q96 48 99 52" stroke="#3d2b1f" strokeWidth="2" strokeLinecap="round" fill="none" />
      <path d="M84 62 Q90 67 96 62" stroke="#c47a6a" strokeWidth="2" strokeLinecap="round" fill="none" />
      <ellipse cx="78" cy="58" rx="5" ry="3" fill="#f7a8a8" opacity="0.4" />
      <ellipse cx="102" cy="58" rx="5" ry="3" fill="#f7a8a8" opacity="0.4" />
    </svg>
  );
}

function getDayPart(locale: ReturnType<typeof useStore.getState>['locale'], date = new Date()) {
  const hour = date.getHours();
  if (hour < 11) return pick(locale, '上午班', 'Morning shift');
  if (hour < 17) return pick(locale, '白天班', 'Day shift');
  if (hour < 21) return pick(locale, '傍晚班', 'Evening shift');
  return pick(locale, '夜间值守', 'Late desk hour');
}

function Sidebar() {
  const activeTab = useStore((s) => s.activeTab);
  const setActiveTab = useStore((s) => s.setActiveTab);
  const wsStatus = useStore((s) => s.wsStatus);
  const theme = useStore((s) => s.theme);
  const setTheme = useStore((s) => s.setTheme);
  const locale = useStore((s) => s.locale);
  const setLocale = useStore((s) => s.setLocale);
  const supervisorStatus = useStore((s) => s.supervisorStatus);
  const roleActivities = useStore((s) => s.roleActivities);
  const roles = useStore((s) => s.roles);

  const team = useMemo(
    () => buildTeam(roles, supervisorStatus, roleActivities),
    [roleActivities, roles, supervisorStatus],
  );

  const counts = supervisorStatus?.counts ?? {};
  const activeCount = Math.max(counts.in_progress ?? 0, Object.keys(roleActivities).length);
  const pendingCount = counts.pending ?? 0;
  const doneCount = counts.done ?? 0;
  const roster = team.filter((m) => m.name !== 'task_agent').slice(0, 4);
  const todayLabel = new Intl.DateTimeFormat(localeTag(locale), {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  }).format(new Date());

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <span className="sidebar-kicker">{getDayPart(locale)}</span>
        <h1>WorkPartner House</h1>
        <span className="sidebar-subtitle">{todayLabel}</span>
      </div>

      <section className="sidebar-supervisor supervisor-panel">
        <div className="sidebar-supervisor-portrait">
          <PortraitSVG label={pick(locale, '大管家', 'Supervisor')} />
          <div>
            <h3>{pick(locale, '办公室实况', 'Office status')}</h3>
            <p>{pick(locale, '大管家 🏠', 'Supervisor 🏠')}</p>
          </div>
        </div>
        <div className="supervisor-metrics">
          <MetricCard value={pendingCount} label={pick(locale, '待接手', 'Queued')} />
          <MetricCard value={activeCount} label={pick(locale, '进行中', 'Live')} />
          <MetricCard value={doneCount} label={pick(locale, '已完成', 'Wrapped')} />
        </div>
      </section>

      <div className="sidebar-roster" aria-label="Team status">
        <div className="sidebar-section-title">{pick(locale, '在场成员', 'On the floor')}</div>
        {roster.map((member) => (
          <button
            key={member.name}
            className={`roster-card roster-card-${member.state}`}
            onClick={() => setActiveTab('team')}
            title={`${member.display_name}: ${member.current_task_title || member.status_text || pick(locale, '待命中', 'Ready')}`}
          >
            <div className="team-avatar">
              <span>{member.state === 'busy' ? '🔥' : '😌'}</span>
            </div>
            <div className="roster-copy">
              <span className="roster-name">{member.display_name}</span>
              <span className="roster-status">
                {member.state === 'busy'
                  ? (member.current_task_title || pick(locale, '处理中', 'Working'))
                  : (member.status_text || pick(locale, '待命中', 'Ready'))}
              </span>
            </div>
          </button>
        ))}
      </div>

      <nav className="sidebar-nav sidebar-grid">
        {MAIN_TABS.map((tab) => {
          const isTeamTab = tab.id === 'team';
          const unreadCount = isTeamTab ? useStore.getState().unreadPinCount : 0;
          return (
            <button
              key={tab.id}
              className={`sidebar-btn ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              <span className="sidebar-label">{pick(locale, tab.label.zh, tab.label.en)}</span>
              {isTeamTab && unreadCount > 0 && (
                <span className="sidebar-badge">{unreadCount}</span>
              )}
            </button>
          );
        })}
      </nav>

      <div className="sidebar-footer">
        <div className={`status-dot ${wsStatus === 'connected' ? 'connected' : 'disconnected'}`} />
        <span className="status-text">
          {wsStatus === 'connected'
            ? pick(locale, '实时连接中', 'Live connection')
            : pick(locale, '未连接', 'Offline')}
        </span>
        <div className="sidebar-controls">
          <button
            className="locale-toggle"
            onClick={() => setLocale(locale === 'zh' ? 'en' : 'zh')}
            title={pick(locale, '切换语言', 'Switch language')}
          >
            {locale === 'zh' ? 'EN' : '中'}
          </button>
          <button
            className="theme-toggle"
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            title={pick(
              locale,
              `切换到${theme === 'dark' ? '日间' : '夜间'}模式`,
              `Switch to ${theme === 'dark' ? 'day' : 'night'} mode`,
            )}
          >
            {theme === 'dark' ? '☀' : '🌙'}
          </button>
          <button
            className={`settings-toggle ${activeTab === 'settings' ? 'active' : ''}`}
            onClick={() => setActiveTab('settings')}
            title={pick(locale, '设置', 'Settings')}
          >
            ⚙
          </button>
        </div>
      </div>
    </aside>
  );
}

export default function App() {
  const activeTab = useStore((s) => s.activeTab);
  const locale = useStore((s) => s.locale);
  const setTasks = useStore((s) => s.setTasks);
  const setSchedules = useStore((s) => s.setSchedules);
  const setRoles = useStore((s) => s.setRoles);
  const setSupervisorStatus = useStore((s) => s.setSupervisorStatus);

  useEffect(() => {
    api.getTasks().then((r) => setTasks(r.tasks)).catch(() => {});
    api.getSchedules().then((r) => setSchedules(r.schedules)).catch(() => {});
    api.listRoles().then((r) => setRoles(r.roles)).catch(() => {});
    api.getSupervisorStatus().then(setSupervisorStatus).catch(() => {});
  }, [setRoles, setSchedules, setSupervisorStatus, setTasks]);

  useEffect(() => {
    connectWs();
    return () => disconnectWs();
  }, []);

  const activeTabLabel = (() => {
    const match = MAIN_TABS.find((tab) => tab.id === activeTab);
    if (!match) return pick(locale, '工作室', 'Studio');
    return pick(locale, match.label.zh, match.label.en);
  })();

  return (
    <div className="app">
      <div className="app-backdrop" aria-hidden="true" />
      <Sidebar />
      <main className="main-content">
        <div className="office-marquee">
          <span>{pick(locale, '托管协作', 'Managed collaboration')}</span>
          <span>{getDayPart(locale)}</span>
          <span>{activeTabLabel}</span>
        </div>
        <div className="content-scroll">
          {activeTab === 'team' && <TeamTab />}
          {activeTab === 'workbench' && <Workbench />}
          {activeTab === 'chat' && <ChatTab />}
          {activeTab === 'timeline' && <TimelineTab />}
          {activeTab === 'settings' && <SettingsTab />}
        </div>
      </main>
    </div>
  );
}
