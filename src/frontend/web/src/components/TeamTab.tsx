import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api';
import { localeTag, pick } from '../locale';
import { useStore, type Role, type TeamMember, type WsEvent, type SupervisorStatus, type Pin } from '../store';
import { OfficeScene } from './OfficeScene';
import { PinBoard } from './PinBoard';
import { PinChatOverlay } from './PinChatOverlay';

/* ─────────────────────────────────────────────────────────
   小管家前台接待台 (Reception Desk) — 名片+委托书一体
   ───────────────────────────────────────────────────────── */

function ReceptionDesk({
  onWakeTeam,
  wakeBusy,
  onMaintenance,
  maintenanceBusy,
  showAnimation,
  onToggleView,
  unreadCount,
}: {
  onWakeTeam: () => void;
  wakeBusy: boolean;
  onMaintenance: () => void;
  maintenanceBusy: boolean;
  showAnimation: boolean;
  onToggleView: () => void;
  unreadCount: number;
}) {
  const locale = useStore((s) => s.locale);
  const roles = useStore((s) => s.roles);
  const tasks = useStore((s) => s.tasks);
  const taskAgentRole = roles.find((r) => r.name === 'task_agent');
  const hasActiveTasks = tasks.some((t) => t.status === 'in_progress');
  const idleMood = useIdleMoods('task_agent');

  return (
    <section className="reception-desk">
      {/* 上部：名片在左，表单在右 */}
      <div className="reception-top">
        <div className="reception-card">
          <div className="reception-portrait">
            <ReceptionistSVG state={hasActiveTasks ? 'busy' : 'idle'} />
          </div>
          <div className="reception-info">
            <div className="reception-title">
              <h3>{pick(locale, '小管家', 'Dispatcher')}</h3>
              <span className={`reception-state reception-state-${hasActiveTasks ? 'busy' : 'idle'}`}>
                {hasActiveTasks ? pick(locale, '调度中', 'Coordinating') : pick(locale, '待命中', 'Ready')}
              </span>
            </div>
            <div className={`reception-bubble reception-bubble-${hasActiveTasks ? 'busy' : 'idle'}`}>
              <span>{hasActiveTasks ? pick(locale, '正在协调和分配任务...', 'Coordinating and dispatching tasks...') : pick(locale, idleMood.zh, idleMood.en)}</span>
            </div>
            <p className="reception-desc">
              {taskAgentRole?.description || pick(locale, '任务总指挥，负责接收委托、拆解规划、调度角色、协调跟进', 'Task commander — receives briefs, plans, dispatches roles, and delivers results.')}
            </p>
            <div className="reception-actions">
              <button className="reception-action-btn" onClick={onWakeTeam} disabled={wakeBusy}>
                {wakeBusy ? pick(locale, '唤醒中...', 'Waking...') : pick(locale, '唤醒办公室', 'Wake the room')}
              </button>
              <button className="reception-action-btn" onClick={onMaintenance} disabled={maintenanceBusy}>
                {maintenanceBusy ? pick(locale, '整理中...', 'Tidying...') : pick(locale, '刷新记忆', 'Refresh memory')}
              </button>
              <button className="reception-action-btn" onClick={onToggleView}>
                {showAnimation
                  ? pick(locale, `切换便签墙${unreadCount > 0 ? ` (${unreadCount})` : ''}`, 'Switch to Pins')
                  : pick(locale, '切换动画', 'Switch to Animation')}
              </button>
            </div>
          </div>
        </div>
        <StudioTaskForm />
      </div>

    </section>
  );
}

