import { useState } from 'react';
import { api } from '../api';
import { pick } from '../locale';
import { useStore, type Schedule } from '../store';

const CRON_PRESETS = [
  {
    cron: '0 * * * *',
    label: { zh: '每小时', en: 'Hourly' },
    hint: { zh: '每小时整点触发', en: 'Every hour on the hour' },
  },
  {
    cron: '0 9 * * *',
    label: { zh: '每天 9 点', en: 'Daily 9am' },
    hint: { zh: '每天上午 9:00', en: 'Every day at 9:00 AM' },
  },
  {
    cron: '0 9 * * 1-5',
    label: { zh: '工作日', en: 'Weekdays' },
    hint: { zh: '周一到周五上午 9:00', en: 'Monday through Friday at 9:00 AM' },
  },
  {
    cron: '0 9 * * 1',
    label: { zh: '每周', en: 'Weekly' },
    hint: { zh: '每周一上午 9:00', en: 'Every Monday at 9:00 AM' },
  },
  {
    cron: '0 12 * * *',
    label: { zh: '每天中午', en: 'Daily noon' },
    hint: { zh: '每天中午 12:00', en: 'Every day at 12:00 PM' },
  },
  {
    cron: '0 0 * * *',
    label: { zh: '夜间', en: 'Nightly' },
    hint: { zh: '每天午夜 0:00', en: 'Every day at midnight' },
  },
] as const;

