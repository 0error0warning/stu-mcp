/* Plain JavaScript client artifact: uses the host's React and Slots, no build step. */
window.__ModuleLoader__.load({
  id: 'dsh-stu-mcp',
  factory: require => {
    const React = require('react');
    const h = React.createElement;
    const ID = 'dsh-stu-mcp';
    // Short presentation copy only. Available families and their states still
    // come from the shared MCP catalog; no raw diagnostic prose is rendered.
    const copy = {
      anonymous: { title: '不用登录就能查', summary: '通知活动、服务入口、充电设备、公众号文章、狐友帖子' },
      school: { title: '学校账号', summary: '课表、成绩、考试、作业、日程、宿舍报修' },
      yuketang: { title: '雨课堂', summary: '课程、作业、课程公告' },
      duifene: { title: '对分易', summary: '课程查询、签到助手' },
      smartcard: { title: '一卡通', summary: '卡片余额、消费记录' },
      webvpn: { title: 'WebVPN', summary: '访问 OA 通知' },
      takeout: { title: '外卖（实验）', summary: '查商家和菜单、帮你选餐' },
      local: { title: '其他工具', summary: '待办、课表文件转换、更新与反馈' },
    };
    const labels = {
      not_required: '不用登录', needs_login: '未登录', sessions_saved: '已设置',
      session_saved: '已设置', partially_configured: '部分已设置',
      login_expired: '登录已过期', not_configured: '未设置', configuration_saved: '已设置',
      unknown: '待检查', service_not_started: '未启动', not_logged_in: '未登录',
      paused: '已暂停', monitoring: '监听中', query_error: '查询异常',
      session_invalid: '需重新登录', secure_storage_unavailable: '无法读取设置',
      starting: '正在启动', stopping: '正在停止',
    };
    const setupMessages = {
      settings_opened: '设置页已打开，登录后回来点“刷新”。',
      host_setup_required: '请在运行 STU MCP 的电脑上完成登录设置。',
      local_browser_required: '浏览器未能自动打开，请在电脑上运行 stu-mcp setup。',
      not_connected: '尚未连接，请刷新或重启 DSH。',
      cancelled_or_timeout: '打开设置超时了，请重试。',
      connection_error: '暂时打不开设置，请稍后重试。',
    };
    const css = `
      .stu-campus{font:inherit;color:inherit;box-sizing:border-box;width:100%;height:100%;overflow:auto;padding:28px 24px;max-width:720px;margin:auto}
      .stu-campus *{box-sizing:border-box}.stu-campus h1{font-size:23px;font-weight:650;margin:0;letter-spacing:-.5px}
      .stu-campus p{line-height:1.6;margin:0;color:color-mix(in srgb,currentColor 70%,transparent);font-size:13px}.stu-campus header{padding-bottom:24px}
      .stu-campus .stu-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:8px}
      .stu-campus .stu-status{display:flex;align-items:center;gap:6px;font-size:12px;white-space:nowrap}
      .stu-campus .stu-dot{width:6px;height:6px;border-radius:50%;background:currentColor;opacity:.45}.stu-campus .stu-connected{background:#39a56b;opacity:1}
      .stu-campus .stu-actions{display:flex;gap:8px;margin-top:18px}.stu-campus button{font:inherit;font-size:13px;cursor:pointer;border:1px solid color-mix(in srgb,currentColor 16%,transparent);border-radius:7px;padding:8px 13px;color:inherit;background:transparent;transition:background .15s,opacity .15s}
      .stu-campus button:hover{background:color-mix(in srgb,currentColor 7%,transparent)}.stu-campus button:focus-visible,.stu-campus summary:focus-visible{outline:2px solid #5579ef;outline-offset:3px}.stu-campus button:disabled{cursor:wait;opacity:.5}
      .stu-campus .stu-primary{background:#4d6bfe;color:white;border-color:transparent}.stu-campus .stu-primary:hover{background:#3c58df}
      .stu-campus section{border-top:1px solid color-mix(in srgb,currentColor 12%,transparent);padding:19px 0}.stu-campus h2{font-size:13px;margin:0 0 10px;font-weight:600}.stu-campus h3{font-size:14px;margin:0 0 3px;font-weight:550}
      .stu-campus .stu-account{display:flex;gap:16px;align-items:center;justify-content:space-between;padding:11px 0}.stu-campus .stu-account:first-child{padding-top:0}.stu-campus .stu-account:last-child{padding-bottom:0}.stu-campus .stu-state{font-size:12px;opacity:.7;white-space:nowrap;flex-shrink:0}
      .stu-campus details{border-top:1px solid color-mix(in srgb,currentColor 12%,transparent);padding:16px 0}.stu-campus summary{font-size:13px;cursor:pointer;user-select:none;width:fit-content}.stu-campus .stu-detail{padding-top:15px}.stu-campus .stu-detail p+p{margin-top:8px}
      .stu-campus .stu-meta{font-size:12px}.stu-campus .stu-message{padding-top:12px;font-size:13px;line-height:1.6}
      @media(max-width:480px){.stu-campus{padding:22px 18px}.stu-campus h1{font-size:21px}.stu-campus .stu-account{gap:10px}}
      @media(prefers-reduced-motion:reduce){.stu-campus button{transition:none}}
    `;
    function Icon({ size = 20 }) {
      return h('svg', { width:size,height:size,viewBox:'0 0 24 24',fill:'none',stroke:'currentColor',strokeWidth:1.7,'aria-hidden':true },
        h('path',{d:'M3 9 12 4l9 5-9 5-9-5Zm4 3v6c3 2 7 2 10 0v-6M21 9v8'}));
    }
    function Panel({ readStatus, openSetup }) {
      const [data,setData] = React.useState(null);
      const [busy,setBusy] = React.useState('status');
      const [message,setMessage] = React.useState('');
      const active = React.useRef(null);
      async function run(kind) {
        active.current?.abort();
        const controller = new AbortController();
        active.current = controller;
        setBusy(kind); setMessage('');
        try {
          const result = await (kind === 'status' ? readStatus : openSetup)(controller.signal);
          if (controller.signal.aborted) return;
          if (kind === 'status') setData(result);
          else setMessage(setupMessages[result.status] ?? '暂时打不开设置，请稍后重试。');
        } catch {
          if (!controller.signal.aborted) {
            if (kind === 'status') setData({ok:false});
            setMessage('暂时连接不上，请刷新或重启 DSH。');
          }
        } finally { if (!controller.signal.aborted) setBusy(''); }
      }
      React.useEffect(() => { run('status'); return () => active.current?.abort(); }, []);
      const connected = data?.ok === true;
      const profiles = data?.profiles ?? [];
      const byId = new Map(profiles.map(profile => [profile.id, profile]));
      const accounts = ['school','yuketang','duifene','smartcard'].map(id => byId.get(id)).filter(Boolean);
      const extras = profiles.filter(profile => !['anonymous','school','yuketang','duifene','smartcard'].includes(profile.id));
      function accountRow(profile) {
        const text = copy[profile.id] ?? { title:profile.label,summary:'在设置页查看可用功能' };
        return h('div',{key:profile.id,className:'stu-account'},
          h('div',null,h('h3',null,text.title),h('p',null,text.summary)),
          profile.state !== 'not_required' && h('span',{className:'stu-state'},labels[profile.state]??'待检查'));
      }
      return h('div',{className:'stu-campus'},
        h('style',null,css),
        h('header',null,
          h('div',{className:'stu-heading'},h('h1',null,'STU MCP'),
            h('div',{className:'stu-status','aria-live':'polite'},h('span',{className:'stu-dot '+(connected?'stu-connected':'')}),
              busy === 'status' ? '连接中…' : connected ? '已连接' : '未连接')),
          h('p',null,'查校园信息，直接在对话里提问。'),
          h('div',{className:'stu-actions'},
            h('button',{className:'stu-primary',disabled:!!busy || !connected,onClick:()=>run('setup')},busy==='setup'?'正在打开…':'登录与设置'),
            h('button',{disabled:!!busy,onClick:()=>run('status')},'刷新')),
          !connected && data && !message && h('p',{className:'stu-message'},'暂时连接不上，请刷新或重启 DSH。'),
          message && h('div',{className:'stu-message',role:'status'},message)),
        connected && h(React.Fragment,null,
          byId.has('anonymous') && h('section',null,h('h2',null,copy.anonymous.title),h('p',null,copy.anonymous.summary)),
          accounts.length > 0 && h('section',null,h('h2',null,'登录后使用'),...accounts.map(accountRow)),
          extras.length > 0 && h('details',null,h('summary',null,'更多功能'),h('div',{className:'stu-detail'},...extras.map(accountRow)))),
        data && h('details',null,h('summary',null,'连接信息'),h('div',{className:'stu-detail'},
          connected ? h(React.Fragment,null,
            h('p',{className:'stu-meta'},`版本 ${data.version || '未知'} · ${data.toolCount} 个工具 · ${new Date(data.checkedAt).toLocaleTimeString()} 检查`),
            h('p',{className:'stu-meta'},'“已设置”表示保存过登录信息。过期时，查询会提示重新登录。'))
          : h('p',{className:'stu-meta'},data.message ?? 'DSH 服务暂时没有响应。'))));
    }
    return {
      inject: ['slots','sidebarRightTabs','connection'],
      apply(ctx) {
        // The authenticated Connection and Gateway retain DSH's owner/access
        // checks. Source-mode Remote methods have no user-controlled arguments.
        const rpc = async (method, signal) => {
          const response = await ctx.connection.rpc.call('/api',`stuCampus/${method}`,{args:{}},signal);
          if (!response.ok) throw new Error('STU panel request failed');
          return response.value;
        };
        const face = () => ({readStatus:signal=>rpc('status',signal),openSetup:signal=>rpc('openSetup',signal)});
        for (const name of ['main','plugins.bundle.config','sidebar.right.pane.tab']) {
          ctx.effect(()=>ctx.slots.inject(name,()=>ctx.slots.register({name,key:ID,inject:face},Panel)));
        }
        ctx.effect(()=>ctx.slots.inject('sidebar.panellist',()=>ctx.slots.register({
          name:'sidebar.panellist',id:ID,order:30,label:()=> 'STU MCP',
        },Icon)));
        ctx.effect(()=>ctx.sidebarRightTabs.register({
          id:ID,kind:'stu-campus',title:()=> 'STU MCP',
          guide:[{id:'stu-campus',order:30,title:()=> 'STU MCP',description:()=> '校园功能与设置',icon:Icon}],
        }));
      },
    };
  },
});
