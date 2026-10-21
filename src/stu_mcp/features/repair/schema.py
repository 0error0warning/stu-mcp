"""Observed school protocol, selectors and DOM extraction; no workflow decisions."""

ROOT = "https://repair.stu.edu.cn/"
LIST_URL = ROOT + "student.aspx"
STATUSES = {"等待处理", "已分派任务", "已派人维修", "已完成", "拒绝处理", "已接受用户评价"}
LIST_COLUMNS = ("单据编号", "报修标题", "报修时间", "处理状态", "操作")
REPAIR_HOME = ROOT
REPAIR_FORM = REPAIR_HOME + "student_applybill.aspx"
VERIFIED_ON = "2026-10-19"
BUILDINGS = (
    "德馨书院楼", "弘毅书院楼", "继续教育学院(蓬州分校)", "交流公寓H座", "交流公寓I座",
    "敬一书院C楼", "敬一书院D楼", "明德书院E楼", "明德书院F楼",
    "桑浦山校区学生宿舍B栋", "桑浦山校区学生宿舍C栋", "桑浦山校区学生宿舍D栋",
    "桑浦山校区学生宿舍E栋", "桑浦山校区学生宿舍F栋", "思源书院楼", "修远书院B楼",
    "研究生院A楼", "研究生院L座", "研究生院Y座", "知行书院楼", "至诚书院楼",
    "住宿书院二期1栋", "住宿书院二期2栋", "住宿书院二期3栋",
)
FIELDS = {
    "name": "姓名", "college": "学院", "building": "所在楼座（完整选项）", "location": "发生地址",
    "phone": "联系电话", "title": "报修标题", "description": "详细描述（800字内）",
    "visit_date": "预约日期 YYYY-MM-DD", "visit_start": "开始时间（8:00–18:00整点）",
    "visit_end": "结束时间（晚于开始时间）",
}
OPTIONAL = {"device", "email"}
SELECT_FIELDS = {"college": "#ddl_department_name", "building": "#ddl_floor",
                 "visit_end": "#DropDownList1", "visit_start": "#ddl_time1"}
TEXT_FIELDS = {"name": "#tb_name", "phone": "#tb_tel", "location": "#tb_happenarea",
               "title": "#tb_title", "device": "#tb_Repair_device_name", "description": "#Detail"}
CAPABILITY = {"scope": "sangpushan_dorm", "draft_and_browser_fill": True,
              "submission_supported": True, "confirmation_required": True, "submission_live_verified": False,
              "transport": "direct", "receipt_verification": "new_list_row_and_matching_detail",
              "network_diagnostic_tool": "diagnose_campus_network",
              "preflight_scope": "service_and_school_sso",
              "read_only_submission_check": True,
              "login": "interactive_temporary_browser",
              "storage": "process_memory_only", "form_verified_on": VERIFIED_ON,
              "native_browser_live_verified": True, "native_browser_verified_on": VERIFIED_ON,
              "native_browser_verification_scope": "shared_adapter_cli_login_fill_readback"}
TIME_EVENTS = {"ddl_time1", "DropDownList1"}
POSTBACK_FIELDS = {"__EVENTTARGET", "__EVENTARGUMENT", "__LASTFOCUS", "__VIEWSTATE",
                   "__VIEWSTATEGENERATOR", "__EVENTVALIDATION", "tb_name", "ddl_department_name",
                   "tb_stu_no", "ddl_sex", "ddl_floor", "tb_tel", "tb_address", "tb_mobil", "tb_email",
                   "tb_title", "tb_happenarea", "tb_happentime", "tb_Repair_device_name",
                   "tb_Repair_device_no", "remLen", "Detail", "tb_bookingtime1", "ddl_time1",
                   "DropDownList1", "tb_bookingtime2", "ddl3", "ddl4", "rbtn_list_agency"}
DIRECT_BROWSER_ARGS = ["--proxy-server=direct://", "--proxy-bypass-list=*"]
SYSTEM_FIELDS = {k for k in POSTBACK_FIELDS if k.startswith("__")} | {"remLen"}
BUSINESS_FIELDS = POSTBACK_FIELDS - SYSTEM_FIELDS
LABELS = {
    "tb_name": "姓名", "ddl_department_name": "学院", "tb_stu_no": "学号", "ddl_sex": "性别",
    "ddl_floor": "所在楼座", "tb_tel": "联系电话", "tb_address": "住址", "tb_mobil": "联系手机",
    "tb_email": "邮箱", "tb_title": "报修标题", "tb_happenarea": "发生地址",
    "tb_happentime": "申请时间（学校生成）",
    "tb_Repair_device_name": "故障设备", "tb_Repair_device_no": "资产编号", "Detail": "详细描述",
    "tb_bookingtime1": "预约日期一", "ddl_time1": "开始时间一", "DropDownList1": "结束时间一",
    "tb_bookingtime2": "预约日期二（空白表示不设置）", "ddl3": "开始时间二", "ddl4": "结束时间二",
    "rbtn_list_agency": "紧急程度",
}
RAW_TO_DRAFT = {"tb_name": "name", "ddl_department_name": "college", "ddl_floor": "building",
                "tb_tel": "phone", "tb_email": "email", "tb_title": "title", "tb_happenarea": "location",
                "Detail": "description", "tb_bookingtime1": "visit_date", "ddl_time1": "visit_start",
                "DropDownList1": "visit_end"}
