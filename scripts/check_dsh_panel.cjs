// Run in DSH's Electron Node mode with its node_modules path as the argument.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const modules = process.argv[2];
const { Context, Service } = require(path.join(modules, '@deepseek-ai/cordis'));
const protocol = require(path.join(modules, '@deepseek-ai/dsh-typert-protocol'));
const source = fs.readFileSync(path.join(__dirname, '../integrations/dsh/index.cjs'), 'utf8');
const sandbox = { module: { exports: {} }, require: () => protocol, AbortController, AbortSignal, Date };
vm.runInNewContext(source, sandbox);
const Plugin = sandbox.module.exports;
const calls = [];
let response;
let available = false;
class Tools extends Service {
  constructor(ctx) { super(ctx, 'tools'); }
  get(name) {
    if (!available) return undefined;
    return { execute: async (args, options) => { calls.push({ name, args, signal: options.signal }); return response; } };
  }
  view() { return { visible: new Map([['mcp__stu-mcp__get_capabilities', {}], ['other', {}]]) }; }
}
(async () => {
  const ctx = new Context();
  await ctx.plugin(Tools);
  const fiber = ctx.plugin(Plugin);
  await fiber;
  try {
    const service = ctx.get('stuCampus');
    assert.equal(protocol.remoteMethods(service).map(x => x.method).sort().join(','), 'openSetup,status');
    assert.equal((await service.status()).status, 'not_connected');
    available = true;
    response = { structuredContent: { ok: true, version: 'test', privateSecret: 'DO_NOT_FORWARD',
      capability_catalog: { profiles: [{ configuration_id:'school',label:'学校账号',state:{status:'needs_login'},features:[{label:'课表'}] }] } } };
    const result = await service.status();
    assert.equal(result.ok, true);
    assert.equal(result.toolCount, 1);
    assert.equal(result.profiles[0].features[0], '课表');
    assert(!JSON.stringify(result).includes('DO_NOT_FORWARD'));
    response = { structuredContent: { ok:false,status:'host_setup_required',message:'在宿主配置',url:'SECRET' } };
    assert.equal((await service.openSetup()).status, 'host_setup_required');
    assert(!JSON.stringify(await service.openSetup()).includes('SECRET'));
    response = { content:[{type:'text',text:'raw transport secret'}],isError:true };
    assert.equal((await service.status()).status, 'connection_error');
    assert(!JSON.stringify(await service.status()).includes('raw transport secret'));
    const stopped = new AbortController(); stopped.abort();
    const beforeCancellation = calls.length;
    assert.equal((await service.status(stopped.signal)).status, 'cancelled_or_timeout');
    assert.equal(calls.length, beforeCancellation);
    assert(calls.every(x => Object.keys(x.args).length === 0));
    assert(calls.every(x => /^mcp__stu-mcp__(get_capabilities|open_setup)$/.test(x.name)));
    console.log(JSON.stringify({ok:true,checks:['missing bridge','public projection','setup guidance','error redaction','cancellation','fixed operations','remote markers']}));
  } finally { await ctx.fiber.dispose(); }
})().catch(error => { console.error(error); process.exitCode=1; });
