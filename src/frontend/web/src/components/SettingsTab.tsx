import { useEffect, useState } from 'react';
import { api } from '../api';
import { pick } from '../locale';
import { useStore, type McpServer } from '../store';

const CHANNEL_META: Record<string, { icon: string; descZh: string; descEn: string }> = {
  telegram: {
    icon: 'TG',
    descZh: 'Telegram 机器人渠道，支持私聊和群聊。',
    descEn: 'Telegram bot channel for direct messages and group chats.',
  },
  feishu: {
    icon: 'FS',
    descZh: '飞书机器人渠道，适合企业内部消息推送。',
    descEn: 'Feishu bot channel for internal team notifications.',
  },
  lark: {
    icon: 'LK',
    descZh: 'Lark 海外版机器人渠道。',
    descEn: 'Lark bot channel for the international workspace.',
  },
};

interface McpEditorState {
  name: string;
  command: string;
  args: string;
  url: string;
  headers: string;
  env: string;
  cwd: string;
  transport: 'stdio' | 'remote';
}

const EMPTY_MCP_EDITOR: McpEditorState = {
  name: '',
  command: '',
  args: '',
  url: '',
  headers: '',
  env: '',
  cwd: '',
  transport: 'stdio',
};

export function SettingsTab() {
  const locale = useStore((s) => s.locale);
  const roles = useStore((s) => s.roles);
  const setRoles = useStore((s) => s.setRoles);
  const editorOpen = useStore((s) => s.editorOpen);
  const setEditorOpen = useStore((s) => s.setEditorOpen);
  const editingRole = useStore((s) => s.editingRole);
  const setEditingRole = useStore((s) => s.setEditingRole);
  const editorForm = useStore((s) => s.editorForm);
  const setEditorField = useStore((s) => s.setEditorField);
  const resetEditorForm = useStore((s) => s.resetEditorForm);

  const channels = useStore((s) => s.channels);
  const setChannels = useStore((s) => s.setChannels);
  const updateChannel = useStore((s) => s.updateChannel);

  const pollInterval = useStore((s) => s.pollInterval);
  const setPollInterval = useStore((s) => s.setPollInterval);
  const wakeupLoading = useStore((s) => s.wakeupLoading);
  const setWakeupLoading = useStore((s) => s.setWakeupLoading);

  const mcpServers = useStore((s) => s.mcpServers);
  const setMcpServers = useStore((s) => s.setMcpServers);
  const updateMcpServer = useStore((s) => s.updateMcpServer);

  const [toast, setToast] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [channelBusy, setChannelBusy] = useState<Record<string, boolean>>({});

  const [skills, setSkills] = useState<any[]>([]);
  const [skillsRefreshing, setSkillsRefreshing] = useState(false);

  const [mcpEditorOpen, setMcpEditorOpen] = useState(false);
  const [mcpJsonEditorOpen, setMcpJsonEditorOpen] = useState(false);
  const [mcpJsonContent, setMcpJsonContent] = useState('');
  const [mcpEditor, setMcpEditor] = useState<McpEditorState>(EMPTY_MCP_EDITOR);
  const [editingMcp, setEditingMcp] = useState<McpServer | null>(null);
  const [mcpBusy, setMcpBusy] = useState<Record<string, boolean>>({});
  const [confirmDeleteMcp, setConfirmDeleteMcp] = useState<string | null>(null);
  const [mcpListLoading, setMcpListLoading] = useState(false);

  useEffect(() => {
    api.listRoles().then((r) => setRoles(r.roles)).catch(() => {});
    api.listChannels().then((r) => setChannels(r.channels)).catch(() => {});
    api.getSkills().then((r) => setSkills(r.skills)).catch(() => {});
    api.getMcpServers().then((r) => setMcpServers(r.servers)).catch(() => {});
  }, []);

  const showToast = (message: string) => {
    setToast(message);
    setTimeout(() => setToast(null), 3000);
  };

  const openNewRole = () => {
    resetEditorForm();
    setEditingRole(null);
    setEditorOpen(true);
  };

  const openEditRole = (role: typeof roles[number]) => {
    setEditingRole(role);
    setEditorField('name', role.name);
    setEditorField('display_name', role.display_name);
    setEditorField('description', role.description);
    setEditorField('icon', role.icon || 'WP');
    setEditorField('personality', role.personality || '');
    setEditorField('greeting', role.greeting || '');
    setEditorField('signoff', role.signoff || '');
    setEditorField('status_text', role.status_text || '');
    api.getRole(role.name)
      .then((r) => {
        setEditorField('system_prompt', r.role.system_prompt || '');
        setEditorField('model', r.role.model || '');
        setEditorField('tools', (r.role.tools || []).join(', '));
        setEditorField('personality', r.role.personality || '');
        setEditorField('greeting', r.role.greeting || '');
        setEditorField('signoff', r.role.signoff || '');
        setEditorField('status_text', r.role.status_text || '');
      })
      .catch(() => {});
    setEditorOpen(true);
  };

  const saveRole = async () => {
    if (!editorForm.name.trim() || !editorForm.display_name.trim() || !editorForm.system_prompt.trim()) {
      showToast(pick(locale, '请填写名称、显示名和系统提示。', 'Please fill in the name, display name, and system prompt.'));
      return;
    }
    try {
      if (editingRole) {
        await api.updateRole(editingRole.name, {
          name: editorForm.name.trim(),
          display_name: editorForm.display_name.trim(),
          description: editorForm.description.trim(),
          icon: editorForm.icon,
          system_prompt: editorForm.system_prompt.trim(),
          tools: editorForm.tools
            ? editorForm.tools.split(',').map((item: string) => item.trim()).filter(Boolean)
            : null,
          model: editorForm.model || null,
          personality: editorForm.personality.trim(),
          greeting: editorForm.greeting.trim(),
          signoff: editorForm.signoff.trim(),
          status_text: editorForm.status_text.trim(),
        });
        showToast(pick(locale, '角色已更新。', 'Role updated.'));
      } else {
        await api.createRole({
          name: editorForm.name.trim(),
          display_name: editorForm.display_name.trim(),
          description: editorForm.description.trim(),
          icon: editorForm.icon,
          system_prompt: editorForm.system_prompt.trim(),
          tools: editorForm.tools
            ? editorForm.tools.split(',').map((item: string) => item.trim()).filter(Boolean)
            : undefined,
          model: editorForm.model || undefined,
          personality: editorForm.personality.trim(),
          greeting: editorForm.greeting.trim(),
          signoff: editorForm.signoff.trim(),
          status_text: editorForm.status_text.trim(),
        });
        showToast(pick(locale, '角色已创建。', 'Role created.'));
      }
      setEditorOpen(false);
      api.listRoles().then((r) => setRoles(r.roles)).catch(() => {});
    } catch (error: any) {
      showToast(error.message || pick(locale, '操作失败', 'Operation failed'));
    }
  };

  const handleDelete = async (name: string) => {
    try {
      await api.deleteRole(name);
      showToast(pick(locale, `角色 "${name}" 已删除。`, `Role "${name}" deleted.`));
      setConfirmDelete(null);
      api.listRoles().then((r) => setRoles(r.roles)).catch(() => {});
    } catch (error: any) {
      showToast(error.message || pick(locale, '删除失败', 'Delete failed'));
    }
  };

  const toggleChannel = async (name: string, currentlyConnected: boolean) => {
    if (channelBusy[name]) return;
    setChannelBusy((prev) => ({ ...prev, [name]: true }));
    try {
      if (currentlyConnected) {
        await api.disconnectChannel(name);
        updateChannel({ name, enabled: true, connected: false, display_name: name });
        showToast(pick(locale, `渠道 "${name}" 已断开。`, `Channel "${name}" disconnected.`));
      } else {
        const res = await api.connectChannel(name);
        updateChannel({ name, enabled: true, connected: res.status === 'connected', display_name: name });
        showToast(
          res.status === 'connected'
            ? pick(locale, `渠道 "${name}" 已连接。`, `Channel "${name}" connected.`)
            : pick(locale, `渠道 "${name}" 连接失败。`, `Channel "${name}" failed to connect.`),
        );
      }
    } catch (error: any) {
      showToast(error.message || pick(locale, '操作失败', 'Operation failed'));
    } finally {
      setChannelBusy((prev) => ({ ...prev, [name]: false }));
    }
  };

  const handleWakeup = async () => {
    setWakeupLoading(true);
    try {
      await api.wakeupExecutor();
      showToast(pick(locale, '已触发立即执行，请稍候查看任务状态。', 'Wakeup triggered. Check task status shortly.'));
    } catch (error: any) {
      showToast(error.message || pick(locale, '触发执行失败', 'Wakeup failed'));
    } finally {
      setWakeupLoading(false);
    }
  };

  const handleRefreshSkills = async () => {
    setSkillsRefreshing(true);
    try {
      const res = await api.refreshSkills();
      const parts: string[] = [];
      if (res.added.length) parts.push(pick(locale, `新增 ${res.added.join('、')}`, `Added: ${res.added.join(', ')}`));
      if (res.removed.length) parts.push(pick(locale, `移除 ${res.removed.join('、')}`, `Removed: ${res.removed.join(', ')}`));
      setSkills(res.skills);
      showToast(
        parts.length
          ? parts.join('；')
          : pick(locale, '已刷新，技能列表无变化。', 'Skills refreshed. No changes detected.'),
      );
    } catch (error: any) {
      showToast(error.message || pick(locale, '刷新失败', 'Refresh failed'));
    } finally {
      setSkillsRefreshing(false);
    }
  };

  const handlePollIntervalChange = async (minutes: number) => {
    setPollInterval(minutes);
    try {
      await api.setPollInterval(minutes);
    } catch {
      // silently ignore
    }
  };

  // ── MCP handlers ──

  const refreshMcpList = async () => {
    setMcpListLoading(true);
    try {
      const res = await api.getMcpServers();
      setMcpServers(res.servers);
    } catch {
      // silently ignore
    } finally {
      setMcpListLoading(false);
    }
  };

  const openNewMcp = () => {
    setEditingMcp(null);
    setMcpEditor(EMPTY_MCP_EDITOR);
    setMcpEditorOpen(true);
  };

  const openMcpJsonEditor = () => {
    const config: Record<string, any> = {};
    mcpServers.forEach((s) => {
      const serverCfg = { ...s.config, enabled: s.enabled };
      // Strip name as it's the key
      delete (serverCfg as any).name;
      config[s.name] = serverCfg;
    });
    setMcpJsonContent(JSON.stringify({ mcpServers: config }, null, 2));
    setMcpJsonEditorOpen(true);
  };

  const saveMcpJsonConfig = async () => {
    try {
      const parsed = JSON.parse(mcpJsonContent);
      if (!parsed.mcpServers || typeof parsed.mcpServers !== 'object') {
        showToast(pick(locale, 'JSON 格式不正确，必须包含 "mcpServers" 对象。', 'Invalid JSON format. Must contain "mcpServers" object.'));
        return;
      }
      const res = await api.replaceMcpConfig(parsed);
      if (res.ok) {
        showToast(pick(locale, 'MCP 配置已更新。', 'MCP configuration updated.'));
        await refreshMcpList();
        setMcpJsonEditorOpen(false);
      } else {
        showToast(pick(locale, '更新失败。', 'Update failed.'));
      }
    } catch (e: any) {
      showToast(pick(locale, `JSON 解析失败: ${e.message}`, `JSON parse error: ${e.message}`));
    }
  };

  const openEditMcp = (server: McpServer) => {
    setEditingMcp(server);
    setMcpEditor({
      name: server.name,
      command: server.config.command || '',
      args: (server.config.args || []).join(' '),
      url: server.config.url || '',
      headers: Object.entries(server.config.headers || {}).map(([k, v]) => `${k}=${v}`).join('\n'),
      env: Object.entries(server.config.env || {}).map(([k, v]) => `${k}=${v}`).join('\n'),
      cwd: server.config.cwd || '',
      transport: server.config.command ? 'stdio' : 'remote',
    });
    setMcpEditorOpen(true);
  };

  const setMcpEditorField = (field: keyof McpEditorState, value: string) => {
    setMcpEditor((prev) => ({ ...prev, [field]: value }));
  };

  const saveMcpServer = async () => {
    if (!mcpEditor.name.trim()) {
      showToast(pick(locale, '请输入服务器名称。', 'Please enter a server name.'));
      return;
    }
    if (mcpEditor.transport === 'stdio' && !mcpEditor.command.trim()) {
      showToast(pick(locale, '请输入命令 (command)。', 'Please enter a command.'));
      return;
    }
    if (mcpEditor.transport === 'remote' && !mcpEditor.url.trim()) {
      showToast(pick(locale, '请输入服务器地址 (URL)。', 'Please enter a server URL.'));
      return;
    }

    const headers: Record<string, string> = {};
    mcpEditor.headers.split('\n').forEach((line) => {
      const [k, ...rest] = line.split('=');
      if (k.trim() && rest.length) headers[k.trim()] = rest.join('=').trim();
    });

    const env: Record<string, string> = {};
    mcpEditor.env.split('\n').forEach((line) => {
      const [k, ...rest] = line.split('=');
      if (k.trim() && rest.length) env[k.trim()] = rest.join('=').trim();
    });

    const payload: Record<string, any> = {};
    if (mcpEditor.transport === 'stdio') {
      payload.command = mcpEditor.command.trim();
      payload.args = mcpEditor.args.trim() ? mcpEditor.args.trim().split(/\s+/) : [];
      payload.env = Object.keys(env).length ? env : undefined;
      if (mcpEditor.cwd.trim()) payload.cwd = mcpEditor.cwd.trim();
    } else {
      payload.url = mcpEditor.url.trim();
      payload.headers = Object.keys(headers).length ? headers : undefined;
    }

    setMcpBusy((prev) => ({ ...prev, [mcpEditor.name]: true }));
    try {
      let res;
      if (editingMcp) {
        res = await api.updateMcpServer(editingMcp.name, payload);
      } else {
        res = await api.connectMcpServer({ name: mcpEditor.name.trim(), ...payload });
      }
      if (res.error) {
        showToast(res.error);
      } else {
        showToast(pick(locale, 'MCP 服务器已更新。', 'MCP server updated.'));
        await refreshMcpList();
        setMcpEditorOpen(false);
      }
    } catch (error: any) {
      showToast(error.message || pick(locale, '操作失败', 'Operation failed'));
    } finally {
      setMcpBusy((prev) => ({ ...prev, [mcpEditor.name]: false }));
    }
  };

  const handleMcpDisconnect = async (name: string) => {
    setMcpBusy((prev) => ({ ...prev, [name]: true }));
    try {
      const res = await api.disconnectMcpServer(name);
      if (res.error) {
        showToast(res.error);
      } else {
        showToast(pick(locale, `已断开 "${name}"。`, `Disconnected "${name}".`));
        await refreshMcpList();
      }
    } catch (error: any) {
      showToast(error.message || pick(locale, '操作失败', 'Operation failed'));
    } finally {
      setMcpBusy((prev) => ({ ...prev, [name]: false }));
    }
  };

  const handleMcpReload = async (name: string) => {
    setMcpBusy((prev) => ({ ...prev, [name]: true }));
    try {
      const res = await api.reloadMcpServer(name);
      if (res.error) {
        showToast(res.error);
      } else {
        showToast(pick(locale, `"${name}" 已重载，注册了 ${res.tools?.length || 0} 个工具。`, `"${name}" reloaded, ${res.tools?.length || 0} tools registered.`));
        await refreshMcpList();
      }
    } catch (error: any) {
      showToast(error.message || pick(locale, '重载失败', 'Reload failed'));
    } finally {
      setMcpBusy((prev) => ({ ...prev, [name]: false }));
    }
  };

  const handleDeleteMcp = async (name: string) => {
    try {
      const res = await api.removeMcpServer(name);
      if (res.error) {
        showToast(res.error);
      } else {
        showToast(pick(locale, `服务器 "${name}" 已移除。`, `Server "${name}" removed.`));
        await refreshMcpList();
      }
      setConfirmDeleteMcp(null);
    } catch (error: any) {
      showToast(error.message || pick(locale, '删除失败', 'Delete failed'));
    }
  };

  return (
    <div className="settings-page">
      <div className="settings-header">
        <div>
          <h2 className="page-title">{pick(locale, '设置', 'Settings')}</h2>
          <p className="page-intro">
            {pick(
              locale,
              '管理角色、MCP 服务器、查看内置能力，并维护即时通讯渠道连接。',
              'Manage roles, MCP servers, installed capabilities, and messaging channels.',
            )}
          </p>
        </div>
      </div>

      <div className="settings-body">
        <section className="settings-section">
          <div className="section-header">
            <h3>{pick(locale, '角色管理', 'Role management')}</h3>
            <button className="settings-add-btn" onClick={openNewRole}>
              + {pick(locale, '新建角色', 'New role')}
            </button>
          </div>

          <div className="role-list">
            {roles.map((role) => (
              <div className="role-card" key={role.name}>
                <div className="role-icon">{role.icon || 'WP'}</div>
                <div className="role-info">
                  <div className="role-name">{role.display_name}</div>
                  <div className="role-desc">
                    {role.description || pick(locale, '暂时没有描述。', 'No description yet.')}
                  </div>
                </div>
                <div className="role-actions">
                  <button className="role-btn-edit" onClick={() => openEditRole(role)}>
                    {pick(locale, '编辑', 'Edit')}
                  </button>
                  {(role.name === 'executor' || role.name === 'task_agent') ? (
                    <button
                      className="role-btn-delete"
                      disabled
                      title={pick(locale, '内置角色不可删除', 'Built-in roles cannot be deleted')}
                    >
                      {pick(locale, '锁定', 'Locked')}
                    </button>
                  ) : (
                    <button className="role-btn-delete" onClick={() => setConfirmDelete(role.name)}>
                      {pick(locale, '删除', 'Delete')}
                    </button>
                  )}
                </div>
              </div>
            ))}
            {roles.length === 0 && (
              <div className="settings-empty">
                {pick(locale, '还没有角色，点击右上角先创建一个。', 'There are no roles yet. Create one from the top right.')}
              </div>
            )}
          </div>
        </section>

        {/* ─ MCP Servers ── */}
        <section className="settings-section">
          <div className="section-header">
            <h3>{pick(locale, 'MCP 服务器', 'MCP servers')}</h3>
            <div className="section-header-actions">
              <button className="settings-add-btn secondary" onClick={openMcpJsonEditor}>
                {pick(locale, '手动配置 (JSON)', 'Manual config (JSON)')}
              </button>
              <button className="settings-add-btn" onClick={openNewMcp}>
                + {pick(locale, '添加服务器', 'Add server')}
              </button>
            </div>
          </div>
          <div className="mcp-list">
            {mcpServers.map((server) => (
              <div className={`mcp-card ${server.enabled ? '' : 'mcp-card-disabled'}`} key={server.name}>
                <div className="mcp-icon">{server.transport === 'stdio' ? '' : '☁'}</div>
                <div className="mcp-info">
                  <div className="mcp-name">
                    {server.name}
                    <span className={`mcp-dot ${server.connected ? 'connected' : 'disconnected'}`} />
                    {server.enabled ? null : (
                      <span className="mcp-disabled-label">
                        {pick(locale, '未启用', 'Disabled')}
                      </span>
                    )}
                  </div>
                  <div className="mcp-meta">
                    {server.transport === 'stdio'
                      ? `${server.config.command || 'stdio'}${server.config.args?.length ? ' ' + server.config.args.join(' ') : ''}`
                      : server.config.url || 'remote'}
                    {server.connected && (
                      <span className="mcp-tool-count">
                        {server.tool_count} {pick(locale, '个工具', 'tools')}
                      </span>
                    )}
                  </div>
                </div>
                <div className="mcp-actions">
                  <button
                    className={`mcp-btn mcp-btn-toggle ${server.enabled ? 'mcp-btn-enabled' : 'mcp-btn-disabled'}`}
                    disabled={mcpBusy[server.name]}
                    onClick={async () => {
                      setMcpBusy((prev) => ({ ...prev, [server.name]: true }));
                      try {
                        await api.toggleMcpServer(server.name);
                        await refreshMcpList();
                      } catch (error: any) {
                        showToast(error.message || pick(locale, '操作失败', 'Operation failed'));
                      } finally {
                        setMcpBusy((prev) => ({ ...prev, [server.name]: false }));
                      }
                    }}
                  >
                    {server.enabled
                      ? pick(locale, '已启用', 'Enabled')
                      : pick(locale, '已禁用', 'Disabled')}
                  </button>
                  {server.connected ? (
                    <>
                      <button
                        className="mcp-btn mcp-btn-reload"
                        disabled={mcpBusy[server.name]}
                        onClick={() => handleMcpReload(server.name)}
                      >
                        {pick(locale, '重载', 'Reload')}
                      </button>
                      <button
                        className="mcp-btn mcp-btn-disconnect"
                        disabled={mcpBusy[server.name]}
                        onClick={() => handleMcpDisconnect(server.name)}
                      >
                        {pick(locale, '断开', 'Disconnect')}
                      </button>
                    </>
                  ) : (
                    <button
                      className="mcp-btn mcp-btn-connect"
                      disabled={mcpBusy[server.name]}
                      onClick={() => {
                        if (editingMcp) return;
                        setEditingMcp(server);
                        setMcpEditor({
                          name: server.name,
                          command: server.config.command || '',
                          args: (server.config.args || []).join(' '),
                          url: server.config.url || '',
                          headers: Object.entries(server.config.headers || {}).map(([k, v]) => `${k}=${v}`).join('\n'),
                          env: Object.entries(server.config.env || {}).map(([k, v]) => `${k}=${v}`).join('\n'),
                          cwd: server.config.cwd || '',
                          transport: server.config.command ? 'stdio' : 'remote',
                        });
                        setMcpEditorOpen(true);
                      }}
                    >
                      {pick(locale, '连接', 'Connect')}
                    </button>
                  )}
                  <button className="mcp-btn mcp-btn-edit" onClick={() => openEditMcp(server)}>
                    {pick(locale, '编辑', 'Edit')}
                  </button>
                  <button className="mcp-btn mcp-btn-delete" onClick={() => setConfirmDeleteMcp(server.name)}>
                    {pick(locale, '删除', 'Delete')}
                  </button>
                </div>
              </div>
            ))}
            {mcpServers.length === 0 && (
              <div className="settings-empty">
                {pick(locale, '还没有配置 MCP 服务器，点击右上角添加。', 'No MCP servers configured yet. Click Add server to get started.')}
              </div>
            )}
          </div>
        </section>

        <section className="settings-section">
          <div className="section-header">
            <h3>{pick(locale, '已启用能力', 'Installed capabilities')}</h3>
            <button className="settings-add-btn" onClick={handleRefreshSkills} disabled={skillsRefreshing}>
              {skillsRefreshing ? pick(locale, '刷新中...', 'Refreshing...') : `+ ${pick(locale, '刷新', 'Refresh')}`}
            </button>
          </div>
          <div className="skill-list">
            {skills.map((s) => (
              <div className="skill-item" key={s.name}>
                <span className="skill-name">
                  {s.name}
                  {s.version ? ` v${s.version}` : ''}
                  {!s.should_auto_load && (
                    <span className="skill-badge">
                      {pick(locale, '手动触发', 'Manual')}
                    </span>
                  )}
                </span>
                <span className="skill-desc">{s.description}</span>
              </div>
            ))}
            {skills.length === 0 && (
              <div className="settings-empty">
                {pick(locale, '还没有加载任何技能，点击右上角刷新。', 'No skills loaded yet. Click refresh above to scan.')}
              </div>
            )}
          </div>
        </section>

        <section className="settings-section">
          <div className="section-header">
            <h3>{pick(locale, '执行器控制', 'Executor control')}</h3>
          </div>
          <div className="executor-control">
            <div className="executor-field">
              <label>{pick(locale, '轮询间隔', 'Poll interval')}</label>
              <div className="executor-slider-row">
                <input
                  type="range"
                  min={1}
                  max={60}
                  value={pollInterval}
                  onChange={(e) => handlePollIntervalChange(Number(e.target.value))}
                  className="executor-slider"
                />
                <span className="executor-slider-value">{pollInterval} {pick(locale, '分钟', 'min')}</span>
              </div>
              <p className="executor-hint">
                {pick(
                  locale,
                  `后台执行器每 ${pollInterval} 分钟检查一次待办任务。`,
                  `Background executor checks tasks every ${pollInterval} minutes.`,
                )}
              </p>
            </div>
            <div className="executor-field">
              <button
                className="executor-wakeup-btn"
                disabled={wakeupLoading}
                onClick={handleWakeup}
              >
                {wakeupLoading
                  ? pick(locale, '执行中...', 'Executing...')
                  : pick(locale, '▶️ 立即执行待办任务', '▶️ Execute tasks now')}
              </button>
              <p className="executor-hint">
                {pick(
                  locale,
                  '唤醒后台执行器立即检查并执行待办任务。',
                  'Wake the background executor to check and execute pending tasks immediately.',
                )}
              </p>
            </div>
          </div>
        </section>

        <section className="settings-section">
          <div className="section-header">
            <h3>{pick(locale, '即时通讯渠道', 'Messaging channels')}</h3>
          </div>
          <div className="channel-list">
            {channels.map((channel) => {
              const meta = CHANNEL_META[channel.name] || {
                icon: 'IM',
                descZh: '即时通讯平台连接。',
                descEn: 'Instant messaging platform connection.',
              };
              return (
                <div className="channel-card" key={channel.name}>
                  <div className="channel-icon">{meta.icon}</div>
                  <div className="channel-info">
                    <div className="channel-name">{channel.display_name || channel.name}</div>
                    <div className="channel-desc">
                      {pick(locale, meta.descZh, meta.descEn)}
                    </div>
                  </div>
                  <div className="channel-status">
                    <span className={`channel-dot ${channel.connected ? 'connected' : 'disconnected'}`} />
                    <span className="channel-status-text">
                      {channel.connected ? pick(locale, '已连接', 'Connected') : pick(locale, '未连接', 'Disconnected')}
                    </span>
                  </div>
                  <button
                    className={`channel-btn ${channel.connected ? 'channel-btn-disconnect' : 'channel-btn-connect'}`}
                    disabled={!!channelBusy[channel.name]}
                    onClick={() => toggleChannel(channel.name, channel.connected)}
                  >
                    {channelBusy[channel.name]
                      ? pick(locale, '处理中...', 'Working...')
                      : channel.connected
                        ? pick(locale, '断开', 'Disconnect')
                        : pick(locale, '连接', 'Connect')}
                  </button>
                </div>
              );
            })}
            {channels.length === 0 && (
              <div className="settings-empty">
                {pick(locale, '还没有配置任何 IM 渠道，配置完成后会显示在这里。', 'No IM channels are configured yet. They will appear here once configured.')}
              </div>
            )}
          </div>
        </section>
      </div>

      {/* ── Role editor ── */}
      {editorOpen && (
        <div className="editor-overlay" onClick={() => setEditorOpen(false)}>
          <div className="editor-panel" onClick={(event) => event.stopPropagation()}>
            <div className="editor-header">
              <h3>{editingRole ? pick(locale, '编辑角色', 'Edit role') : pick(locale, '新建角色', 'New role')}</h3>
              <button className="editor-close" onClick={() => setEditorOpen(false)}>
                {pick(locale, '关闭', 'Close')}
              </button>
            </div>
            <div className="editor-body">
              <div className="editor-field">
                <label>{pick(locale, '名称（标识符）', 'Name (identifier)')}</label>
                <input
                  className="editor-input"
                  value={editorForm.name}
                  onChange={(event) => setEditorField('name', event.target.value)}
                  placeholder="research"
                  disabled={!!editingRole}
                />
              </div>
              <div className="editor-row">
                <div className="editor-field">
                  <label>{pick(locale, '显示名称', 'Display name')}</label>
                  <input
                    className="editor-input"
                    value={editorForm.display_name}
                    onChange={(event) => setEditorField('display_name', event.target.value)}
                    placeholder={pick(locale, '例如：调研助手', 'e.g. Research assistant')}
                  />
                </div>
                <div className="editor-field editor-field-icon">
                  <label>{pick(locale, '图标', 'Icon')}</label>
                  <input
                    className="editor-input"
                    value={editorForm.icon}
                    onChange={(event) => setEditorField('icon', event.target.value)}
                    placeholder="WP"
                  />
                </div>
              </div>
              <div className="editor-field">
                <label>{pick(locale, '人格气质', 'Personality')}</label>
                <input
                  className="editor-input"
                  value={editorForm.personality}
                  onChange={(event) => setEditorField('personality', event.target.value)}
                  placeholder={pick(locale, '例如：谨慎、直接、擅长归纳风险', 'e.g. careful, direct, good at summarizing risks')}
                />
              </div>
              <div className="editor-row">
                <div className="editor-field">
                  <label>{pick(locale, '接手口吻', 'Greeting tone')}</label>
                  <input
                    className="editor-input"
                    value={editorForm.greeting}
                    onChange={(event) => setEditorField('greeting', event.target.value)}
                    placeholder={pick(locale, '收到，我先把这件事接住。', 'Got it, I will take this on first.')}
                  />
                </div>
                <div className="editor-field">
                  <label>{pick(locale, '状态文案', 'Status text')}</label>
                  <input
                    className="editor-input"
                    value={editorForm.status_text}
                    onChange={(event) => setEditorField('status_text', event.target.value)}
                    placeholder={pick(locale, '正在整理资料', 'Organizing notes')}
                  />
                </div>
              </div>
              <div className="editor-field">
                <label>{pick(locale, '交付口吻', 'Signoff tone')}</label>
                <input
                  className="editor-input"
                  value={editorForm.signoff}
                  onChange={(event) => setEditorField('signoff', event.target.value)}
                  placeholder={pick(locale, '我已经整理好了，重点都在前面。', 'This is wrapped and the key points are up front.')}
                />
              </div>
              <div className="editor-field">
                <label>{pick(locale, '描述', 'Description')}</label>
                <input
                  className="editor-input"
                  value={editorForm.description}
                  onChange={(event) => setEditorField('description', event.target.value)}
                  placeholder={pick(locale, '用一句话描述这个角色。', 'Describe this role in one sentence.')}
                />
              </div>
              <div className="editor-field">
                <label>{pick(locale, '系统提示（角色指令）', 'System prompt')}</label>
                <textarea
                  className="editor-textarea"
                  value={editorForm.system_prompt}
                  onChange={(event) => setEditorField('system_prompt', event.target.value)}
                  placeholder="You are a research specialist. When investigating a topic..."
                  rows={10}
                />
              </div>
              <div className="editor-row">
                <div className="editor-field">
                  <label>{pick(locale, '工具（逗号分隔）', 'Tools (comma separated)')}</label>
                  <input
                    className="editor-input"
                    value={editorForm.tools}
                    onChange={(event) => setEditorField('tools', event.target.value)}
                    placeholder="web_search, web_extract, file_write"
                  />
                </div>
                <div className="editor-field editor-field-model">
                  <label>{pick(locale, '模型路由', 'Model route')}</label>
                  <input
                    className="editor-input"
                    value={editorForm.model}
                    onChange={(event) => setEditorField('model', event.target.value)}
                    placeholder="chat / utility / utility_large"
                  />
                </div>
              </div>
              <div className="editor-actions">
                <button className="editor-btn editor-btn-cancel" onClick={() => setEditorOpen(false)}>
                  {pick(locale, '取消', 'Cancel')}
                </button>
                <button className="editor-btn editor-btn-save" onClick={saveRole}>
                  {pick(locale, '保存', 'Save')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ─ MCP editor ── */}
      {mcpEditorOpen && (
        <div className="editor-overlay" onClick={() => setMcpEditorOpen(false)}>
          <div className="editor-panel mcp-editor-panel" onClick={(event) => event.stopPropagation()}>
            <div className="editor-header">
              <h3>{editingMcp ? pick(locale, '编辑 MCP 服务器', 'Edit MCP server') : pick(locale, '添加 MCP 服务器', 'Add MCP server')}</h3>
              <button className="editor-close" onClick={() => setMcpEditorOpen(false)}>
                {pick(locale, '关闭', 'Close')}
              </button>
            </div>
            <div className="editor-body">
              <div className="editor-field">
                <label>{pick(locale, '服务器名称', 'Server name')}</label>
                <input
                  className="editor-input"
                  value={mcpEditor.name}
                  onChange={(e) => setMcpEditorField('name', e.target.value)}
                  placeholder="amap-maps"
                  disabled={!!editingMcp}
                />
              </div>

              <div className="mcp-transport-toggle">
                <button
                  className={`mcp-toggle-btn ${mcpEditor.transport === 'stdio' ? 'active' : ''}`}
                  onClick={() => setMcpEditorField('transport', 'stdio')}
                >
                  {pick(locale, '本地进程 (stdio)', 'Local process (stdio)')}
                </button>
                <button
                  className={`mcp-toggle-btn ${mcpEditor.transport === 'remote' ? 'active' : ''}`}
                  onClick={() => setMcpEditorField('transport', 'remote')}
                >
                  {pick(locale, '远程 HTTP', 'Remote HTTP')}
                </button>
              </div>

              {mcpEditor.transport === 'stdio' ? (
                <>
                  <div className="editor-field">
                    <label>{pick(locale, '命令', 'Command')}</label>
                    <input
                      className="editor-input"
                      value={mcpEditor.command}
                      onChange={(e) => setMcpEditorField('command', e.target.value)}
                      placeholder="npx"
                    />
                  </div>
                  <div className="editor-field">
                    <label>{pick(locale, '参数', 'Arguments')}</label>
                    <input
                      className="editor-input"
                      value={mcpEditor.args}
                      onChange={(e) => setMcpEditorField('args', e.target.value)}
                      placeholder="-y @amap/amap-maps-mcp-server"
                    />
                  </div>
                  <div className="editor-field">
                    <label>{pick(locale, '工作目录 (可选)', 'Working directory (optional)')}</label>
                    <input
                      className="editor-input"
                      value={mcpEditor.cwd}
                      onChange={(e) => setMcpEditorField('cwd', e.target.value)}
                      placeholder="/workspace"
                    />
                  </div>
                  <div className="editor-field">
                    <label>{pick(locale, '环境变量 (每行 KEY=VALUE)', 'Environment variables (KEY=VALUE per line)')}</label>
                    <textarea
                      className="editor-textarea"
                      value={mcpEditor.env}
                      onChange={(e) => setMcpEditorField('env', e.target.value)}
                      placeholder={'AMAP_MAPS_API_KEY=your_key_here\nOTHER_VAR=value'}
                      rows={4}
                    />
                  </div>
                </>
              ) : (
                <>
                  <div className="editor-field">
                    <label>{pick(locale, '服务器 URL', 'Server URL')}</label>
                    <input
                      className="editor-input"
                      value={mcpEditor.url}
                      onChange={(e) => setMcpEditorField('url', e.target.value)}
                      placeholder="http://localhost:3001/mcp"
                    />
                  </div>
                  <div className="editor-field">
                    <label>{pick(locale, 'HTTP 头 (每行 KEY=VALUE)', 'HTTP headers (KEY=VALUE per line)')}</label>
                    <textarea
                      className="editor-textarea"
                      value={mcpEditor.headers}
                      onChange={(e) => setMcpEditorField('headers', e.target.value)}
                      placeholder={'Authorization=Bearer your_token\nX-Api-Key=key'}
                      rows={4}
                    />
                  </div>
                </>
              )}

              <div className="editor-actions">
                <button className="editor-btn editor-btn-cancel" onClick={() => setMcpEditorOpen(false)}>
                  {pick(locale, '取消', 'Cancel')}
                </button>
                <button className="editor-btn editor-btn-save" onClick={saveMcpServer}>
                  {pick(locale, '保存', 'Save')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── MCP JSON editor ── */}
      {mcpJsonEditorOpen && (
        <div className="editor-overlay" onClick={() => setMcpJsonEditorOpen(false)}>
          <div className="editor-panel mcp-json-editor-panel" onClick={(event) => event.stopPropagation()}>
            <div className="editor-header">
              <h3>{pick(locale, '手动配置 (JSON)', 'Manual Config (JSON)')}</h3>
              <button className="editor-close" onClick={() => setMcpJsonEditorOpen(false)}>
                {pick(locale, '关闭', 'Close')}
              </button>
            </div>
            <div className="editor-body">
              <p className="editor-hint">
                {pick(
                  locale,
                  '请从 MCP Servers 的介绍页面复制配置 JSON（优先使用 NPX 或 UVX 配置），并粘贴到输入框中。',
                  'Copy the configuration JSON from MCP Servers (prefer NPX or UVX) and paste it here.',
                )}
              </p>
              <div className="editor-field">
                <textarea
                  className="editor-textarea mcp-json-textarea"
                  value={mcpJsonContent}
                  onChange={(e) => setMcpJsonContent(e.target.value)}
                  placeholder={JSON.stringify({
                    mcpServers: {
                      "example-server": {
                        "command": "npx",
                        "args": ["-y", "mcp-server-example"]
                      }
                    }
                  }, null, 2)}
                  rows={20}
                />
              </div>
              <p className="editor-footer-hint">
                <span className="hint-icon">⚠️</span>
                {pick(
                  locale,
                  '配置前请确认来源，甄别风险',
                  'Verify the source before configuring, be aware of risks',
                )}
              </p>
              <div className="editor-actions">
                <button className="editor-btn editor-btn-cancel" onClick={() => setMcpJsonEditorOpen(false)}>
                  {pick(locale, '取消', 'Cancel')}
                </button>
                <button className="editor-btn editor-btn-save" onClick={saveMcpJsonConfig}>
                  {pick(locale, '确认', 'Confirm')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Delete confirmation ── */}
      {confirmDelete && (
        <div className="confirm-overlay" onClick={() => setConfirmDelete(null)}>
          <div className="confirm-dialog" onClick={(event) => event.stopPropagation()}>
            <h3>{pick(locale, '确认删除', 'Confirm delete')}</h3>
            <p>
              {pick(
                locale,
                `确定要删除角色 "${confirmDelete}" 吗？这个操作无法撤销。`,
                `Are you sure you want to delete role "${confirmDelete}"? This cannot be undone.`,
              )}
            </p>
            <div className="confirm-actions">
              <button className="confirm-btn confirm-btn-cancel" onClick={() => setConfirmDelete(null)}>
                {pick(locale, '取消', 'Cancel')}
              </button>
              <button className="confirm-btn confirm-btn-delete" onClick={() => handleDelete(confirmDelete)}>
                {pick(locale, '删除', 'Delete')}
              </button>
            </div>
          </div>
        </div>
      )}

      {confirmDeleteMcp && (
        <div className="confirm-overlay" onClick={() => setConfirmDeleteMcp(null)}>
          <div className="confirm-dialog" onClick={(event) => event.stopPropagation()}>
            <h3>{pick(locale, '确认删除', 'Confirm delete')}</h3>
            <p>
              {pick(
                locale,
                `确定要移除 MCP 服务器 "${confirmDeleteMcp}" 吗？这个操作无法撤销。`,
                `Are you sure you want to remove MCP server "${confirmDeleteMcp}"? This cannot be undone.`,
              )}
            </p>
            <div className="confirm-actions">
              <button className="confirm-btn confirm-btn-cancel" onClick={() => setConfirmDeleteMcp(null)}>
                {pick(locale, '取消', 'Cancel')}
              </button>
              <button className="confirm-btn confirm-btn-delete" onClick={() => handleDeleteMcp(confirmDeleteMcp)}>
                {pick(locale, '删除', 'Delete')}
              </button>
            </div>
          </div>
        </div>
      )}

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