export function ScheduleTab() {
  const locale = useStore((s) => s.locale);
  const schedules = useStore((s) => s.schedules);
  const setSchedules = useStore((s) => s.setSchedules);

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [type, setType] = useState<'once' | 'recurring'>('recurring');
  const [cronExpr, setCronExpr] = useState('0 9 * * *');
  const [triggerAt, setTriggerAt] = useState('');
  const [loading, setLoading] = useState(false);

  const describeCron = (expr: string) => {
    const preset = CRON_PRESETS.find((item) => item.cron === expr.trim());
    if (!preset) {
      return pick(locale, '自定义节奏：分 时 日 月 周', 'Custom cadence: minute hour day month weekday');
    }
    return pick(locale, preset.hint.zh, preset.hint.en);
  };

  const refresh = () => api.getSchedules().then((r) => setSchedules(r.schedules)).catch(() => {});

  const handleCreate = async () => {
    if (!title.trim() || loading) return;
    setLoading(true);
    try {
      await api.createSchedule({
        title: title.trim(),
        type,
        cron_expression: type === 'recurring' ? cronExpr : undefined,
        trigger_at: type === 'once' ? triggerAt : undefined,
        task_description: description.trim() || undefined,
      });
      setTitle('');
      setDescription('');
      refresh();
    } catch (error) {
      console.error('Failed to create schedule:', error);
    } finally {
      setLoading(false);
    }
  };

  const handlePause = async (schedule: Schedule) => {
    try {
      await api.pauseSchedule(schedule.id);
      refresh();
    } catch (error) {
      console.error(error);
    }
  };

  const handleResume = async (schedule: Schedule) => {
    try {
      await api.resumeSchedule(schedule.id);
      refresh();
    } catch (error) {
      console.error(error);
    }
  };

  const handleDelete = async (schedule: Schedule) => {
    try {
      await api.deleteSchedule(schedule.id);
      refresh();
    } catch (error) {
      console.error(error);
    }
  };

  return (
    <div className="sched-page">
      <header className="sched-header">
        <div>
          <h2 className="page-title">{pick(locale, '节奏台', 'Rhythm Desk')}</h2>
          <p className="page-intro">
            {pick(
              locale,
              '在这里安排办公室的跟进节奏、重复动作和一次性提醒。',
              'Set the office cadence for recurring follow-ups and one-off reminders.',
            )}
          </p>
        </div>
      </header>

      <div className="sched-form">
        <div className="sched-form-main">
          <input
            type="text"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') handleCreate();
            }}
            placeholder={pick(locale, '给这个节奏起个名字', 'Name this schedule')}
            className="sched-input"
          />
          <select
            value={type}
            onChange={(event) => setType(event.target.value as 'once' | 'recurring')}
            className="sched-select"
          >
            <option value="recurring">{pick(locale, '循环', 'Recurring')}</option>
            <option value="once">{pick(locale, '单次', 'Once')}</option>
          </select>
          <button onClick={handleCreate} disabled={loading || !title.trim()} className="sched-create-btn">
            {loading ? pick(locale, '创建中...', 'Creating...') : pick(locale, '创建', 'Create')}
          </button>
        </div>

        <div className="sched-desc-row">
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder={pick(locale, '当这个节奏被唤醒时，希望办公室做什么？', 'What should the office do when this schedule wakes up?')}
            className="sched-description"
            rows={2}
          />
        </div>

        <div className="sched-form-timing">
          {type === 'recurring' ? (
            <>
              <div className="sched-timing-row">
                <input
                  type="text"
                  value={cronExpr}
                  onChange={(event) => setCronExpr(event.target.value)}
                  placeholder="Cron expression"
                  className="sched-cron"
                  spellCheck={false}
                />
                <div className="sched-cron-presets">
                  {CRON_PRESETS.map((preset) => (
                    <button
                      key={preset.cron}
                      className={`sched-preset-btn ${cronExpr.trim() === preset.cron ? 'active' : ''}`}
                      onClick={() => setCronExpr(preset.cron)}
                      title={preset.cron}
                    >
                      {pick(locale, preset.label.zh, preset.label.en)}
                    </button>
                  ))}
                </div>
              </div>
              <p className="sched-cron-hint">
                <span className="sched-cron-desc">{describeCron(cronExpr)}</span>
                <span className="sched-cron-format">{pick(locale, '格式：分 时 日 月 周', 'Format: min hr dom mon dow')}</span>
              </p>
            </>
          ) : (
            <div className="sched-timing-row">
              <input
                type="datetime-local"
                value={triggerAt}
                onChange={(event) => setTriggerAt(event.target.value)}
                className="sched-date"
              />
              <p className="sched-date-hint">{pick(locale, '会在所选时间执行一次', 'Runs once at the selected date and time')}</p>
            </div>
          )}
        </div>
      </div>

      <div className="sched-list">
        {schedules.length === 0 && (
          <p className="sched-empty">
            {pick(locale, '还没有任何节奏安排，可以在上面先创建一个。', 'No schedules yet. Create one above to set the office rhythm.')}
          </p>
        )}

        {schedules.map((schedule) => (
          <div key={schedule.id} className="sched-card">
            <div className="sched-card-info">
              <h4>{schedule.name}</h4>
              {schedule.task_description && <p className="sched-card-desc">{schedule.task_description}</p>}
              <code className="sched-cron-display">
                {schedule.cron_expression
                  ? `${schedule.cron_expression} | ${describeCron(schedule.cron_expression)}`
                  : schedule.trigger_at && new Date(schedule.trigger_at).toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US')}
              </code>
              <div className="sched-tags">
                <span className={`sched-tag ${schedule.enabled ? 'sched-tag-active' : 'sched-tag-paused'}`}>
                  {schedule.enabled ? pick(locale, '启用中', 'Active') : pick(locale, '已暂停', 'Paused')}
                </span>
                <span className="sched-tag sched-tag-type">
                  {schedule.schedule_type === 'recurring'
                    ? pick(locale, '循环', 'recurring')
                    : pick(locale, '单次', 'once')}
                </span>
              </div>
            </div>
            <div className="sched-card-actions">
              {schedule.enabled ? (
                <button onClick={() => handlePause(schedule)} className="sched-action-btn sched-action-pause">
                  {pick(locale, '暂停', 'Pause')}
                </button>
              ) : (
                <button onClick={() => handleResume(schedule)} className="sched-action-btn sched-action-resume">
                  {pick(locale, '恢复', 'Resume')}
                </button>
              )}
              <button onClick={() => handleDelete(schedule)} className="sched-action-btn sched-action-delete">
                {pick(locale, '删除', 'Delete')}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