PAGE_PROBLEM_SCRIPT = """body => {
  if (body.querySelector('input[type=password]')) return 'login_required';
  if (Array.from(body.querySelectorAll('h1,h2')).some(el =>
      /应用程序中的服务器错误|Server Error in .*Application/i.test(el.textContent)))
    return 'source_error';
  return null;
}"""
LIST_SCRIPT = """body => {
  const problem = (""" + PAGE_PROBLEM_SCRIPT + """)(body);
  const text = body.innerText;
  const ids = ['tb_AppBill_ID','tb_AppBill_Title','tb_Appbill_from_Date','tb_Appbill_to_Date'];
  const filtersClear = ids.every(id => body.querySelectorAll('#'+id).length === 1 &&
    body.querySelector('#'+id).value === '') &&
    body.querySelectorAll('#ddl_Appbill_Status').length === 1 &&
    body.querySelector('#ddl_Appbill_Status')?.selectedOptions[0]?.textContent.trim() === '全部';
  const grids = body.querySelectorAll('#DataGrid1'), grid = grids[0];
  const empty = Array.from(body.querySelectorAll('span,p,td,div')).some(el =>
    !el.querySelector('table,input,select') && !el.closest('#DataGrid1') &&
    /^没有任何数据[!！]?$/.test(el.innerText.trim()));
  return {problem, schemaValid: grids.length <= 1,
    heading: text.includes('我的报修单据列表'), filtersClear, empty,
    rows: grid ? Array.from(grid.rows).slice(0,101).map(row =>
      Array.from(row.cells).map(cell => ({text: cell.innerText.trim(),
        links: Array.from(cell.querySelectorAll('a')).map(a => a.getAttribute('href'))}))) : []};
}"""
DETAIL_SCRIPT = """body => {
  const problem = (""" + PAGE_PROBLEM_SCRIPT + """)(body);
  const labels = {'报修人姓名:':'tb_name','所属单位:':'ddl_department_name',
    '学号:':'tb_stu_no','性别:':'ddl_sex','电话:':'tb_tel','住址:':'tb_address',
    '手机:':'tb_mobil','E-MAIL:':'tb_email','报修标题:':'tb_title',
    '发生地址:':'tb_happenarea','发生时间:':'tb_happentime',
    '故障设备名称:':'tb_Repair_device_name','资产编号:':'tb_Repair_device_no',
    '详细描述:':'Detail','我想预约时间:':'appointment','处理状态:':'processing_status'};
  const fields = {}, orders = [];
  for (const row of body.querySelectorAll('table tr')) {
    const cells = Array.from(row.cells);
    // Layout tables may wrap the real table. Never read their aggregate text.
    if (cells.some(cell => cell.querySelector('table'))) continue;
    if (cells.length === 1) {
      const m = cells[0].innerText.trim().match(/^报修单\\s*[(（]\\s*(\\d+)\\s*[)）]$/);
      if (m) orders.push(m[1]);
    }
    for (let i=0; i<cells.length; i++) {
      const source = cells[i].innerText.trim();
      const colon = source.search(/[:：]/);
      if (colon < 0) continue;
      const label = source.slice(0,colon+1).replace(/\\s/g,'').replace(/：/g,':');
      const key = labels[label];
      if (key) {
        const inline = source.slice(colon+1).trim();
        const value = inline || (cells[i+1]?.innerText.trim() || '');
        (fields[key] ||= []).push(value);
        if (!inline && i+1<cells.length) i++;
      }
    }
  }
  const floor = body.querySelectorAll('#ddl_floor');
  const common = body.querySelectorAll('#chk_agency_common');
  const urgent = body.querySelectorAll('#chk_agency_urgency');
  if (floor.length===1) fields.ddl_floor = [floor[0].selectedOptions[0]?.textContent.trim() || ''];
  if (common.length===1 && urgent.length===1 && common[0].checked !== urgent[0].checked)
    fields.rbtn_list_agency = [urgent[0].checked ? '紧急' : '一般'];
  return {problem, orders, fields};
}"""
FORM_SCRIPT = """(form, allowed) => {
      const body = {}, display = {}, unknown = [], controls = {};
      let attachments = false;
      for (const el of form.elements) {
        const name = el.name;
        if (allowed.includes(name)) controls[name] = (controls[name] || 0) + 1;
        if (el.type === 'file') { attachments ||= Boolean(el.files.length); continue; }
        if (name === 'tb_happentime') {
          display[name] = el.value;
          if (!el.disabled) (body[name] ||= []).push(el.value);
          continue;
        }
        if (!name || el.disabled || ['button','submit','reset'].includes(el.type)) continue;
        if (!allowed.includes(name)) { unknown.push(name); continue; }
        if (name.startsWith('__') || name === 'remLen') continue;
        if (['radio','checkbox'].includes(el.type) && !el.checked) continue;
        const values = el.tagName === 'SELECT'
          ? Array.from(el.selectedOptions).map(o => o.value) : [el.value];
        (body[name] ||= []).push(...values);
        display[name] = el.tagName === 'SELECT'
          ? Array.from(el.selectedOptions).map(o => o.textContent.trim()).join('、') : el.value;
      }
      return {action:form.getAttribute('action'), method:form.method,
        body, display, controls, unknown, attachments};
    }"""