function ReceptionistSVG({ state }: { state: 'idle' | 'busy' }) {
  const skin = '#fde8d0';
  const hairColor = '#e0e0e0';
  const jacket = '#1a1a2e';
  const shirt = '#fff5eb';
  const desk = '#a0714f';

  const eyeLeft = state === 'idle'
    ? <path d="M77 62 Q81 58 85 62" stroke="#3d2b1f" strokeWidth="2.5" strokeLinecap="round" fill="none" />
    : <><ellipse cx="81" cy="61" rx="5" ry="6" fill="white" /><ellipse cx="81" cy="61" rx="3.5" ry="4.5" fill="#3d2b1f" /><circle cx="83" cy="59" r="1.5" fill="white" /></>;
  const eyeRight = state === 'idle'
    ? <path d="M95 62 Q99 58 103 62" stroke="#3d2b1f" strokeWidth="2.5" strokeLinecap="round" fill="none" />
    : <><ellipse cx="99" cy="61" rx="5" ry="6" fill="white" /><ellipse cx="99" cy="61" rx="3.5" ry="4.5" fill="#3d2b1f" /><circle cx="101" cy="59" r="1.5" fill="white" /></>;

  const mouth = state === 'idle'
    ? 'M83 73 Q90 79 97 73'
    : 'M84 74 Q90 77 96 74';

  return (
    <svg viewBox="0 0 180 160" className="portrait-svg receptionist-svg" role="img" aria-label="小管家">
      {/* 椅子靠背 */}
      <rect x="52" y="60" width="76" height="70" rx="20" fill={jacket} opacity="0.12" />

      {/* Q版身体 — 背带裤 */}
      <path d="M62 136 C64 114 76 104 90 104 C104 104 116 114 118 136" fill="#2d2d44" />
      {/* 背带 — 左右两条 */}
      <rect x="74" y="104" width="5" height="32" rx="2" fill="#1a1a2e" />
      <rect x="101" y="104" width="5" height="32" rx="2" fill="#1a1a2e" />
      {/* 背带扣 */}
      <rect x="73" y="112" width="7" height="5" rx="1" fill="#d4a843" />
      <rect x="100" y="112" width="7" height="5" rx="1" fill="#d4a843" />
      {/* 内搭白T */}
      <path d="M76 110 C80 103 85 100 90 100 C95 100 100 103 104 110 L100 136 L80 136 Z" fill={shirt} />
      {/* 背带裤口袋 */}
      <rect x="80" y="122" width="20" height="10" rx="2" fill="#2d2d44" stroke="#3d3d5c" strokeWidth="0.5" />

      {/* 手 */}
      {state === 'busy'
        ? <>
            <circle cx="56" cy="124" r="6" fill={skin} />
            <circle cx="124" cy="124" r="6" fill={skin} />
            <line x1="124" y1="124" x2="142" y2="84" stroke={skin} strokeWidth="4" strokeLinecap="round" opacity="0.8" />
          </>
        : <>
            <circle cx="62" cy="128" r="6" fill={skin} />
            <circle cx="118" cy="128" r="6" fill={skin} />
          </>
      }

      {/* 办公桌 — 前景 */}
      <ellipse cx="90" cy="58" rx="30" ry="32" fill={skin} />

      {/* 银白色中分头发 */}
      {/* 头顶整体发量 */}
      <path d="M54 58 C54 24 72 14 90 14 C108 14 126 24 126 58 C122 38 106 30 90 30 C74 30 58 38 54 58 Z" fill={hairColor} />
      {/* 中分线 — 左边刘海 */}
      <path d="M60 40 C62 30 74 22 88 24 C80 30 72 38 64 56 C60 52 58 46 60 40 Z" fill={hairColor} />
      {/* 中分线 — 右边刘海 */}
      <path d="M120 40 C118 30 106 22 92 24 C100 30 108 38 116 56 C120 52 122 46 120 40 Z" fill={hairColor} />
      {/* 左侧鬓角 */}
      <path d="M54 56 C52 64 52 74 54 82 C56 78 58 68 58 58 Z" fill={hairColor} />
      {/* 右侧鬓角 */}
      <path d="M126 56 C128 64 128 74 126 82 C124 78 122 68 122 58 Z" fill={hairColor} />
      {/* 头发高光 */}
      <path d="M70 28 Q80 22 90 24" stroke="#ffffff" strokeWidth="1.5" strokeLinecap="round" fill="none" opacity="0.5" />
      <path d="M96 24 Q106 22 114 28" stroke="#ffffff" strokeWidth="1.5" strokeLinecap="round" fill="none" opacity="0.5" />

      {/* 眉毛 */}
      {state === 'busy'
        ? <>
            <line x1="76" y1="52" x2="86" y2="54" stroke="#4a4a4a" strokeWidth="2" strokeLinecap="round" />
            <line x1="94" y1="54" x2="104" y2="52" stroke="#4a4a4a" strokeWidth="2" strokeLinecap="round" />
          </>
        : <>
            <path d="M76 53 Q81 50 86 53" stroke="#4a4a4a" strokeWidth="1.8" strokeLinecap="round" fill="none" />
            <path d="M94 53 Q99 50 104 53" stroke="#4a4a4a" strokeWidth="1.8" strokeLinecap="round" fill="none" />
          </>
      }

      {/* 眼睛 */}
      {eyeLeft}
      {eyeRight}

      {/* 腮红 */}
      <ellipse cx="73" cy="70" rx="6" ry="3.5" fill="#f7a8a8" opacity={state === 'idle' ? 0.5 : 0.25} />
      <ellipse cx="107" cy="70" rx="6" ry="3.5" fill="#f7a8a8" opacity={state === 'idle' ? 0.5 : 0.25} />

      {/* 嘴巴 */}
      <path d={mouth} stroke={state === 'idle' ? '#c47a6a' : '#d48a7a'} strokeWidth="2.5" strokeLinecap="round" fill="none" />

      {/* 办公桌 — 前景 */}
      <rect x="8" y="122" width="164" height="20" rx="6" fill={desk} />
      <rect x="8" y="122" width="164" height="3" rx="1.5" fill="white" opacity="0.08" />

      {/* 桌上篮球 */}
      <circle cx="40" cy="116" r="8" fill="#e85d3a" />
      <path d="M32 116 Q40 110 48 116" stroke="#333" strokeWidth="1" fill="none" />
      <path d="M40 108 Q44 116 40 124" stroke="#333" strokeWidth="1" fill="none" />
      <line x1="32" y1="116" x2="48" y2="116" stroke="#333" strokeWidth="0.8" />

      {/* 桌上茶杯 */}
      <circle cx="148" cy="118" r="6" fill="#f1ede4" />
      <rect x="144" y="121" width="8" height="3" rx="1" fill={jacket} />
    </svg>
  );
}

