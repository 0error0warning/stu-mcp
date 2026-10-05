"use strict";
(() => {
  const token = location.hash.slice(1);
  const feedback = document.getElementById("feedback");
  let initial = true, polling = null;
  const names = {not_required:"无需账号", needs_login:"尚未登录", session_saved:"会话已保存", login_expired:"登录已过期", secure_storage_unavailable:"系统密钥库不可用", session_invalid:"请重新登录"};
  function say(message, error=false) { feedback.textContent=message; feedback.className=error?"error":""; }
  async function api(path, data) {
    const res = await fetch(path, {method:data===undefined?"GET":"POST", headers:{"X-STU-Setup":token,"Content-Type":"application/json"}, body:data===undefined?undefined:JSON.stringify(data)});
    const result=await res.json();
    if (!res.ok || result.ok===false) throw new Error(result.message || "设置页已失效，请从 stu-mcp setup 重新打开。");
    return result;
  }
  function element(tag, text, className) { const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node; }
  async function action(button, path, data, message) {
    button.disabled=true;
    try {const result=await api(path,data);say(message || result.message || "操作已完成。");await load();return result;}
    catch(error){say(error.message,true);return null;}
    finally{button.disabled=false;}
  }
  function button(text, kind, fn) { const node=element("button",text,kind);node.addEventListener("click",()=>fn(node));return node; }
  async function load() {
    const state=await api("/api/status");
    document.getElementById("version").textContent=state.version;
    const container=document.getElementById("sources");container.replaceChildren();
    for (const source of state.sources) {
      const row=element("div",undefined,"source"), info=element("div");
      info.append(element("h3",source.label),element("p",source.features.join(" · "),"description"));row.append(info);
      const status=source.auth.status;
      const statusBlock=element("div",undefined,"source-state");
      let label=names[status] || status;
      if(source.source==="oa" && status!=="session_saved")label="无需预先登录";
      statusBlock.append(element("span",label,"state"+(source.login_required&&status!=="session_saved"?" pending":"")));
      const fresh=state.freshness.find(f=>f.source===source.source);
      if(fresh)statusBlock.append(element("span",(fresh.success_at?"缓存更新 "+new Date(fresh.success_at).toLocaleString("zh-CN"):"尚未成功刷新")+(fresh.status!=="ok"?" · "+(fresh.status==="partial"?"限定范围 / 部分结果":fresh.status):""),"freshness"));
      else statusBlock.append(element("span",source.source==="oa"?"先尝试公开访问，需要时再配置 WebVPN":"按需刷新，不运行后台任务","freshness"));
      row.append(statusBlock);
      const actions=element("div",undefined,"actions");
      if(source.source!=="public")actions.append(button(source.source==="oa"?"WebVPN 登录":status==="session_saved"?"重新登录":"登录","secondary",async b=>{
        const result=await action(b,"/api/login",{service:source.source},"请在打开的学校页面完成登录。不要把密码发给 agent。");
        if(result&&!polling)polling=setInterval(async()=>{try{await load();}catch(e){say(e.message,true);clearInterval(polling);polling=null;}},3000);
      }));
      actions.append(button("刷新","secondary",b=>action(b,"/api/refresh",{source:source.source},"已获取此来源的最新可读数据；查询时请留意范围和更新时间。")));
      if(status==="session_saved")actions.append(button("退出","secondary forget",b=>action(b,"/api/logout",{service:source.source},"已移除此来源的会话和缓存。")));
      row.append(actions);container.append(row);
    }
    if(initial){document.getElementById("jw-http-compat").checked=state.transport.jw_http_compat;for(const key of ["college","major","entry_year","interests"])document.getElementById(key).value=state.profile[key]||"";if(state.clients.length)document.getElementById("client").value=state.clients[0];initial=false;}
    const running=state.jobs.find(j=>j.status==="running");
    if(polling&&running&&running.phase==="preparing_browser")say("首次使用正在准备登录浏览器。下载完成后会打开学校页面，无需提供任何账密。");
    if(polling&&running&&running.phase==="waiting_for_login")say("请在打开的学校页面完成登录。验证码或扫码也只在学校页面处理。");
    const finished=state.jobs.find(j=>j.status==="finished");
    if(polling&&finished){clearInterval(polling);polling=null;say(finished.result.ok?"登录会话已安全保存，现在可刷新对应来源。":finished.result.message,!finished.result.ok);}
  }
  document.getElementById("client").addEventListener("change",e=>{document.getElementById("connect").textContent=e.target.value==="generic"?"显示接入配置":"保存接入";document.getElementById("generic").hidden=true;});
  document.getElementById("connect").addEventListener("click",async e=>{
    const client=document.getElementById("client").value;
    const result=await action(e.target,"/api/connect",{client},client==="generic"?"将此配置添加到支持本地 stdio MCP 的客户端。":"接入已保存。请重新加载 MCP 或重启客户端，并启用 STU MCP。");
    if(result&&client==="generic"){const pre=document.getElementById("generic");pre.textContent=JSON.stringify(result.config,null,2);pre.hidden=false;}
  });
  document.getElementById("save-profile").addEventListener("click",e=>{const data={};for(const key of ["college","major","entry_year","interests"])data[key]=document.getElementById(key).value;action(e.target,"/api/profile",data,"资料已保存。");});
  document.getElementById("save-transport").addEventListener("click",e=>action(e.target,"/api/transport",{jw_http_compat:document.getElementById("jw-http-compat").checked},"教务选项已保存。需要成绩时，再登录并刷新教务。"));
  load().catch(error=>say(error.message,true));
})();
