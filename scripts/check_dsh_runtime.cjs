// Run with DSH's Electron in Node mode, or Node against an installed DSH runtime.
// Arguments: runtime node_modules directory, Python executable, empty test directory.
// Uses real Cordis, ToolRuntime and MCP bridge; no model or user profile is loaded.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const [modules, python, scratch] = process.argv.slice(2);
if (!modules || !python || !scratch) throw new Error('runtime, python, scratch are required');
if (!fs.existsSync(scratch) || fs.readdirSync(scratch).length) throw new Error('scratch must be empty');
const { Context } = require(path.join(modules, '@deepseek-ai/cordis'));
const { SystemPrompt } = require(path.join(modules, '@deepseek-ai/dsh-system-prompt'));
const { ToolRuntime } = require(path.join(modules, '@deepseek-ai/dsh-tools'));
const bridge = require(path.join(modules, '@deepseek-ai/dsh-mcp-client'));
const version = require(path.join(modules, '@deepseek-ai/dsh-mcp-client/package.json')).version;

async function run() {
  const ctx = new Context();
  await ctx.plugin(SystemPrompt);
  await ctx.plugin(ToolRuntime);
  try {
    await ctx.plugin(bridge, {
      serverName: 'stu-mcp', transport: 'stdio', command: python,
      args: ['-m', 'stu_mcp', 'serve'], cwd: process.cwd(),
      env: { STU_MCP_HOME: path.join(scratch, 'data'), STU_CHECKIN_HOME: path.join(scratch, 'checkin') },
      toolCallTimeoutMs: 20000, failOnStartupError: true,
      reconnect: { enabled: false },
    });
    const names = [...ctx.tools.view().visible.keys()];
    assert(names.length >= 52);
    assert(names.every(name => name.startsWith('mcp__stu-mcp__')));
    async function call(name, args = {}) {
      const tool = ctx.tools.get('mcp__stu-mcp__' + name);
      assert(tool);
      const result = await tool.execute(args, { signal: AbortSignal.timeout(20000) });
      assert(Array.isArray(result.content));
      assert(result.structuredContent);
      return result.structuredContent;
    }
    const capabilities = await call('get_capabilities');
    assert.equal(capabilities.ok, true);
    assert.equal((await call('get_grades')).status, 'needs_login');
    assert.equal((await call('refresh_source', { source: 'invalid-synthetic-source' })).status, 'invalid_source');
    assert.deepEqual((await call('search_notices')).items, []);
    return { dsh_version: version, stu_version: capabilities.version, tools: names.length };
  } finally {
    await ctx.fiber.dispose();
  }
}

const deadline = setTimeout(() => { console.error('DSH bridge verification timed out'); process.exit(1); }, 60000);
(async () => {
  const first = await run();
  const second = await run();
  assert.deepEqual(second, first);
  console.log(JSON.stringify({ ok: true, ...first, restart_verified: true,
    scope: 'installed DSH bridge and registry; no model turn or desktop UI' }));
})().catch(error => { console.error(error.message); process.exitCode = 1; })
  .finally(() => clearTimeout(deadline));