function memberStatus(locale: ReturnType<typeof useStore.getState>['locale'], member: TeamMember) {
  if (member.current_task_title) return member.current_task_title;
  return member.status_text || pick(locale, '随时待命', 'Ready for the next request');
}

function describeEvent(locale: ReturnType<typeof useStore.getState>['locale'], event: WsEvent, roles?: Role[]) {
  const payload = event.payload || event.data || {};
  const role = payload.role as string | undefined;
  const roleInfo = role ? roles?.find((r) => r.name === role) : undefined;
  const displayName = roleInfo?.display_name || role || null;

  switch (event.event) {
    case 'task.created':
      return pick(locale, `📨 有新的委托到桌：${trim(String(payload.title || payload.task_id || '未命名任务'), 36)}`, `📨 A new request arrived: ${trim(String(payload.title || payload.task_id || 'Untitled task'), 42)}`);
    case 'task.started':
      return pick(locale, `🚀 开始处理：${trim(String(payload.title || payload.task_id || '某项任务'), 36)}`, `🚀 Work began on ${trim(String(payload.title || payload.task_id || 'a task'), 42)}`);
    case 'task.done':
      return pick(locale, `✅ 已经完成：${trim(String(payload.title || payload.task_id || '某项任务'), 36)}`, `✅ Finished ${trim(String(payload.title || payload.task_id || 'a task'), 42)}`);
    case 'task.failed':
      return pick(locale, `⚠️ 任务遇到阻塞：${trim(String(payload.title || payload.task_id || '未知任务'), 36)}`, `⚠️ A task hit a snag: ${trim(String(payload.title || payload.task_id || 'unknown work'), 42)}`);
    case 'role.started': {
      const action = roleInfo?.greeting
        ? pick(locale, `${roleInfo.greeting} 💪`, `"${roleInfo.greeting}" 💪`)
        : pick(locale, '💪 接住了新简报', 'picked up a brief 💪');
      return displayName
        ? `${displayName}: ${action}`
        : pick(locale, `${String(payload.display_name || '有成员')}💪 接住了新简报`, `${String(payload.display_name || 'A teammate')} picked up a brief`);
    }
    case 'role.done': {
      const wrap = roleInfo?.signoff
        ? pick(locale, `"${roleInfo.signoff}" 🎉`, `"${roleInfo.signoff}" 🎉`)
        : pick(locale, '🎉 完成了自己的部分', 'wrapped their part 🎉');
      return displayName
        ? `${displayName}: ${wrap}`
        : pick(locale, `${String(payload.display_name || '有成员')}🎉 完成了自己的部分`, `${String(payload.display_name || 'A teammate')} wrapped their part`);
    }
    case 'role.failed': {
      const follow = pick(locale, '🔄 需要进一步跟进', 'needs a follow-up 🔄');
      return displayName
        ? `${displayName}: ${follow}`
        : pick(locale, `${String(payload.display_name || '有成员')}🔄 需要进一步跟进`, `${String(payload.display_name || 'A teammate')} needs a follow-up`);
    }
    case 'executor.wakeup':
      return pick(locale, '🔔 办公室被轻轻唤醒了一次', 'The room was nudged awake 🔔');
    default:
      return trim(String(event.event || pick(locale, '📢 办公室更新', '📢 Office update')), 42);
  }
}

