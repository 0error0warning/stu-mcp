'use strict';

const { TypertRemoteService, Remote } = require('@deepseek-ai/dsh-typert-protocol');
const PREFIX = 'mcp__stu-mcp__';

// Only these two fixed operations cross the DSH UI boundary. The existing
// official MCP bridge owns the connection, process, tools and credentials.
class StuCampus extends TypertRemoteService {
  static inject = ['tools'];

  constructor(ctx) {
    super(ctx, 'stuCampus');
    this.lifetime = new AbortController();
    ctx.effect(() => () => this.lifetime.abort());
    for (const name of ['status', 'openSetup']) {
      Remote(this[name], {
        kind: 'method', name, static: false, private: false,
        addInitializer: initializer => initializer.call(this),
      });
    }
  }

  async call(name, signal) {
    const tool = this.ctx.tools.get(PREFIX + name);
    if (!tool) return { ok: false, status: 'not_connected', message: '尚未连接 STU MCP。请在宿主运行 stu-mcp connect dsh --apply，再重载 DSH。' };
    const combined = AbortSignal.any([this.lifetime.signal, signal ?? new AbortController().signal, AbortSignal.timeout(20000)]);
    try {
      combined.throwIfAborted();
      const result = await tool.execute({}, { signal: combined });
      combined.throwIfAborted();
      const value = result.structuredContent;
      if (result.isError || !value || typeof value !== 'object') throw new Error('invalid_result');
      return value;
    } catch {
      // Never expose raw transport errors, command lines or credential-bearing logs.
      return { ok: false, status: combined.aborted ? 'cancelled_or_timeout' : 'connection_error', message: '本次连接检查未完成。请刷新重试，或检查 DSH 中的 STU MCP 连接。' };
    }
  }

  async status(signal) {
    const result = await this.call('get_capabilities', signal);
    if (!result.ok) return { ok: false, status: result.status, message: result.message };
    // Project the shared public catalog; do not forward account or source payloads.
    return {
      ok: true, status: 'connected', version: result.version ?? '',
      checkedAt: new Date().toISOString(),
      toolCount: [...this.ctx.tools.view().visible.keys()].filter(name => name.startsWith(PREFIX)).length,
      setupOn: 'mcp_host', transport: result.hosting?.transport ?? 'unknown',
      profiles: (result.capability_catalog?.profiles ?? []).map(profile => ({
        id: profile.configuration_id, label: profile.label,
        state: profile.state?.status ?? 'unknown', message: profile.state?.message ?? '',
        features: (profile.features ?? []).map(feature => feature.label),
      })),
    };
  }

  async openSetup(signal) {
    const result = await this.call('open_setup', signal);
    return { ok: result.ok === true, status: result.status, message: result.message ?? '请在 MCP 宿主完成设置。' };
  }
}

module.exports = StuCampus;