function formatTime(locale: ReturnType<typeof useStore.getState>['locale'], timestamp: string) {
  return new Intl.DateTimeFormat(localeTag(locale), {
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(timestamp));
}

function hashSeed(value: string) {
  return value.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
}

function trim(value: string, max: number) {
  return value.length > max ? `${value.slice(0, max - 1)}...` : value;
}

/** 空闲角色 idle 自动互动 — 前端轮询，不依赖后端 */
const IDLE_MOODS: { emoji: string; zh: string; en: string }[] = [
  { emoji: '☕', zh: '正在泡咖啡', en: 'brewing coffee' },
  { emoji: '📖', zh: '翻看着笔记', en: 'skimming through notes' },
  { emoji: '🧹', zh: '整理着桌面', en: 'tidying up the desk' },
  { emoji: '🎵', zh: '轻轻哼着歌', en: 'humming a tune' },
  { emoji: '🎍', zh: '给绿植浇了点水', en: 'watering the plants' },
  { emoji: '✍️', zh: '写着随手笔记', en: 'jotting down notes' },
  { emoji: '🍵', zh: '端着茶杯发呆', en: 'daydreaming with tea' },
  { emoji: '😴', zh: '打了个小盹', en: 'taking a quick nap' },
  { emoji: '📋', zh: '检查着待办清单', en: 'checking the to-do list' },
  { emoji: '🌤️', zh: '望着窗外发呆', en: 'gazing out the window' },
];

function useIdleMoods(memberName: string) {
  const moodIndexRef = useRef(Math.floor(Math.random() * IDLE_MOODS.length));
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [mood, setMood] = useState(IDLE_MOODS[moodIndexRef.current]);

  useEffect(() => {
    const scheduleNext = () => 8000 + Math.random() * 12000;
    function tick() {
      moodIndexRef.current = (moodIndexRef.current + 1) % IDLE_MOODS.length;
      setMood(IDLE_MOODS[moodIndexRef.current]);
      timerRef.current = setTimeout(tick, scheduleNext());
    }
    timerRef.current = setTimeout(tick, scheduleNext());
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [memberName]);

  return mood;
}

/** 首页任务输入框 — 办公室风格的委托书 */
function StudioTaskForm() {
  const locale = useStore((s) => s.locale);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState<'high' | 'medium' | 'low'>('medium');
  const [role, setRole] = useState('');
  const [loading, setLoading] = useState(false);
  const [roles, setRoles] = useState<{ name: string; display_name: string; icon: string }[]>([]);
  const setTasks = useStore((s) => s.setTasks);

  useEffect(() => {
    api.listRoles().then((r) => setRoles(r.roles)).catch(() => {});
  }, []);

  const handleDispatch = async () => {
    if (!title.trim() || loading) return;
    setLoading(true);
    try {
      await api.createTask({
        title: title.trim(),
        description: description.trim(),
        priority,
        role: role || null,
        auto_run: true,
      });
      setTitle('');
      setDescription('');
      api.getTasks().then((r) => setTasks(r.tasks)).catch(() => {});
    } catch (error) {
      console.error('Failed to create task:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleQueue = async () => {
    if (!title.trim() || loading) return;
    setLoading(true);
    try {
      await api.createTask({
        title: title.trim(),
        description: description.trim(),
        priority,
        role: role || null,
        auto_run: false,
      });
      setTitle('');
      setDescription('');
      api.getTasks().then((r) => setTasks(r.tasks)).catch(() => {});
    } catch (error) {
      console.error('Failed to queue task:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="studio-dispatch">
      <div className="dispatch-form">
        <div className="dispatch-row">
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleDispatch(); }}
            placeholder={pick(locale, '描述你想要的结果...', 'Describe what you need...')}
            className="dispatch-input"
          />
          <select
            value={priority}
            onChange={(e) => setPriority(e.target.value as 'high' | 'medium' | 'low')}
            className="dispatch-select"
          >
            <option value="high">{pick(locale, '高', 'High')}</option>
            <option value="medium">{pick(locale, '中', 'Medium')}</option>
            <option value="low">{pick(locale, '低', 'Low')}</option>
          </select>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="dispatch-select"
            title={pick(locale, '选择处理这条委托的成员', 'Choose the teammate for this request')}
          >
            <option value="">{pick(locale, '⊕ 小管家（自动规划）', '⊕ Task manager (auto)')}</option>
            {roles.filter((item) => item.name !== 'task_agent').map((item) => (
              <option key={item.name} value={item.name}>
                {item.icon} {item.display_name}
              </option>
            ))}
          </select>
        </div>
        <div className="dispatch-row dispatch-row-bottom">
          <button
            onClick={handleDispatch}
            disabled={loading || !title.trim()}
            className="dispatch-btn"
          >
            {loading ? pick(locale, '正在派件...', 'Dispatching...') : pick(locale, '🚀 立即执行', '🚀 Execute now')}
          </button>
          <button
            onClick={handleQueue}
            disabled={loading || !title.trim()}
            className="dispatch-btn dispatch-btn-queue"
          >
            {loading ? pick(locale, '正在派件...', 'Queuing...') : pick(locale, '📋 加入待办', '📋 Add to queue')}
          </button>
        </div>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={pick(locale, '补充背景、交接信息，或你希望得到的结果。', 'Add context, handoff notes, or desired outcome.')}
          rows={2}
          className="dispatch-textarea"
        />
      </div>
    </section>
  );
}

export function TeamTab() {
  const locale = useStore((s) => s.locale);
  const supervisorStatus = useStore((s) => s.supervisorStatus);
  const setSupervisorStatus = useStore((s) => s.setSupervisorStatus);
  const unreadPinCount = useStore((s) => s.unreadPinCount);
  const roleActivities = useStore((s) => s.roleActivities);
  const events = useStore((s) => s.events);
  const roles = useStore((s) => s.roles);
  const [busy, setBusy] = useState(false);
  const [maintenanceBusy, setMaintenanceBusy] = useState(false);
  const [showAnimation, setShowAnimation] = useState(false);
  const [overlayPin, setOverlayPin] = useState<Pin | null>(null);

  const refresh = () => api.getSupervisorStatus().then(setSupervisorStatus).catch(() => {});

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 8000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (events.length > 0) refresh();
  }, [events.length]);

  const team = (supervisorStatus?.team ?? []).map((member) => {
    const activity = roleActivities[member.name];
    if (!activity) return member;
    return {
      ...member,
      state: 'busy' as const,
      icon: activity.icon || member.icon,
      status_text: activity.status_text,
      current_task_id: activity.thread_id || member.current_task_id,
      current_task_title: activity.title,
    };
  });

  // 后端无数据时，从已加载的 roles 生成 idle 团队
  const fallbackTeam: TeamMember[] = useMemo(
    () =>
      team.length === 0 && roles.length > 0
        ? roles.map((role) => ({
            name: role.name,
            display_name: role.display_name,
            description: role.description || pick(locale, '团队成员', 'A team member'),
            icon: role.icon || 'WP',
            personality: role.personality || '',
            status_text: role.status_text || pick(locale, '桌面已整理，随时待命', 'Desk is tidy and ready'),
            state: 'idle' as const,
            current_task_id: null,
            current_task_title: null,
          }))
        : [],
    [roles, team.length, locale],
  );

  const effectiveTeam = (team.length > 0 ? team : fallbackTeam).filter((m) => m.name !== 'task_agent');

  const actionItems = supervisorStatus?.action_items ?? [];
  const recentEvents = useMemo(
    () =>
      [...events].slice(-6).reverse().map((event) => ({
        id: event.event_id || `${event.event}-${event.timestamp}`,
        title: describeEvent(locale, event, roles),
        time: formatTime(locale, event.timestamp),
      })),
    [events, locale],
  );

  const wakeTeam = async () => {
    setBusy(true);
    try {
      await api.wakeupExecutor();
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  const runMaintenance = async () => {
    setMaintenanceBusy(true);
    try {
      await api.runMemoryMaintenance();
      await refresh();
    } finally {
      setMaintenanceBusy(false);
    }
  };

  const retryTask = async (taskId: string) => {
    setBusy(true);
    try {
      await api.retryTaskFromSupervisor(taskId);
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="team-page">
      <ReceptionDesk
        onWakeTeam={wakeTeam}
        wakeBusy={busy}
        onMaintenance={runMaintenance}
        maintenanceBusy={maintenanceBusy}
        showAnimation={showAnimation}
        onToggleView={() => setShowAnimation(!showAnimation)}
        unreadCount={unreadPinCount}
      />

      {showAnimation ? (
        <OfficeScene team={effectiveTeam} />
      ) : (
        <div className="studio-grid">
          <div className="studio-left">
            <section className="studio-floor">
              <div className="section-header">
                <div>
                  <span className="section-kicker">{pick(locale, '人物看板', 'Live portraits')}</span>
                  <h3>{pick(locale, '办公室一览', 'The office at a glance')}</h3>
                </div>
                <span className="section-caption">
                  {pick(locale, '更新时间', 'Updated')} {formatTime(locale, supervisorStatus?.updated_at || new Date().toISOString())}
                </span>
              </div>

              <div className="office-stage">
                {effectiveTeam.map((member, index) => (
                  <CrewCard key={member.name} member={member} index={index} locale={locale} />
                ))}
              </div>
            </section>

            <PinBoard
              onExpand={(pin) => setOverlayPin(pin)}
              onAsk={(pin) => setOverlayPin(pin)}
            />
          </div>

          <SupervisorPanel
            locale={locale}
            actionItems={actionItems}
            recentEvents={recentEvents}
            retryTask={retryTask}
          />
        </div>
      )}

      {overlayPin && (
        <PinChatOverlay
          pin={overlayPin}
          onClose={() => setOverlayPin(null)}
        />
      )}
    </div>
  );
}

/** 成员卡片 — 空闲时自动切换 mood/emoji */
function CrewCard({ member, index, locale }: {
  member: TeamMember;
  index: number;
  locale: ReturnType<typeof useStore.getState>['locale'];
}) {
  const idleMood = useIdleMoods(member.name);
  const isIdle = member.state !== 'busy';
  const moodText = isIdle ? pick(locale, idleMood.zh, idleMood.en) : memberStatus(locale, member);
  const moodEmoji = isIdle ? idleMood.emoji : (member.state === 'busy' ? '💼' : '😌');

  return (
    <article className={`crew-card crew-card-${member.state}`}>
      <div className={`crew-bubble crew-bubble-${member.state}`}>
        <span>{moodEmoji} {moodText}</span>
      </div>

      <div className="crew-portrait">
        <Portrait
          label={member.display_name}
          seed={hashSeed(`${member.name}-${index}`)}
          state={member.state}
        />
      </div>

      <div className="crew-details">
        <div className="crew-heading">
          <div>
            <h4>{member.display_name}</h4>
            <p>{member.description}</p>
          </div>
          <span className={`crew-state crew-state-${member.state}`}>
            {member.state === 'busy'
              ? pick(locale, '处理中 💼', 'In motion 💼')
              : pick(locale, '待命中', 'Ready')}
          </span>
        </div>

        <p className="crew-personality">
          {member.personality || pick(locale, '气质稳定，会帮助整个办公室保持节奏。', 'Keeps a steady presence and helps the room stay in rhythm.')}
        </p>
      </div>
    </article>
  );
}

/** 主管角色面板 — 带头像 */
function SupervisorPanel({
  locale,
  actionItems,
  recentEvents,
  retryTask,
}: {
  locale: ReturnType<typeof useStore.getState>['locale'];
  actionItems: SupervisorStatus['action_items'];
  recentEvents: { id: string; title: string; time: string }[];
  retryTask: (taskId: string) => void;
}) {
  return (
    <aside className="studio-aside">
      <section className="supervisor-panel">
        <div className="section-header compact">
          <h3>{pick(locale, '📌 大管家便签', '📌 Supervisor notes')}</h3>
        </div>
        <div className="action-list">
          {actionItems.map((item, i) => (
            <div className={`action-item action-${item.level}`} key={`${item.text}-${i}`}>
              <span>{item.text}</span>
              {item.task_id && (
                <button className="action-retry" onClick={() => retryTask(item.task_id!)}>
                  {pick(locale, '重试', 'Retry')}
                </button>
              )}
            </div>
          ))}
          {actionItems.length === 0 && (
            <div className="action-item">{pick(locale, '😌 前台目前没有需要立刻处理的便签。', 'Nothing urgent is pinned to the front desk.')}</div>
          )}
        </div>
      </section>

      <section className="supervisor-panel">
        <div className="section-header compact">
          <h3>{pick(locale, '🗣️ 走廊消息', '🗣️ Hallway chatter')}</h3>
        </div>
        <div className="event-stack">
          {recentEvents.map((event) => (
            <div className="event-note" key={event.id}>
              <strong>{event.title}</strong>
              <span>{event.time}</span>
            </div>
          ))}
          {recentEvents.length === 0 && (
            <div className="event-note">
              <strong>{pick(locale, '😴 办公室很安静。', 'The office is quiet.')}</strong>
              <span>{pick(locale, '新的动态会在团队开始动作后出现在这里。', 'Fresh events will appear here as the team moves.')}</span>
            </div>
          )}
        </div>
      </section>
    </aside>
  );
}



function Portrait({
  label,
  seed,
  state,
}: {
  label: string;
  seed: number;
  state: TeamMember['state'];
}) {
  const palettes = [
    { skin: '#fde8d0', hair: '#4a3728', jacket: '#e8956a', shirt: '#fff5eb', desk: '#a0714f', accent: '#7cb89e' },
    { skin: '#f5d5be', hair: '#2d3a44', jacket: '#7a9aad', shirt: '#fff0e6', desk: '#8f6e52', accent: '#d4a06a' },
    { skin: '#e8c4a8', hair: '#3d2b2c', jacket: '#b07da0', shirt: '#fef2e6', desk: '#9e7a58', accent: '#7ea6be' },
    { skin: '#fce5c8', hair: '#7a5c42', jacket: '#8db89d', shirt: '#fff4eb', desk: '#a07858', accent: '#e08a64' },
  ] as const;
  const palette = palettes[seed % palettes.length];
  const hairStyle = seed % 5; // 5种发型
  const hasGlasses = (seed % 3) === 0; // 1/3概率戴眼镜
  const hasHairClip = (seed % 4) === 0; // 1/4概率有发夹

  // 眼睛 — 不同状态不同表情
  const eyeLeft = state === 'idle'
    ? <path d="M77 62 Q81 58 85 62" stroke="#3d2b1f" strokeWidth="2.5" strokeLinecap="round" fill="none" /> // 弯月眼（微笑）
    : state === 'busy'
      ? <><ellipse cx="81" cy="61" rx="5" ry="6" fill="white" /><ellipse cx="81" cy="61" rx="3.5" ry="4.5" fill="#3d2b1f" /><circle cx="83" cy="59" r="1.5" fill="white" /></> // 大圆睁+高光
      : <><ellipse cx="81" cy="61" rx="6" ry="7" fill="white" /><ellipse cx="81" cy="62" rx="4" ry="5" fill="#3d2b1f" /><circle cx="83" cy="59.5" r="1.8" fill="white" /></>; // 闪亮大眼
  const eyeRight = state === 'idle'
    ? <path d="M95 62 Q99 58 103 62" stroke="#3d2b1f" strokeWidth="2.5" strokeLinecap="round" fill="none" />
    : state === 'busy'
      ? <><ellipse cx="99" cy="61" rx="5" ry="6" fill="white" /><ellipse cx="99" cy="61" rx="3.5" ry="4.5" fill="#3d2b1f" /><circle cx="101" cy="59" r="1.5" fill="white" /></>
      : <><ellipse cx="99" cy="61" rx="6" ry="7" fill="white" /><ellipse cx="99" cy="62" rx="4" ry="5" fill="#3d2b1f" /><circle cx="101" cy="59.5" r="1.8" fill="white" /></>;

  // 嘴巴
  const mouthPath = state === 'idle'
    ? 'M83 73 Q90 79 97 73' // 微笑
    : state === 'busy'
      ? 'M84 74 Q90 77 96 74' // 认真抿嘴
      : 'M82 72 Q90 80 98 72'; // 开心张嘴

  // 腮红
  const blush = (
    <>
      <ellipse cx="73" cy="70" rx="6" ry="3.5" fill="#f7a8a8" opacity={state === 'idle' ? 0.5 : 0.25} />
      <ellipse cx="107" cy="70" rx="6" ry="3.5" fill="#f7a8a8" opacity={state === 'idle' ? 0.5 : 0.25} />
    </>
  );

  // 眉毛
  const brows = state === 'busy'
    ? <>
        <line x1="76" y1="52" x2="86" y2="54" stroke="#3d2b1f" strokeWidth="2" strokeLinecap="round" />
        <line x1="94" y1="54" x2="104" y2="52" stroke="#3d2b1f" strokeWidth="2" strokeLinecap="round" />
      </>
    : <>
        <path d="M76 53 Q81 51 86 53" stroke="#3d2b1f" strokeWidth="1.8" strokeLinecap="round" fill="none" />
        <path d="M94 53 Q99 51 104 53" stroke="#3d2b1f" strokeWidth="1.8" strokeLinecap="round" fill="none" />
      </>;

  // 头发 — 5 种样式
  const hair = (() => {
    const basePaths = [
      'M58 56 C58 30 75 20 90 20 C105 20 122 30 122 56 L122 68 C116 52 106 42 90 42 C74 42 64 52 58 68 Z', // 短发
      'M56 58 C56 28 74 18 90 18 C106 18 124 28 124 58 C120 44 110 36 90 36 C70 36 60 44 56 58 Z', // 卷发
      'M54 60 C54 28 72 18 90 18 C108 18 126 28 126 60 L126 100 C120 96 114 98 108 96 L108 60 C102 50 94 44 90 44 C86 44 78 50 72 60 L72 96 C66 98 60 96 54 100 Z', // 长发
      'M58 56 C58 30 75 20 90 20 C105 20 122 30 122 56 L122 68 C116 52 106 42 90 42 C74 42 64 52 58 68 Z', // 丸子头
      'M56 54 C58 28 76 18 94 18 C106 18 118 28 122 52 C118 40 106 34 90 34 C74 34 62 40 56 54 Z', // 偏分
    ] as const;
    const extras = [
      null,
      <><circle cx="58" cy="58" r="6" fill={palette.hair} /><circle cx="122" cy="58" r="6" fill={palette.hair} /></>,
      null,
      <circle cx="90" cy="18" r="10" fill={palette.hair} />,
      <path d="M56 54 C56 60 54 70 54 78 C56 78 58 68 58 60 Z" fill={palette.hair} />,
    ] as const;
    return (
      <>
        <path d={basePaths[hairStyle]} fill={palette.hair} />
        {extras[hairStyle]}
      </>
    );
  })();

  // 桌上物品
  const deskItems = state === 'idle'
    ? <>
        <circle cx="140" cy="116" r="8" fill="#f1ede4" />
        <rect x="134" y="119" width="12" height="4" rx="2" fill={palette.accent} />
        <path d="M140 110 Q139 106 141 104" stroke="#ccc" strokeWidth="1" fill="none" opacity="0.5" />
      </> // 咖啡杯+热气
    : <>
        <rect x="128" y="108" width="24" height="14" rx="2" fill="#c8c0b8" />
        <rect x="130" y="110" width="20" height="10" rx="1" fill="#6a8fa8" />
        <rect x="38" y="126" width="16" height="3" rx="1.5" fill={palette.accent} opacity="0.6" />
      </>; // 小电脑+笔

  return (
    <svg viewBox="0 0 180 160" className="portrait-svg" role="img" aria-label={label}>
      {/* 椅子靠背 */}
      <rect x="52" y="60" width="76" height="70" rx="20" fill={palette.jacket} opacity="0.12" />

      {/* 小身体（Q版：头大身小） */}
      <path d="M62 136 C64 114 76 104 90 104 C104 104 116 114 118 136" fill={palette.jacket} />
      <path d="M76 110 C80 103 85 100 90 100 C95 100 100 103 104 110 L100 136 L80 136 Z" fill={palette.shirt} />

      {/* 小手 */}
      <circle cx="62" cy="128" r="6" fill={palette.skin} />
      <circle cx="118" cy="128" r="6" fill={palette.skin} />

      {/* 大头 */}
      <ellipse cx="90" cy="58" rx="30" ry="32" fill={palette.skin} />

      {/* 头发 */}
      {hair}

      {/* 发夹 */}
      {hasHairClip && <circle cx="118" cy="42" r="3" fill="#f7a8a8" />}

      {/* 眉毛 */}
      {brows}

      {/* 眼睛 */}
      {eyeLeft}
      {eyeRight}

      {/* 腮红 */}
      {blush}

      {/* 嘴巴 */}
      <path d={mouthPath} stroke={state === 'idle' ? '#c47a6a' : '#d48a7a'} strokeWidth="2.5" strokeLinecap="round" fill="none" />

      {/* 眼镜 */}
      {hasGlasses && (
        <>
          <circle cx="81" cy="61" r="9" stroke="#666" strokeWidth="1.5" fill="none" />
          <circle cx="99" cy="61" r="9" stroke="#666" strokeWidth="1.5" fill="none" />
          <line x1="90" y1="61" x2="90" y2="61" stroke="#666" strokeWidth="1.5" />
        </>
      )}

      {/* 办公桌 — 前景 */}
      <rect x="8" y="122" width="164" height="20" rx="6" fill={palette.desk} />
      <rect x="8" y="122" width="164" height="3" rx="1.5" fill="white" opacity="0.08" />

      {/* 桌上物品 */}
      {deskItems}
    </svg>
  );
}
