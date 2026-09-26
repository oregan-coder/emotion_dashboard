/* 5535 COCKPIT FAST 910 V1: combined bootstrap, honest ready timer, no entrance animation. */
/* P50: allowlisted Chinese view formatting. Original machine fields remain in API diagnostics. */
(function(root){
 'use strict';
 const labels={
  r_pct:'昨日涨停样本当日平均涨幅',p23:'二进三晋级比例',fail_high:'高位连板失败比例',U:'涨停家数',Z:'炸板家数',D:'跌停家数',
  breadth:'题材上涨比例',excess_median_T:'今日题材相对全市场中位数',excess_median_previous:'前日题材相对全市场中位数',
  n1:'其他首板数量',n2:'其他二板数量',n3plus:'三板及以上数量',n:'可比成员数量',rank:'封板平均名次',
  remaining_session_minutes:'封板后剩余交易分钟',open_break_count:'开板次数',seal_amount:'封单金额',circulating_market_cap:'流通市值',
  current:'当日',previous:'前日',date:'日期',trade_date:'交易日期',previous_trade_date:'前一交易日',code:'股票代码',name:'名称',
  score:'得分',known_subtotal:'已算分项小计',value:'数值',status:'状态',count:'数量',members:'成员',
  percentage_points:'百分点',percent:'百分比',fraction:'比例',stocks:'只',minutes:'分钟',times:'次',yuan:'元',ratio:'比例',CNY:'元',
  VALID:'有效',INPUT_PENDING:'输入待核',DATA_PENDING:'数据待核',INPUT_MISSING:'缺少输入',NOT_ENABLED:'正式策略未启用',NOT_APPROVED:'尚未批准',
  FORWARD_RESEARCH:'当日研究快照',RECALCULATED_RESEARCH_REVISION:'数据修复后的独立研究修订',VALUE_READY:'数值可用',
  COMPLETE_RESEARCH:'研究分完整',PARTIAL_RESEARCH:'部分计分项有效',UNKNOWN:'待核',ELIGIBLE:'通过原筛选',EXCLUDED:'按原规则排除',
  SCOPE_VERIFIED_MISSING:'样本范围未核实',CLOSING_VERIFIED_MISSING:'收盘状态未核实',ITEM_EVIDENCE_NOT_VERIFIED:'分项证据未核实',
  ITEM_SOURCE_DATES_MISMATCH_OR_MISSING:'来源日期缺失或不一致',THEME_CONFIRMATION_PENDING:'日期化题材证据待核',
  DATED_THEME_NOT_SELECTED:'缺少当日交易题材定义',MEMBERSHIP_COMPLETE_MISSING:'题材完整成员待补',THEME_CONFIRMED_MISSING:'题材定义待核',
  MEMBERS_LIST_MISSING:'缺少完整成员名单',MEMBER_LIST_DIFFERS_FROM_REFERENCE:'成员与计算引用不一致',
  INPUT_EVIDENCE_PENDING:'输入证据待核',MEMBER_QUOTE_MISSING_OR_INVALID:'成员当日行情缺失或待核',AMBIGUOUS_REMOVAL_NOT_ACCEPTED:'成员剔除依据不充分',
  NO_COMPARABLE_PEER:'没有可比成员',NOT_COMPARABLE_SINGLETON:'没有可比成员',COHORT_MISSING:'缺少前日完整涨停名单',
  FIVE_DAY_INPUT_MISSING:'五个交易日日值尚未齐备',CALENDAR_WARMUP_MISSING:'窗口起点交易日历不足',
  CANDIDATE_NOT_IN_COMPLETE_PRIOR_FIRST_BOARD_SET:'候选不在完整的前日首板名单内',SOURCE_DATE_VERIFIED_MISSING:'来源日期未核实',
  NUMERATOR_DENOMINATOR_REQUIRED:'分子或分母尚未核实',PREVIOUS_TRADE_DATE_VERIFIED_MISSING:'前一交易日未核实'
 };
 const sources={LOCAL_EFFECTIVE_PRIOR_LIMITUP_MEAN:'本地有效昨日涨停样本等权均值',P50_DB_PRIOR_COHORT_MEAN:'数据库核实的昨日涨停样本均值',
 'emotion.yesterday_performance':'数据库中的昨日涨停表现','akshare.stock_zt_pool_em':'东方财富涨停池','883900':'同花顺昨日涨停表现',
 'akshare.tool_trade_date_hist_sina':'新浪交易日历',local:'本地计算',archive:'历史归档',SQLITE_ONLY:'统一数据库',
 baostock:'BaoStock 历史行情',tushare:'Tushare历史行情',ak_em:'东方财富历史行情',ak_tx:'腾讯历史行情',ak_sina:'新浪历史行情'};
 const formulas={A01:'以昨日涨停样本的当日平均涨幅计分，上限8分',A02:'按已发生的二进三晋级比例计分，上限8分',A03:'按高位连板未失败比例计分，上限7分',A04:'涨停家数除以涨停与炸板家数之和，乘4分',A05:'涨停家数除以涨停与跌停家数之和，乘3分',B01:'题材有效成员上涨比例乘10分',B02:'两日题材收益中位数分别超过同日市场中位数，每日6分',B03:'首板、二板、高板人数分加多层共存分，最高18分',C02:'按前日首板封板顺序的平均名次计分；至少两只可比成员',D01:'封板后剩余交易分钟除以240分钟，乘10分',D02:'6分除以开板次数加1',D03:'封单占流通市值比例按原阈值计分，最高6分'};
 function esc(x){return String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
 function human(x){
   if(x==null||x==='')return '待核';const s=String(x);
   if(labels[s])return labels[s];if(sources[s])return sources[s];
   if(/^(\d{6}|\d{8}|\d{4}-\d{2}-\d{2}|[+-]?\d+(?:\.\d+)?%?)$/.test(s))return s;
   if(s.length>180||/[\\/{}<>]|\b[A-Za-z][A-Za-z0-9_]*\b/.test(s))return '其他信息请查看诊断记录';
   return s;
 }
 function text(v,depth){
   depth=depth||0;if(v==null)return '待证据';if(depth>3)return '详细信息见诊断记录';
   if(typeof v==='number')return Number.isFinite(v)?(Number.isInteger(v)?String(v):String(Number(v.toFixed(4)))):'数值异常';
   if(typeof v==='boolean')return v?'是':'否';if(typeof v==='string')return human(v);
   if(Array.isArray(v))return v.length?v.slice(0,12).map(x=>text(x,depth+1)).join('、')+(v.length>12?'；其余详见诊断记录':''):'待证据';
   if(typeof v==='object'){
     const pairs=Object.keys(v).filter(k=>labels[k]||/^[\u3400-\u9fff（）\s]+$/.test(k)).slice(0,10).map(k=>(labels[k]||k)+'：'+text(v[k],depth+1));
     return pairs.length?pairs.join('；'):'详细字段保留于诊断记录';
   }return '待核';
 }
 function issue(s){
   if(!s)return '';s=String(s);if(labels[s])return labels[s];
   if(s.startsWith('INPUT_MISSING:'))return '缺少输入：'+human(s.slice(14));
   if(s.startsWith('UPSTREAM:'))return '上游数据待核';
   const parts=s.replace(/^[A-D]\d{2}:\s*/,'').split(',').map(t=>t.trim()).filter(Boolean);
   if(parts.length>1)return [...new Set(parts.map(issue))].join('；');
   if(parts[0]!==s)return issue(parts[0]);return human(s);
 }
 function pages(width,cardWidth,gap,count){let per=Math.max(1,Math.floor((Math.max(0,width)+gap)/(cardWidth+gap)));return {perPage:per,totalPages:Math.max(1,Math.ceil(count/per)),offset:p=>p*per*(cardWidth+gap)};}
 root.P50UI={esc,text,value:v=>esc(text(v)),human,issue,source:s=>sources[s]||'其他已记录来源（详情见诊断记录）',formula:f=>formulas[f]||'按原规则计算，详细公式见诊断记录',pages};
 if(typeof module==='object'&&module.exports)module.exports=root.P50UI;
})(typeof globalThis==='object'?globalThis:this);

/* ============================================================
   A股打板情绪仪表盘 V3.1.1
   前端渲染脚本
   ============================================================ */

(function () {

  'use strict';

  // ---------- A股配色 ----------
  var C = {
    up: '#f6465d',
    down: '#60a5fa',
    gold: '#f0b90b',
    blue: '#3b82f6',
    text: '#e6e9f0',
    muted: '#8b93a7',
    line: '#232c40',
    grid: '#1c2333',
    panel: '#131826',
    gray: '#6b7280'
  };

  var charts = [];

  function $(id) { return document.getElementById(id); }

  function fmtDate(d) {
    if (!d) return '--';
    var s = String(d).replace(/\D/g, '');
    if (s.length !== 8) return d;
    return s.slice(0, 4) + '-' + s.slice(4, 6) + '-' + s.slice(6, 8);
  }

  function fmtShort(d) {
    var s = String(d).replace(/\D/g, '');
    if (s.length !== 8) return d;
    return s.slice(4, 6) + '-' + s.slice(6, 8);
  }

  function fmtNum(v) {
    var n = Number(v);
    if (!hasNumericValue(v)) return '待证据';
    return String(Math.round(n));
  }

  function fmtPct(v) {
    var n = Number(v);
    if (!hasNumericValue(v)) return '待证据';
    return n.toFixed(2) + '%';
  }

  function hasNumericValue(v) {
    return (typeof v === 'number' || (typeof v === 'string' && v.trim() !== ''))
      && Number.isFinite(Number(v));
  }

  function initChart(id) {
    var el = $(id);
    if (!el) return null;
    if (typeof echarts === 'undefined') throw new Error('图表依赖 ECharts 未加载');
    var chart = echarts.getInstanceByDom ? echarts.getInstanceByDom(el) : null;
    if (!chart) chart = echarts.init(el);
    if (charts.indexOf(chart) < 0) charts.push(chart);
    if (!chart.__5535FastSetOption) {
      var originalSetOption = chart.setOption.bind(chart);
      chart.setOption = function (option) {
        if (option && typeof option === 'object') {
          option.animation = false; option.animationDuration = 0; option.animationDurationUpdate = 0;
        }
        return originalSetOption.apply(null, arguments);
      };
      chart.__5535FastSetOption = true;
    }
    // Replay must replace the previous state (including empty-state graphics).
    chart.clear();
    return chart;
  }

  function stageClass(stage) {
    var s = String(stage || '');
    if (/高潮|活跃|加速/.test(s)) return 'hot';
    if (/冰点|退潮/.test(s)) return 'cold';
    if (/试错|启动|主升|扩张/.test(s)) return 'gold';
    return '';
  }

  // ============================================================
  // 今日情绪总览
  // ============================================================

  function renderEmotionScore(emotion) {
    // P03A: score为null时显示"待证据"，不默认给0
    var score = emotion.score;
    var el = $('emotionScore');
    var wave = $('emotionWave');
    if (el) {
      if (!hasNumericValue(score)) {
        el.textContent = '待证据';
        el.style.color = '#faad14';
        if (wave) wave.style.setProperty('--fill', '0%');
      } else {
        var s = Number(score);
        el.textContent = s.toFixed(0);
        el.style.color = '';
        if (wave) wave.style.setProperty('--fill', Math.max(0, Math.min(100, s)) + '%');
      }
    }
    // P03A: 显示数据状态和缺失字段
    var statusEl = $('emotionStatus');
    if (statusEl) {
      var parts = [];
      if (emotion.status === 'DATA_PENDING') {
        parts.push('数据待补充: ' + (emotion.missing_fields || []).join(', '));
      }
      if (emotion.score_status) {
        parts.push('状态: ' + emotion.score_status);
      }
      if (hasNumericValue(emotion.snapshot_score)) {
        parts.push('原快照对照: ' + Number(emotion.snapshot_score).toFixed(0));
      }
      statusEl.textContent = parts.join(' · ');
      statusEl.style.display = parts.length ? 'block' : 'none';
    }
  }

  // ============================================================
  // 市场广度
  // ============================================================

  function renderMarket(market) {
    var note = '';
    if (market.source === 'LEGULEGU' && market.scope === 'PROVIDER_NATIVE') {
      note = '来源：乐咕 · 原生口径（未按本地ST/新股60日重算）' +
        (market.as_of ? ' · 统计时间 ' + String(market.as_of) : '');
    } else if (market.source || market.scope) {
      note = '归档来源：' + String(market.source || '未标注') + ' · ' + String(market.scope || '原记录口径');
    }
    var label = $('marketSourceNote');
    if (!label && $('marketStats')) {
      label = document.createElement('div'); label.id = 'marketSourceNote';
      label.style.cssText = 'font-size:11px;line-height:1.6;color:#8b93a7;margin-top:6px;overflow-wrap:anywhere';
      $('marketStats').parentNode.appendChild(label);
    }
    if (label) { label.textContent = note; label.hidden = !note; }
    var chart = initChart('marketChart');
    if (!chart) return;

    if (![market.up, market.down, market.flat].every(hasNumericValue)) {
      chart.clear();
      chart.setOption({graphic:{type:'text',left:'center',top:'middle',style:{text:'市场广度待证据',fill:C.muted}}});
      $('marketStats').textContent = market.source === 'LEGULEGU' ? '乐咕统计未通过日期/时点/字段检查；不回退全市场抓取' : '未知成员不能作为平盘或0家';
      return;
    }
    var data = [
      { value: Number(market.up) || 0, name: '上涨', itemStyle: { color: C.up } },
      { value: Number(market.down) || 0, name: '下跌', itemStyle: { color: C.down } },
      { value: Number(market.flat) || 0, name: '平盘', itemStyle: { color: C.gray } }
    ].filter(function (d) { return d.value > 0; });

    chart.setOption({
      tooltip: { trigger: 'item', formatter: '{b}: {c} 家 ({d}%)' },
      legend: { bottom: 0, icon: 'circle', textStyle: { color: C.muted, fontSize: 12 } },
      series: [{
        type: 'pie',
        radius: ['52%', '76%'],
        center: ['50%', '42%'],
        itemStyle: { borderColor: C.panel, borderWidth: 2 },
        label: { show: true, formatter: '{b}\n{c}', color: C.text, fontSize: 12, lineHeight: 16 },
        labelLine: { length: 8, length2: 6, lineStyle: { color: C.line } },
        data: data
      }]
    });

    $('marketStats').innerHTML =
      '上涨 <b class="up">' + fmtNum(market.up) + '</b>' +
      '　下跌 <b class="down">' + fmtNum(market.down) + '</b>' +
      '　平盘 <b>' + fmtNum(market.flat) + '</b>';
  }

  // ============================================================
  // 涨停生态
  // ============================================================

  // LIMIT_ECOLOGY_TODAY_PREVIOUS_V1 BEGIN
  function priorDownFromHistory(history, previousDate) {
    var target = String(previousDate || '').replace(/-/g, '');
    if (!/^\d{8}$/.test(target)) return null;
    var rows = Array.isArray(history) ? history : [];
    for (var i = rows.length - 1; i >= 0; i--) {
      var row = rows[i] || {};
      if (String(row.date || '').replace(/-/g, '') !== target) continue;
      var value = row.limit_down_count;
      return hasNumericValue(value) && Number(value) >= 0 && Number.isInteger(Number(value)) ? Number(value) : null;
    }
    return null;
  }
  function renderLimit(limit, smash, history, previousDate) {
    limit = limit || {};
    smash = smash || {};
    function countText(value) {
      return hasNumericValue(value) && Number(value) >= 0 && Number.isInteger(Number(value))
        ? String(Number(value)) : '--';
    }
    function titleText(value) {
      return String(value).replace(/[&<>"']/g, function (c) {
        return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
      });
    }
    var priorDown = limit.prev_down;
    var priorDownSource = '原快照';
    if (['DATA_PENDING', 'SOURCE_ERROR', 'INVALID', 'CONFLICT'].indexOf(limit.prev_down_status) >= 0) {
      priorDown = null;
    }
    if (countText(priorDown) === '--' && limit.prev_down_status !== 'CONFLICT' && limit.prev_down_status !== 'INVALID') {
      var historicalDown = priorDownFromHistory(history, limit.prev_down_date || previousDate);
      if (historicalDown !== null) {
        priorDown = historicalDown;
        priorDownSource = '已保存的前一交易日历史';
      }
    }
    var yesterday = '昨日指前一交易日' + ((limit.prev_down_date || previousDate) ? '（' + fmtDate(limit.prev_down_date || previousDate) + '）' : '');
    var downTip = yesterday + '；' + (countText(priorDown) !== '--'
      ? priorDownSource + '跌停家数，0家正常显示。'
      : '该日跌停统计尚未取得可用记录，暂显示--，不按0家处理。');
    var sealRate = hasNumericValue(limit.seal_rate) ? Number(limit.seal_rate) : null;
    var tiles = [
      { num: countText(limit.up) + ' / ' + countText(limit.prev_up), cls: 'up', label: '涨停(今/昨)', tip: '左侧为所选交易日，右侧为原接口中的昨日涨停家数。' },
      { num: countText(limit.down) + ' / ' + countText(priorDown), cls: 'down', label: '跌停(今/昨)', tip: downTip },
      { num: fmtPct(sealRate), cls: 'gold', label: '昨日涨停续板占比' },
      { num: fmtPct(smash.break_rate), cls: 'muted', label: '高位晋级失败率' }
    ];
    var host = $('limitTiles');
    if (!host) return;
    host.innerHTML = tiles.map(function (t) {
      return '<div class="tile"' + (t.tip ? ' title="' + titleText(t.tip) + '"' : '') + '><div class="t-num ' + t.cls + '">' + t.num +
        '</div><div class="t-label">' + t.label + '</div></div>';
    }).join('');
    host.setAttribute('data-prev-down-date', limit.prev_down_date || '');
    host.setAttribute('data-prev-down-value', countText(priorDown));
  }
  // LIMIT_ECOLOGY_TODAY_PREVIOUS_V1 END

  // ============================================================
  // 连板梯队
  // ============================================================

  function renderLadder(ladder, smash) {
    var chart = initChart('ladderChart');
    if (!chart) return;

    // 固定1-8板，为更高板预留空间
    var MAX_BOARD = 8;
    var countMap = {};
    (ladder || []).forEach(function (x) {
      countMap[Number(x.board)] = Number(x.count) || 0;
    });

    var rates = (smash && smash.rates) || {};
    // 晋级率放在目标板数标签下：1进2→2板，2进3→3板，...
    var rateMap = {
      2: rates.rate12,
      3: rates.rate23,
      4: rates.rate34,
      5: rates.rate45,
      6: rates.rate56,
      7: rates.rate67,
      8: rates.rate78
    };

    var labels = [];
    var counts = [];
    for (var b = 1; b <= MAX_BOARD; b++) {
      labels.push(b === 1 ? '首板' : b + '板');
      counts.push(countMap[b] || 0);
    }

    chart.setOption({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: function (ps) {
          var p = ps[0];
          var idx = p.dataIndex;
          var board = idx + 1;
          var rate = rateMap[board];
          var rateTxt = board < 2 ? '' : '（晋级率 ' +
            (hasNumericValue(rate) ? Number(rate).toFixed(2) + '%' : '未知') + '）';
          return p.name + ': ' + p.value + ' 只' + rateTxt;
        }
      },
      grid: { left: 42, right: 18, top: 22, bottom: 32 },
      xAxis: {
        type: 'category',
        data: labels,
        axisLine: { lineStyle: { color: C.line } },
        axisTick: { show: false },
        axisLabel: {
          color: C.muted,
          fontSize: 11,
          formatter: function (val, idx) {
            var board = idx + 1;
            var rate = rateMap[board];
            if (board < 2) return val;
            return val + '\n(' + (hasNumericValue(rate) ? Number(rate).toFixed(1) + '%' : '未知') + ')';
          }
        }
      },
      yAxis: {
        type: 'value',
        minInterval: 1,
        splitLine: { lineStyle: { color: C.grid } },
        axisLabel: { color: C.muted }
      },
      series: [{
        type: 'bar',
        barWidth: '30%',
        itemStyle: {
          borderRadius: [5, 5, 0, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: C.up },
            { offset: 1, color: '#7c1d2e' }
          ])
        },
        label: { show: true, position: 'top', color: C.text, fontSize: 12, fontWeight: 600 },
        data: counts
      }]
    });

    var hbEl = $('leaderLine');
    if (hbEl) hbEl.style.display = 'none';
  }

  // ============================================================
  // 砸盘情绪
  // ============================================================

  function rateColor(v) {
    if (v >= 50) return C.up;
    if (v >= 30) return '#ff8a5c';
    if (v >= 15) return C.gold;
    return C.blue;
  }

  function smashDisplayState(smash) {
    var state=(smash || {}).calculation_state || {};
    if (state.display_label) return state;
    return {display_label: (smash || {}).status || '待证据', explanation: '',
      state: hasNumericValue((smash || {}).score) ? 'SCORE_PRESENT' : 'INPUTS_PENDING'};
  }

  // SMASH_PANEL_30D_NO_SHADOW_V1 BEGIN
  var SMASH_PANEL_ZOOM=null;

  function renderSmashTrend(smash, smashHistory) {
    var chart = initChart('smashTrend');
    if (!chart) return;
    var rows = Array.isArray(smashHistory) ? smashHistory : [];
    var dates = rows.map(function (x) { return fmtShort(x.date); });
    var marked=rows.some(function(x){return x.history_view_schema === '5535_SMASH_HISTORY_COMPONENT_VIEW_V1';});
    var scores=rows.map(function(x){
      var v=x.history_view_schema === '5535_SMASH_HISTORY_COMPONENT_VIEW_V1' ? x.current_formula_score : x.smash_score;
      if(!hasNumericValue(v)) {
        v = x.pre_dynamic_saved_score != null ? x.pre_dynamic_saved_score
           : (x.old_selected_smash_score != null ? x.old_selected_smash_score : x.smash_score);
      }
      return hasNumericValue(v) ? Number(v) : null;
    });
    var archived=rows.map(function(x){return hasNumericValue(x.archive_smash_score) ? Number(x.archive_smash_score) : null;});
    var boards=rows.map(function(x){
      var v=x.history_view_schema === '5535_SMASH_HISTORY_COMPONENT_VIEW_V1' ? x.highest_board_display : x.highest_board;
      return hasNumericValue(v) ? Number(v) : null;
    });
    var note=$('smashHistorySourceNote'), host=$('smashTrend');
    if (!note && host && host.parentNode) {
      note=document.createElement('div'); note.id='smashHistorySourceNote';
      note.style.cssText='font-size:12px;color:var(--muted);line-height:1.5;padding:4px 0 8px';
      host.parentNode.insertBefore(note,host.nextSibling);
    }
    if (note) note.textContent=marked ? '仅保留一条砸盘分曲线：实心点为按已确认规则计算的分数，空心点为同日历史原值（未重算）。悬浮查看来源；缺值不补0，最高板独立显示。' : '历史数据按当前接口原值显示；空值不补0。';
    if (!dates.length) {
      SMASH_PANEL_ZOOM=null;
      if(chart.__smash15ZoomHandler && chart.off)chart.off('datazoom',chart.__smash15ZoomHandler);
      if(chart.clear)chart.clear();
      if(host && host.setAttribute){host.setAttribute('data-window-count','0');host.setAttribute('data-history-count','0');host.setAttribute('data-window-start','');host.setAttribute('data-window-end','');}
      chart.setOption({graphic:{type:'text',left:'center',top:'middle',style:{text:'数据库中暂无可读取的砸盘历史',fill:C.muted,fontSize:14}}});
      return;
    }
    var scoreOrigins=[];
    var scorePoints=scores.map(function(v,i){
      var computed=hasNumericValue(v),archive=!computed && hasNumericValue(archived[i]);
      scoreOrigins.push(computed?'已确认规则计算':archive?'历史原值（未按现行规则重算）':'缺少可用分数');
      return {value:computed?v:archive?archived[i]:null,symbol:archive?'emptyCircle':'circle'};
    });
    var series=[{
      name:'砸盘分',type:'line',smooth:false,connectNulls:false,
      symbol:'circle',symbolSize:7,data:scorePoints,itemStyle:{color:C.gold},lineStyle:{width:3,color:C.gold}
    }];
    series.push({name:'最高板',type:'line',smooth:true,connectNulls:false,yAxisIndex:1,
      symbol:'diamond',symbolSize:9,data:boards,itemStyle:{color:C.blue},lineStyle:{width:2,type:'dashed',color:C.blue}});
    var total=dates.length,zoomKey=rows.map(function(x){return String(x.date||'');}).join('|');
    var zoomLeft=Math.max(0,total-15),zoomRight=total-1;
    if(SMASH_PANEL_ZOOM && SMASH_PANEL_ZOOM.key===zoomKey){
      zoomLeft=SMASH_PANEL_ZOOM.start;zoomRight=SMASH_PANEL_ZOOM.end;
    }
    function markSmashWindow(a,b){
      if(host && host.setAttribute){
        host.setAttribute('data-smash-window-version','30D_NO_SHADOW_V1');
        host.setAttribute('data-window-start',String(rows[a].date||''));
        host.setAttribute('data-window-end',String(rows[b].date||''));
        host.setAttribute('data-window-count',String(b-a+1));
        host.setAttribute('data-history-count',String(total));
      }
    }
    markSmashWindow(zoomLeft,zoomRight);
    // Do not accumulate listeners when the original dashboard refreshes.
    if(chart.__smash15ZoomHandler && chart.off)chart.off('datazoom',chart.__smash15ZoomHandler);
    chart.setOption({
      tooltip:{trigger:'axis',confine:true,backgroundColor:C.panel,borderColor:C.line,textStyle:{color:C.text},extraCssText:'max-width:520px;white-space:normal;line-height:1.65',formatter:function(ps){
        if(!ps || !ps.length) return '';
        var idx=ps[0].dataIndex,row=rows[idx]||{},lines=[];
        ps.forEach(function(p){
          var txt=!hasNumericValue(p.value)?'未生成':p.seriesName==='最高板'?Number(p.value)+'板':Number(p.value).toFixed(2)+'分';
          lines.push((p.marker||'')+esc(p.seriesName)+'：'+txt);
        });
        lines.push('砸盘分来源：'+esc(scoreOrigins[idx]));
        var state=row.calculation_state||{},h=row.highest_board_evidence||{},a=row.archive_score_evidence||{};
        if(state.explanation) lines.push(esc(state.explanation));
        if(a.value!==null && a.value!==undefined) {
          var origin=(a.origins||[])[0]||{};
          lines.push('历史原值来源：'+(origin.source_path ? '同日SQLite归档（未重算）' : '同日SQLite归档'));
        }
        if(a.status==='CONFLICT') lines.push('同优先级归档分数有冲突，未自动选择。');
        var stock=marked?row.highest_stock_display:row.highest_stock;
        lines.push('最高板股票：'+esc(stock ? String(stock).replace(/\|/g,'、') : '名称未提供'));
        if(h.status==='STORED_SAME_DAY_HEIGHT_COMPONENT') lines.push('最高板：同日已存独立指标读回，不改原发布批次。');
        if(h.status==='ARCHIVE_NOT_RECALCULATED') lines.push('最高板：同日原始归档，未重新核验。');
        if(h.status==='STORED_COMPONENT_CONFLICT'||h.status==='CONFLICT') lines.push('最高板来源存在冲突，未自动补值。');
        return esc(row.date ? fmtDate(row.date) : dates[idx])+'<br>'+lines.join('<br>');
      }},
      legend:{top:0,right:6,icon:'roundRect',textStyle:{color:C.muted,fontSize:11},itemWidth:14,itemGap:12},
      grid:{left:44,right:42,top:36,bottom:52},
      dataZoom:[{id:'smash-slider-15d',type:'slider',xAxisIndex:0,
        rangeMode:['value','value'],startValue:zoomLeft,endValue:zoomRight,
        height:18,bottom:4,borderColor:'transparent',showDataShadow:false,brushSelect:false,
        dataBackground:{lineStyle:{opacity:0},areaStyle:{opacity:0}},
        selectedDataBackground:{lineStyle:{opacity:0},areaStyle:{opacity:0}},
        backgroundColor:'rgba(255,255,255,0.04)',fillerColor:'rgba(240,185,11,0.12)',
        handleStyle:{color:C.gold,borderColor:C.gold},moveHandleStyle:{color:C.gold},textStyle:{color:C.muted,fontSize:10}},
        {id:'smash-inside-15d',type:'inside',xAxisIndex:0,rangeMode:['value','value'],startValue:zoomLeft,endValue:zoomRight}],
      xAxis:{type:'category',data:dates,boundaryGap:false,axisLine:{lineStyle:{color:C.line}},axisTick:{show:false},axisLabel:{color:C.muted}},
      yAxis:[{type:'value',name:'砸盘分',min:0,max:10,minInterval:2,splitLine:{lineStyle:{color:C.grid}},axisLabel:{color:C.muted},nameTextStyle:{color:C.muted}},
        {type:'value',min:0,max:10,minInterval:2,splitLine:{show:false},axisLabel:{color:C.muted}}],
      series:series
    });
    if(chart.on){
      chart.__smash15ZoomHandler=function(ev){
        var z=(ev && ev.batch && ev.batch[0])||ev||{};
        var a=hasNumericValue(z.startValue)?Math.round(Number(z.startValue)):
          (hasNumericValue(z.start)?Math.round(Number(z.start)*(total-1)/100):null);
        var b=hasNumericValue(z.endValue)?Math.round(Number(z.endValue)):
          (hasNumericValue(z.end)?Math.round(Number(z.end)*(total-1)/100):null);
        if(a===null || b===null)return;
        a=Math.max(0,Math.min(total-1,a));b=Math.max(a,Math.min(total-1,b));
        SMASH_PANEL_ZOOM={key:zoomKey,start:a,end:b};markSmashWindow(a,b);
      };
      chart.on('datazoom',chart.__smash15ZoomHandler);
    }
  }
  // SMASH_PANEL_30D_NO_SHADOW_V1 END

  function renderSmash(smash, smashHistory) {
    var own = $('smashIndependentSummary');
    var host = $('smashTrend');
    if (!own && host && host.parentNode) {
      own=document.createElement('div');own.id='smashIndependentSummary';own.setAttribute('role','status');
      own.style.cssText='padding:6px 0;font-size:13px;line-height:1.6';host.parentNode.insertBefore(own,host);
    }
    if (own) {
      var state=smashDisplayState(smash);
      var missing=smash.missing_fields || ((smash.detail || {}).missing_inputs) || [];
      var value=hasNumericValue(smash.score) ? Number(smash.score).toFixed(2) : state.display_label;
      var hb = Number(smash.highest_board) || 0;
      var hs = smash.highest_stock_display || smash.highest_stock || smash.leader || '';
      hs = String(hs).replace(/\|/g,'、');
      var hbText = hb>0 ? '  最高板：'+hb+'板（'+(hs||'待核')+'）' : '';
      own.innerHTML='<span style="color:#f0b429;font-weight:600;">砸盘分：'+value+'</span><span style="margin-left:28px;color:#7fb3ff;font-weight:500;">最高板：'+hb+'板（'+(hs||'待核')+'）</span>';
      own.setAttribute('data-smash-calculation-state',state.state||'UNKNOWN');
    }
    renderDynamicSmashDetails(smash);
    renderSmashTrend(smash, smashHistory);

    // 高位反馈显示在砸盘情绪标题右侧
    var hf = smash.high_feedback || '暂无';
    var hfEl = $('smashHighFeedback');
    if (hfEl) {
      hfEl.innerHTML =
        '<span class="hf-label">高位反馈</span>' +
        '<b class="gold">' + hf + '</b>' +
        '<span class="hf-detail">高位 ' + fmtNum(smash.high_count) + ' 只' +
        '（晋级 ' + fmtNum(smash.high_continue_count) +
        ' / 断板 ' + fmtNum(smash.high_break_count) + '）</span>';
    }

    // 砸盘分数 > 最高连板数时：提示砸盘风险 + 连板情绪高涨
    var tipEl = $('smashRiskTip');
    if (tipEl) {
      var score = Number(smash.score) || 0;
      var board = Number(smash.highest_board) || 0;
      if (score > board && board > 0) {
        tipEl.innerHTML =
          '<span class="risk-warn">注意砸盘风险</span>' +
          '<span class="risk-hot">连板情绪高涨</span>' +
          '<span class="risk-detail">砸盘分 ' + score.toFixed(2) +
          ' > 最高板 ' + board + '板，晋级率偏高但空间受限，警惕高位兑现</span>';
        tipEl.style.display = 'flex';
      } else {
        tipEl.style.display = 'none';
      }
    }
  }

  // ============================================================
  // 五日情绪周期
  // ============================================================

  function renderTrend(history, cycle) {
    var chart = initChart('trendChart');
    if (!chart) return;

    var dates = (history || []).map(function (x) { return fmtShort(x.date); });
    // P03A R1: null显示为缺口（ECharts断点），真实0仍为0，不补0
    var scores = (history || []).map(function (x) {
      var v = x.emotion_score;
      if (!hasNumericValue(v)) return null;
      return Number(v);
    });
    var boards = (history || []).map(function (x) {
      var v = x.highest_board;
      if (!hasNumericValue(v)) return null;
      return Number(v);
    });

    if (!dates.length) {
      chart.setOption({
        graphic: {
          type: 'text',
          left: 'center',
          top: 'middle',
          style: { text: '暂无历史数据，运行 start.py 后自动积累', fill: C.muted, fontSize: 14 }
        }
      });
    } else {
      chart.setOption({
        tooltip: {
          trigger: 'axis',
          formatter: function (ps) {
            var line = ps.map(function (p) {
              var txt = !hasNumericValue(p.value) ? '待证据' :
                (p.seriesName === '最高板' ? Number(p.value) + '板' : Number(p.value).toFixed(2) + '分');
              return p.marker + p.seriesName + '：' + txt;
            }).join('<br>');
            return dates[ps[0].dataIndex] + '<br>' + line;
          }
        },
        legend: { top: 0, right: 6, icon: 'roundRect', textStyle: { color: C.muted, fontSize: 12 }, itemWidth: 14 },
        grid: { left: 46, right: 44, top: 36, bottom: 26 },
        xAxis: {
          type: 'category',
          data: dates,
          boundaryGap: false,
          axisLine: { lineStyle: { color: C.line } },
          axisTick: { show: false },
          axisLabel: { color: C.muted }
        },
        yAxis: [
          {
            type: 'value',
            name: '情绪分',
            min: 0,
            max: 100,
            splitLine: { lineStyle: { color: C.grid } },
            axisLabel: { color: C.muted },
            nameTextStyle: { color: C.muted }
          },
          {
            type: 'value',
            min: 0,
            max: 10,
            minInterval: 1,
            splitLine: { show: false },
            axisLabel: { color: C.muted }
          }
        ],
        series: [
          {
            name: '情绪分',
            type: 'line',
            smooth: true,
            symbol: 'circle',
            symbolSize: 7,
            data: scores,
            itemStyle: { color: C.up },
            lineStyle: { width: 3, color: C.up },
            areaStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: 'rgba(246,70,93,0.28)' },
                { offset: 1, color: 'rgba(246,70,93,0)' }
              ])
            }
          },
          {
            name: '最高板',
            type: 'line',
            smooth: true,
            yAxisIndex: 1,
            symbol: 'diamond',
            symbolSize: 9,
            data: boards,
            itemStyle: { color: C.blue },
            lineStyle: { width: 2, type: 'dashed', color: C.blue }
          }
        ]
      });
    }

    $('trendStats').innerHTML =
      '情绪周期：<b class="gold">' + (cycle.emotion_cycle || '--') + '</b>' +
      '　空间周期：<b>' + (cycle.height_cycle || '--') + '</b>' +
      '　趋势：<b class="gold">' + (cycle.trend || '--') + '</b>';
  }

  // ============================================================
  // 顶栏 / 标签 / 仓位 / 策略
  // ============================================================

  // Layout-only move. Existing chart objects and IDs are reused, no chart data is deleted.
  function ensureCompactTopRow() {
    var hero=document.querySelector('section.hero');
    if(!hero || !hero.parentNode) return null;
    var row=$('smashMoneyTopRow');
    if(!row) {
      row=document.createElement('section');row.id='smashMoneyTopRow';row.className='grid2 smash-money-top-row';
      row.setAttribute('aria-label','砸盘情绪与五日赚钱效应');
      hero.parentNode.insertBefore(row,hero);
      var left=document.createElement('div');left.className='panel compact-smash-panel';left.id='compactSmashPanel';row.appendChild(left);
      var source=hero.querySelector('.smash-panel');
      if(source){
        var heading=source.querySelector('h3');if(heading)left.appendChild(heading);
        ['smashRiskTip','smashIndependentSummary','dynamicSmashDetails','smashTrend','smashHistorySourceNote'].forEach(function(id){var e=$(id);if(e)left.appendChild(e);});
        if(!$('marketStructureHeading')){var h=document.createElement('h3');h.id='marketStructureHeading';h.textContent='连板与涨停生态';source.insertBefore(h,source.firstChild);}
      }
      var style=document.createElement('style');style.id='smashMoneyCompactStyle';
      style.textContent='#smashMoneyTopRow{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:18px;align-items:start;margin:18px 0}'+
        '#smashMoneyTopRow>.panel{min-width:0;width:auto;box-sizing:border-box}'+
        '#smashMoneyTopRow #smashTrend,#smashMoneyTopRow #moneyEffectChart{height:280px!important;min-height:280px;width:100%}'+
        '#smashMoneyTopRow h3{display:flex;flex-wrap:wrap;gap:6px;align-items:center;line-height:1.45}'+
        '#smashMoneyTopRow details{max-width:100%;overflow-wrap:anywhere}'+
        '#smashMoneyTopRow #dynamicSmashDetails>div{max-height:220px;overflow:auto}'+
        '#smashMoneyTopRow .mini-stats{line-height:1.7;overflow-wrap:anywhere}'+
        '@media(max-width:880px){#smashMoneyTopRow{grid-template-columns:minmax(0,1fr)}#smashMoneyTopRow #smashTrend,#smashMoneyTopRow #moneyEffectChart{height:260px!important;min-height:260px}}';
      document.head.appendChild(style);
    }
    return row;
  }

  // MONEY_PANEL_30D_ASOF_V1 BEGIN — display only; never changes source/current/API values.
  var MONEY_PANEL_ZOOM = null;

  function moneyPanelDay(x) {
    var s=String(x==null?'':x).replace(/-/g,'');
    return /^\d{8}$/.test(s)?s:'';
  }
  function moneyPanelDailyReady(r) {
    return !!r && hasNumericValue(r.earning_effect) &&
      (!r.daily || r.daily.status==null || r.daily.status==='VALID');
  }
  function moneyPanelComplete(r) {
    return !!r && r.status==='VALID' && moneyPanelDailyReady(r) && hasNumericValue(r.fund_cycle);
  }
  function moneyPanelPresentation(d) {
    var view=d.five_day_money_effect||{}, current=view.current||{};
    var target=moneyPanelDay(d.date)||moneyPanelDay(view.date)||moneyPanelDay(current.date);
    var rows=(Array.isArray(view.history)?view.history:[]).filter(function(r){
      return r && moneyPanelDay(r.date) && (!target || moneyPanelDay(r.date)<=target);
    }).slice().sort(function(a,b){return moneyPanelDay(a.date).localeCompare(moneyPanelDay(b.date));});
    if(!target && rows.length)target=moneyPanelDay(rows[rows.length-1].date);
    var exact=moneyPanelDay(current.date)===target;
    var candidates=rows.filter(function(r){
      // An explicitly pending current cannot be promoted by a contradictory same-day history row.
      return !exact || moneyPanelDay(r.date)!==target || moneyPanelComplete(current);
    });
    var chosen=exact&&moneyPanelComplete(current)?current:null;
    if(!chosen){for(var i=candidates.length-1;i>=0;i--){if(moneyPanelComplete(candidates[i])){chosen=candidates[i];break;}}}
    if(!chosen && exact && moneyPanelDailyReady(current))chosen=current;
    if(!chosen){for(var j=candidates.length-1;j>=0;j--){if(moneyPanelDailyReady(candidates[j])){chosen=candidates[j];break;}}}
    if(!chosen)chosen=exact?current:{};
    var asof=moneyPanelDay(chosen.date), fallback=!!asof&&!!target&&asof<target;
    var end=rows.length-1;
    for(var k=rows.length-1;k>=0;k--){
      if(hasNumericValue(rows[k].earning_effect)||hasNumericValue(rows[k].fund_cycle)){end=k;break;}
    }
    return {view:view,current:current,rows:rows,target:target,chosen:chosen,asof:asof,
      fallback:fallback,complete:moneyPanelComplete(chosen),startIndex:Math.max(0,end-29),endIndex:Math.max(0,end)};
  }

  // Approved 5-session earning effect. This block changes presentation, not calculations.
  function renderMoneyEffect(d) {
    var model=moneyPanelPresentation(d),view=model.view,current=model.chosen,rows=model.rows;
    var panel=$('moneyEffectSection');
    if(!panel) {
      panel=document.createElement('div');panel.id='moneyEffectSection';panel.className='panel compact-money-panel';
      panel.innerHTML=
        '<h3>五日赚钱效应 <span id="moneyFundStage" class="tag" style="margin-left:12px">数据不足</span></h3>'+
        '<div id="moneyEffectStats" class="mini-stats" role="status"></div>'+
        '<div id="moneyEffectChart" class="chart" style="height:310px;width:100%" role="img" aria-label="赚钱效应和资金周期，单位百分比"></div>'+
        '<div id="moneyEffectNote" style="font-size:12px;line-height:1.6;color:var(--muted)"></div>'+
        '<details style="margin-top:8px"><summary style="cursor:pointer;color:var(--muted)">查看所示日期的五交易日窗口与七档说明</summary>'+
        '<div id="moneyEffectWindow" style="overflow:auto;font-size:12px;line-height:1.8;padding:8px 0"></div></details>';
      var topRow=ensureCompactTopRow();
      if(topRow)topRow.appendChild(panel);
      else {var root=document.querySelector('main');if(root)root.appendChild(panel);}
    }
    panel.setAttribute('data-money-panel-version','30D_ASOF_V1');
    panel.setAttribute('data-asof-date',model.asof||'');
    panel.setAttribute('data-target-date',model.target||'');
    panel.setAttribute('data-asof-is-reference',model.fallback?'true':'false');
    panel.setAttribute('data-window-start','');
    panel.setAttribute('data-window-end','');
    panel.setAttribute('data-window-count','0');
    panel.setAttribute('data-history-count',String(rows.length));
    function show(x){return hasNumericValue(x)?Number(x).toFixed(2)+'%':'数据不足';}
    function humanSource(x){return x==='THS_883900_INDEX_DAILY_PCT'?'同花顺883900昨日涨停指数日涨幅':sourceLabel(x||'');}
    $('moneyFundStage').textContent=model.complete?(current.stage||'资金周期已生成'):'数据不足';
    var statusText='数据截至 '+fmtDate(model.asof||model.target)+'　赚钱效应 '+show(moneyPanelDailyReady(current)?current.earning_effect:null)+'　资金周期 '+show(model.complete?current.fund_cycle:null);
    statusText+='　历史'+rows.length+'日：日值'+rows.filter(function(r){return hasNumericValue(r.earning_effect);}).length+
      '／周期'+rows.filter(function(r){return hasNumericValue(r.fund_cycle);}).length+'个有效点';
    if(model.fallback)statusText+='　所选 '+fmtDate(model.target)+' 数据尚未完整，显示较早日期参考';
    $('moneyEffectStats').textContent=statusText;
    var sourceNote=view.source_label?('来源：'+view.source_label+'；与原本地样本均值分别保存。'):'';
    var notice='';
    if(model.fallback){
      notice='当前数值属于 '+fmtDate(model.asof)+'，不是 '+fmtDate(model.target)+' 的数值；所选日数据齐备后自动切换。';
      if(moneyPanelDay(model.current.date)===model.target && moneyPanelDailyReady(model.current))
        notice+='所选日已到库的日值为 '+show(model.current.earning_effect)+'，其资金周期仍待补齐。';
    } else if(current.missing_dates&&current.missing_dates.length){
      notice='当前五日窗口缺少：'+current.missing_dates.map(fmtDate).join('、')+'。';
    } else if(!model.complete)notice='当前日期尚无完整的五交易日数据。';
    $('moneyEffectNote').textContent=sourceNote+'赚钱效应＝当日昨日涨停表现；资金周期＝T-4 前收盘至 T 收盘的累计涨幅（包含 T-4 当日涨跌）。默认最近30个交易日，拖动可查看全部历史。'+
      notice+'阶段名称仅为指标分档，不自动启用交易或仓位。';
    $('moneyEffectWindow').innerHTML='<div>窗口截至 '+esc(fmtDate(model.asof||model.target))+(model.fallback?'（历史参考，非所选日值）':'')+'</div>'+
      (current.window_values||[]).map(function(r){return '<div>'+esc(fmtDate(r.date))+'　'+esc(show(r.value))+'　'+humanSource(r.source||r.status||'缺失')+'</div>';}).join('')+
      '<div style="padding-top:6px">≤−2 深度反击；(−2,2] 启动进攻；(2,5] 均衡参与；(5,8] 动能减弱；(8,13] 防御减仓；(13,17] 退潮警戒；>17 脉冲尾声。</div>';
    var chart=initChart('moneyEffectChart');if(!chart)return;
    if(!rows.length){chart.setOption({graphic:{type:'text',left:'center',top:'middle',style:{text:'尚无可读取的昨日涨停表现；不使用旧模型分数替代',fill:C.muted}}});return;}
    var key=[model.target,view.source||'',rows.length,rows[0].date,rows[rows.length-1].date].join('|');
    var start=model.startIndex,end=model.endIndex;
    if(MONEY_PANEL_ZOOM&&MONEY_PANEL_ZOOM.key===key){start=MONEY_PANEL_ZOOM.start;end=MONEY_PANEL_ZOOM.end;}
    panel.setAttribute('data-window-start',moneyPanelDay(rows[start].date));
    panel.setAttribute('data-window-end',moneyPanelDay(rows[end].date));
    panel.setAttribute('data-window-count',String(end-start+1));
    panel.setAttribute('data-history-count',String(rows.length));
    chart.setOption({animation:false,aria:{enabled:true},
      legend:{data:['赚钱效应','资金周期'],top:2,textStyle:{color:C.text},itemGap:24},
      grid:{left:52,right:24,top:45,bottom:62},
      tooltip:{trigger:'axis',confine:true,backgroundColor:C.panel,borderColor:C.line,textStyle:{color:C.text},formatter:function(ps){
        if(!ps||!ps.length)return '';var r=rows[ps[0].dataIndex]||{};
        var html=esc(fmtDate(r.date))+'<br>赚钱效应：'+esc(show(r.earning_effect))+'<br>资金周期：'+esc(show(r.fund_cycle))+
          '<br>阶段：'+esc(r.stage||'数据不足');
        html+='<br>来源：'+humanSource((r.daily||{}).source||view.source||'未明确');
        (r.window_values||[]).forEach(function(w){html+='<br>'+esc(fmtDate(w.date))+'：'+esc(show(w.value));});
        if(r.missing_dates&&r.missing_dates.length)html+='<br>缺失日：'+r.missing_dates.map(function(x){return esc(fmtDate(x));}).join('、');
        return html;
      }},
      dataZoom:[{id:'money-slider',type:'slider',xAxisIndex:0,bottom:8,height:20,
                  rangeMode:['value','value'],startValue:start,endValue:end,
                  showDataShadow:false,brushSelect:false,
                  dataBackground:{lineStyle:{opacity:0},areaStyle:{opacity:0}},
                  selectedDataBackground:{lineStyle:{opacity:0},areaStyle:{opacity:0}},
                  backgroundColor:C.panel,borderColor:C.line,fillerColor:'rgba(139,147,167,0.20)',
                  handleStyle:{color:C.muted,borderColor:C.muted},textStyle:{color:C.muted}},
                {id:'money-inside',type:'inside',xAxisIndex:0,rangeMode:['value','value'],startValue:start,endValue:end,
                  zoomOnMouseWheel:'ctrl',moveOnMouseWheel:false}],
      xAxis:{type:'category',boundaryGap:false,data:rows.map(function(r){return fmtShort(r.date);}),axisLabel:{color:C.muted},axisLine:{lineStyle:{color:C.line}}},
      yAxis:{type:'value',name:'%',nameTextStyle:{color:C.muted},axisLabel:{color:C.muted},splitLine:{lineStyle:{color:C.grid}}},
      series:[{name:'赚钱效应',type:'line',smooth:false,connectNulls:false,symbol:'circle',symbolSize:5,
          data:rows.map(function(r){return hasNumericValue(r.earning_effect)?Number(r.earning_effect):null;}),
          itemStyle:{color:C.up},lineStyle:{width:2,color:C.up}},
        {name:'资金周期',type:'line',smooth:false,connectNulls:false,symbol:'diamond',symbolSize:6,
          data:rows.map(function(r){return hasNumericValue(r.fund_cycle)?Number(r.fund_cycle):null;}),
          itemStyle:{color:C.gold},lineStyle:{width:3,color:C.gold}}]});
    if(chart.on){
      if(chart.__moneyPanelZoomHandler&&chart.off)chart.off('datazoom',chart.__moneyPanelZoomHandler);
      chart.__moneyPanelZoomHandler=function(ev){
        var z=(ev&&ev.batch&&ev.batch[0])||ev||{};
        var a=hasNumericValue(z.startValue)?Math.round(Number(z.startValue)):
          (hasNumericValue(z.start)?Math.round(Number(z.start)*(rows.length-1)/100):null);
        var b=hasNumericValue(z.endValue)?Math.round(Number(z.endValue)):
          (hasNumericValue(z.end)?Math.round(Number(z.end)*(rows.length-1)/100):null);
        if(a===null||b===null)return;
        a=Math.max(0,Math.min(rows.length-1,a));b=Math.max(a,Math.min(rows.length-1,b));
        MONEY_PANEL_ZOOM={key:key,start:a,end:b};
        panel.setAttribute('data-window-start',moneyPanelDay(rows[a].date));
        panel.setAttribute('data-window-end',moneyPanelDay(rows[b].date));
        panel.setAttribute('data-window-count',String(b-a+1));
      };
      chart.on('datazoom',chart.__moneyPanelZoomHandler);
    }
  }

  // Adapt the scalar V2 fact response to the presentation model used by the
  // existing chart. This keeps the calculation/storage contract separate from
  // the UI and treats incomplete windows as pending rather than zero.
  function loadMoneyEffectFact(date) {
    if (!date) return Promise.resolve(null);
    return fetch('/api/research/money-effect?date=' + encodeURIComponent(date), {cache:'no-store'})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (payload) {
        if (!payload || payload.schema !== 'MONEY_EFFECT_FACTS_V2' || !payload.result) return payload;
        var result = payload.result || {};
        var current = {date: result.trade_date || payload.trade_date, earning_effect: result.earning_effect,
          fund_cycle: result.fund_cycle, fund_cycle_exact: result.fund_cycle_exact, stage: result.stage,
          status: result.status, daily: {status: result.status, source: 'V2_FACT_MATCHED'}};
        var windowRows = Array.isArray(result.window) ? result.window.map(function (row) {
          return {date: row.window_date, value: hasNumericValue(row.earning_effect) ? Number(row.earning_effect) : null,
            status: row.status, source: 'V2_FACT_MATCHED'};
        }) : [];
        current.window_values = windowRows;
        var historyRows = Array.isArray(payload.history) ? payload.history.map(function (row) {
          return {date: row.trade_date, earning_effect: hasNumericValue(row.earning_effect) ? Number(row.earning_effect) : null,
            fund_cycle: hasNumericValue(row.fund_cycle) ? Number(row.fund_cycle) : null,
            fund_cycle_exact: row.fund_cycle_exact, stage: row.stage, status: row.status,
            daily: {status: row.status, source: 'V2_FACT_MATCHED'}};
        }) : [];
        var currentInHistory = false;
        historyRows.forEach(function (row) {
          if (row.date !== current.date) return;
          row.earning_effect = current.earning_effect;
          row.fund_cycle = current.fund_cycle;
          row.fund_cycle_exact = current.fund_cycle_exact;
          row.stage = current.stage;
          row.status = current.status;
          row.daily = current.daily;
          row.window_values = current.window_values;
          currentInHistory = true;
        });
        if (!currentInHistory) historyRows.push(current);
        return {date: current.date, current: current, history: historyRows,
          source: 'V2_FACT_MATCHED', source_label: '计算结果事实表（同日同批次）', read_source: payload.read_source};
      })
      .catch(function () { return null; });
  }
  // MONEY_PANEL_30D_ASOF_V1 END

  function renderDynamicSmashDetails(smash) {
    var detail=smash.detail||{}, el=$('dynamicSmashDetails'), host=$('smashIndependentSummary');
    if(!el&&host){el=document.createElement('details');el.id='dynamicSmashDetails';el.style.cssText='font-size:12px;line-height:1.8;margin-bottom:8px';host.parentNode.insertBefore(el,host.nextSibling);}
    if(!el)return;
    if(detail.version!=='5535_SMASH_DYNAMIC_DIV4_V1'){el.innerHTML='';return;}
    el.innerHTML='<summary style="cursor:pointer;color:var(--muted)">动态砸盘依据：有效'+esc(detail.included_group_count)+'组／检查'+esc(detail.observed_layer_count)+'层，固定÷4×10</summary>'+
      '<div>昨日最高 '+esc(detail.prior_highest_board==null?'待核':detail.prior_highest_board)+' 板；不含1进2；真0%计组数，原无样本或全停牌层跳过。</div>'+
      (detail.tiers||[]).map(function(r){return '<div>'+esc(r.label)+'：'+esc(r.numerator)+'/'+esc(r.effective_count)+'　'+
        (r.included?esc((Number(r.ratio_decimal)*100).toFixed(2))+'% · 计入':'不计入／'+esc(r.status))+
        '　原'+esc(r.original_count)+'只，剔除'+esc((r.removed||[]).length)+'只</div>';}).join('')+
      (detail.no_sample?'<div>各层已核清但无有效样本，总分按约定为0。</div>':'');
  }
  function renderHeader(d) {
    $('updateTime').textContent = d.update_time ? ('数据更新 ' + d.update_time) : '数据更新 --';
  }

  function renderTags(cycle, smash, emotion, fundCycle) {
    var stage = emotion.cycle_stage || '待证据';
    var tag = $('cycleStage');
    tag.textContent = '当日情绪：' + stage;
    tag.className = 'tag ' + stageClass(stage);

    var hTag = $('heightStage');
    fundCycle=fundCycle||{};
    hTag.textContent = '五日周期：'+(fundCycle.status==='VALID'&&fundCycle.stage?fundCycle.stage:'数据不足');
    hTag.title='T-4 前收盘至 T 收盘的累计涨幅（包含 T-4 当日涨跌）；不自动授权仓位。';
    hTag.className = 'tag';

    // 仓位水杯：按五日周期阶段映射
    var pctMap = {'深度反击':90,'启动进攻':80,'均衡参与':70,'动能减弱':50,'防御减仓':30,'退潮警戒':10,'脉冲尾声':1};
    var fcStage = (fundCycle && fundCycle.status==='VALID' && (fundCycle.fund_cycle_stage || fundCycle.stage)) ?
      (fundCycle.fund_cycle_stage || fundCycle.stage) : '';
    var pct = null;
    for (var k in pctMap) { if (fcStage.indexOf(k) >= 0) { pct = pctMap[k]; break; } }
    var pEl = $('positionScore'), pW = $('positionWave');
    if (pEl && pW) {
      if (pct === null) { pEl.textContent = '待证据'; pW.style.setProperty('--fill','0%'); }
      else { pEl.textContent = pct; pW.style.setProperty('--fill', pct + '%'); }
    }

    var sTag = $('smashStatus');
    // Keep the Smash label in its OWN module, not today's emotion overview.
    if (sTag) {
      var host = $('smashHighFeedback');
      if (host && host.parentNode && sTag.parentNode !== host.parentNode) host.parentNode.appendChild(sTag);
    }
    sTag.textContent = '砸盘情绪：' + smashDisplayState(smash).display_label;
    var sCls = /火热|高潮|砸盘|退潮/.test(smash.status || '') ? 'hot'
      : /试错|修复/.test(smash.status || '') ? 'cold' : '';
    sTag.className = 'tag ' + sCls;

    var concl = $('cycleConclusion');
    if (concl) concl.textContent = stage === '--' ? '' : '当前处于「' + stage + '」';
    renderCycleBar(stage);
  }

  // ============================================================
  // 阶段横条（全部阶段横排 + 指针标记当前）
  // ============================================================

  var CYCLE_STAGES = ['冰点阶段', '试错阶段', '启动阶段', '主升阶段', '高潮阶段', '退潮阶段'];

  function cycleIndex(stage) {
    var i = CYCLE_STAGES.indexOf(stage);
    if (i >= 0) return i;
    if (/冰点/.test(stage)) return 0;
    if (/试错/.test(stage)) return 1;
    if (/启动/.test(stage)) return 2;
    if (/主升/.test(stage)) return 3;
    if (/高潮/.test(stage)) return 4;
    if (/退潮/.test(stage)) return 5;
    return -1;
  }

  function renderCycleBar(stage) {
    var box = $('cycleBar');
    if (!box) return;
    var idx = cycleIndex(stage || '');
    var pct = Math.round(idx / (CYCLE_STAGES.length - 1) * 100);
    var nodes = CYCLE_STAGES.map(function (s, i) {
      return '<span class="cb-node' + (i === idx ? ' active' : '') + '">' +
        '<i></i>' + s.replace('阶段', '') + '</span>';
    }).join('');
    box.innerHTML =
      '<div class="cb-label">周期阶段</div>' +
      '<div class="cb-track">' + nodes + '</div>';
  }

  function renderPosition(position) {
    position = position || {};
    var disabled = /NOT_ENABLED|PAUSED/.test(String(position.status || ''));
    var invalid = /ERROR|INVALID|PENDING|INSUFFICIENT/.test(String(position.status || ''));
    var riskText = typeof position.risk === 'string' ? position.risk.trim() : '';
    if (disabled || invalid || !riskText || !/[★☆]/.test(riskText)) {
      $('posSuggest').textContent = disabled ? '未启用' : (invalid ? '待证据' : (position.suggest || '待证据'));
      $('posRisk').innerHTML = '<div class="risk-label">操作难度</div><div class="risk-level">' +
        (disabled ? (position.evidence_pending ? '历史数据待证据；五日判断及其仓位依赖暂停，未生成风险等级' : '五日判断及其仓位依赖暂停，未生成风险等级') : '风险数据待证据，不按低风险处理') + '</div>';
      return;
    }
    $('posSuggest').textContent = position.suggest || '待证据';

    // 解析星星数量，生成可视化操作难度组件
    var filled = (riskText.match(/★/g) || []).length;
    var level = '低';
    var levelCls = 'risk-low';
    var levelTip = '操作轻松，按计划执行';
    if (filled >= 5) { level = '极高'; levelCls = 'risk-critical'; levelTip = '难度极高，建议观望或极小仓位'; }
    else if (filled >= 4) { level = '高'; levelCls = 'risk-high'; levelTip = '操作难度高，严格止损，控制仓位'; }
    else if (filled >= 3) { level = '中'; levelCls = 'risk-mid'; levelTip = '难度适中，谨慎操作，注意节奏'; }
    else if (filled >= 2) { level = '较低'; levelCls = 'risk-low-mid'; levelTip = '难度较低，可按计划正常操作'; }

    var starsHtml = '';
    for (var i = 0; i < 5; i++) {
      var active = i < filled ? ' active ' + levelCls : '';
      starsHtml += '<span class="risk-star' + active + '" title="' + (i + 1) + '星">★</span>';
    }

    $('posRisk').innerHTML =
      '<div class="risk-label">操作难度</div>' +
      '<div class="risk-stars" title="' + levelTip + '">' + starsHtml + '</div>' +
      '<div class="risk-level ' + levelCls + '">' + level + ' · ' + levelTip + '</div>';
  }

  function renderStrategy(position, cycle) {
    $('strategyText').textContent = position.strategy || '暂无策略建议';
    $('cycleDesc').textContent = cycle.description || '';
  }

  // ============================================================
  // 涨停梯队 / 概念联动 / 明日三板预案
  // ============================================================

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function renderSecondPool(list, available) {
    var box = $('secondPool');
    if (!box) return;
    if (!list || !list.length) {
      box.innerHTML = '<div class="pool-empty">' + (available === false ? '二板梯队数据待证据' : '暂无2板个股') + '</div>';
      return;
    }
    box.innerHTML = list.map(function (r) {
      var same = (r.same_concept || []).slice(0, 4).map(function (s) {
        var cls = s.first_count >= 3 ? 's' : '';
        var names = (s.first_stocks || []).slice(0, 4).join('、');
        return '<span class="' + cls + '">' + esc(s.concept) + '(' + s.first_count + ')' +
          (names ? ' <em class="stk">' + esc(names) + '</em>' : '') + '</span>';
      }).join(' / ');
      return '<div class="pool-row">' +
        '<b>' + esc(r.name) + '</b> <span class="muted">' + (r.seal_time_fmt || '') + ' ' + (r.seal_amount_fmt || '') + '</span>' +
        '<div class="pool-sub">' + (same || '<span class="muted">无同概念1板</span>') + '</div>' +
        '</div>';
    }).join('');
  }

  function renderFirstPool(list, available) {
    var box = $('firstPool');
    if (!box) return;
    if (!list || !list.length) {
      box.innerHTML = '<div class="pool-empty">' + (available === false ? '首板梯队数据待证据' : '暂无1板个股') + '</div>';
      return;
    }
    box.innerHTML = list.map(function (r, i) {
      var mark = i === 0 ? ' <span class="s">最早涨停</span>' : '';
      var zc = (r.zt_counts || []).slice(0, 4).map(function (z) {
        var cls = z.total >= 3 ? 's' : '';
        return '<span class="' + cls + '">' + esc(z.concept) + '(' + z.total + ')</span>';
      }).join(' ');
      return '<div class="pool-row">' +
        '<b>' + esc(r.name) + '</b> <span class="muted">' + (r.seal_time_fmt || '') + '</span>' + mark +
        '<div class="pool-sub">' + (zc || '<span class="muted">暂无概念</span>') + '</div>' +
        '</div>';    }).join('');
  }

  // ============================================================
  // 明日三板预案 · 顶部长横幅
  // ============================================================

  var bannerCleanup = null;
  var bannerResizeHandler = null;

  function resetBannerDetails() {
    if (bannerCleanup) { bannerCleanup(); bannerCleanup = null; }
    if (bannerResizeHandler) {
      window.removeEventListener('resize', bannerResizeHandler);
      bannerResizeHandler = null;
    }
    var popup = $('bannerPopup');
    if (popup) {
      popup.classList.remove('show'); popup.innerHTML = '';
      popup.onmouseenter = null; popup.onmouseleave = null;
    }
  }

  // BEGIN 5535 S02 MAIN CARD VIEW V1 - display only, no scoring/permission changes.
  function s02Number(v) {
    return typeof v === 'number' && Number.isFinite(v);
  }
  function s02Value(v) { return P50UI.value(v); }
  function s02Points(v) {
    return s02Number(v) ? v.toFixed(2) : '待证据';
  }
  function s02View(r) {
    return r && r.research_view && r.research_view.schema === '5535_S02_MAIN_CARD_VIEW_V1' ? r.research_view : {
      research_status: 'NOT_CONNECTED', research_score: null, known_subtotal: null,
      known_item_count: 0, required_item_count: 12, theme_name: null, module_scores: {},
      factors: [], reasons: [], limitations: [], observations: [], issues: ['此API未附同批新研究结果，不使用旧分数或旧理由替代。'],
      strategy_status: 'NOT_ENABLED', screening: {}
    };
  }
  function s02Status(v) { return P50UI.human(v); }
  function s02Screen(v) {
    return ({ELIGIBLE:'通过已批准筛选（不等于买入）',EXCLUDED:'已按批准规则排除',UNKNOWN:'资格或两日开盘证据待核',PENDING:'资格待核'})[v] || '资格待核';
  }
  // 缺项/状态码中文标签：已知码映射，未知转通用"待核条件"（原始码留诊断层）
  var ISSUE_LABELS = {
    'ITEM_EVIDENCE_NOT_VERIFIED':'证据未核验','SCOPE_VERIFIED_MISSING':'范围未核验',
    'CLOSING_VERIFIED_MISSING':'收盘未核验','ITEM_SOURCE_DATES_MISMATCH_OR_MISSING':'来源日期缺失或不符',
    'THEME_CONFIRMATION_PENDING':'题材确认待核','NUMERATOR_DENOMINATOR_REQUIRED':'缺分子/分母',
    'DATED_THEME_NOT_SELECTED':'日期化题材未选择','MEMBERSHIP_COMPLETE_MISSING':'成员完整性缺失',
    'THEME_CONFIRMED_MISSING':'题材确认缺失','MEMBERS_LIST_MISSING':'成员名单缺失',
    'CANDIDATE_NOT_IN_COMPLETE_PRIOR_FIRST_BOARD_SET':'候选不在完整前日首板集合',
    'NOT_COMPARABLE_SINGLETON':'无可比样本','MEMBER_LIST_DIFFERS_FROM_REFERENCE':'成员名单与参考不一致',
    'INPUT_PENDING':'输入待核','INPUT_MISSING':'输入缺失','UPSTREAM':'上游依赖'
  };
  function issueCode(v) { return P50UI.issue(v); }
  function issueLabel(v) { return P50UI.issue(v); }
  function issuesText(list) {
    return (list || []).map(issueLabel).join('；');
  }

  function sourceLabel(v) { return v === "THS_883900_INDEX_DAILY_PCT" ? "同花顺883900昨日涨停指数日涨幅" : P50UI.source(v); }
  function s02Toolbar(box) {
    var sub = document.querySelector('.banner-sub');
    if (sub) sub.textContent = '市场30 · 题材40 · 先手8 · 封板22；新研究结果，不是旧模型推荐';
    var bar = $('s02ResearchToolbar');
    if (!bar) {
      bar = document.createElement('div'); bar.id = 's02ResearchToolbar';
      bar.style.cssText = 'padding:8px 4px;display:flex;gap:16px;flex-wrap:wrap;font-size:12px;';
      if (box.parentNode) box.parentNode.insertBefore(bar, box);
    }
    bar.innerHTML = '<strong>新方案 S02研究 · 30/40/8/22</strong>' +
      '<a style="color:var(--gold);text-decoration:underline" href="/research/closed-loop" target="_blank" rel="noopener">昨日二板 → 今日结果</a>' +
      '<span>旧模型仅折叠对照；研究分不是成功率或交易权限</span>';
  }
  // S02_PARENT_CARD_CLOSEOUT_R1: saved-view presentation only; no fetch, no score writes.
  var S02Plan = (function () {
    'use strict';
    var version='S02_PARENT_CARD_CLOSEOUT_R1';
    var order=['A01','A02','A03','A04','A05','B01','B02','B03','C02','D01','D02','D03'];
    var caps={A01:8,A02:8,A03:7,A04:4,A05:3,B01:10,B02:12,B03:18,C02:8,D01:10,D02:6,D03:6};
    var names={A01:'昨日涨停表现',A02:'已发生二进三承接',A03:'高位续板保有',A04:'市场封板稳定',A05:'涨跌停两端力量',B01:'题材有效成员上涨广度',B02:'题材两日相对强度',B03:'题材梯队规模与层次',C02:'首板阶段相对先手',D01:'最后封板后持续时间',D02:'当日开板次数',D03:'收盘封单相对规模'};
    var labels={CALCULATED:'已计算',PAUSED:'本轮暂停',NOT_COMPARABLE:'不可比',CROSS_DAY_PENDING:'跨日归属待核',EVIDENCE_PENDING:'证据待核',INPUT_REVIEW:'输入待核',NOT_RETURNED:'接口未返回'};
    var hints={A01:'沿用本研究已保存的本地样本表现，不因五日图切换883900自动换源。',A02:'已发生的群体承接，不是该股次日晋级概率。',A03:'高位群体断板与全市场炸板分别统计。',A04:'收盘封住与盘中炸板的比例。',A05:'沿用原有涨跌停家数口径。',B01:'按当前仅两日涨停股范围，本项暂停；不以涨停子集冒充题材上涨广度。',B02:'本项暂停；不以涨停子集、指数或家数统计替代全市场逐股中位数。',B03:'两日统一父级口径；今日去重后剔除候选，分别统计其他首板、二板、三板及以上。',C02:'前日完整同父级首板集合，含后来未晋级者；使用首封时间，并列取平均名次。',D01:'原规则的封板后交易分钟，不计午休。',D02:'真实0次有效，不把缺失改为0。',D03:'封单相对流通市值的静态代理，不代表成交保证。'};
    function num(x){return typeof x==='number'&&Number.isFinite(x);}
    function safe(x){return String(x==null?'':x).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
    function points(x){return num(x)?x.toFixed(2):'—';}
    function percent(x){return num(x)?(x*100).toFixed(2)+'%':'未提供';}
    function money(x){if(!num(x))return '未提供';return Math.abs(x)>=1e8?(x/1e8).toFixed(2)+'亿元':Math.abs(x)>=1e4?(x/1e4).toFixed(2)+'万元':x.toFixed(2)+'元';}
    function obj(x){return x&&typeof x==='object'&&!Array.isArray(x)?x:{};}
    function day(x){var s=String(x||'').replace(/-/g,'');return /^\d{8}$/.test(s)?s:'';}
    function dateText(x){var d=day(x);return d?d.slice(0,4)+'-'+d.slice(4,6)+'-'+d.slice(6):'日期未提供';}
    function issueText(f){return (Array.isArray(f.issues)?f.issues:[]).map(String).join('；');}
    function factorState(f){
      if(f._absent)return 'NOT_RETURNED';
      if(num(f.score))return /PENDING|CONFLICT|INVALID|MISSING/.test(String(f.data_status||''))?'INPUT_REVIEW':'CALCULATED';
      if(f.factor_id==='B01'||f.factor_id==='B02')return 'PAUSED';
      var text=issueText(f);
      if(f.factor_id==='C02'){
        if(/NOT_COMPARABLE|SINGLETON|不足两只|少于两只/.test(text))return 'NOT_COMPARABLE';
        if(/候选在相应日期并无该题材|不跨日倒填|CANDIDATE_NOT_IN_COMPLETE_PRIOR_FIRST_BOARD_SET|跨日归属/.test(text))return 'CROSS_DAY_PENDING';
      }
      return 'EVIDENCE_PENDING';
    }
    function blocker(f){
      var st=factorState(f);
      if(st==='PAUSED')return f.factor_id==='B01'?'当前只处理两日涨停股，未采完整题材涨跌平成员；不补0。':'未采全市场逐股涨幅，本轮不计算原定义的两日中位数比较。';
      if(st==='NOT_COMPARABLE')return '昨日同父级首板不足两只，按原规则不计分；不是采集失败。';
      if(st==='CROSS_DAY_PENDING')return '前日没有与当前所选父级对应的原因归属证据；不拿今日原因倒填。';
      if(st==='NOT_RETURNED')return '接口没有返回本分项；只核对同批修订与显示读取，不重新采集已存行情。';
      if(st==='INPUT_REVIEW')return '已存数值的输入仍有待核状态，不作为完整研究分；保留原记录。';
      if(/CONFLICT|冲突/.test(issueText(f)))return '来源或比较集合存在明确冲突，详见原始诊断；不自动更换主因。';
      if(f.factor_id==='B03')return '当日父级比较集合尚未完整，未知归属不能当作不属于。';
      if(f.factor_id==='C02')return '前日比较集合、首封时刻或批准范围仍待核；不以末封代替首封。';
      return '所需日期、范围或原始字段尚未核实，详见原研究日报。';
    }
    function model(r){
      r=obj(r);var v=s02View(r),source=Array.isArray(v.factors)?v.factors:[],map={},bad=false;
      source.forEach(function(f){if(!f||!Object.prototype.hasOwnProperty.call(caps,f.factor_id)){bad=true;return;}if(map[f.factor_id])bad=true;map[f.factor_id]=f;});
      var fs=order.map(function(id){return map[id]||{factor_id:id,score:null,input_values:{},issues:[],_absent:true};});
      var known=fs.filter(function(f){return num(f.score);}),missing=fs.filter(function(f){return !num(f.score);});
      var sum=known.reduce(function(a,f){return a+f.score;},0),budget=known.reduce(function(a,f){return a+caps[f.factor_id];},0);
      if(known.some(function(f){return f.score<0||f.score>caps[f.factor_id]+1e-7||num(f.max)&&f.max!==caps[f.factor_id];}))bad=true;
      if(num(v.known_item_count)&&v.known_item_count!==known.length)bad=true;
      if(num(v.known_subtotal)&&Math.abs(v.known_subtotal-sum)>1e-5)bad=true;
      if(v.code&&r.code&&String(v.code)!==String(r.code))bad=true;
      if(r.s02_plan_revision&&r.s02_plan_revision.base_batch_id&&v.batch_id&&r.s02_plan_revision.base_batch_id!==v.batch_id)bad=true;
      var linked=obj(r.s02_plan_revision).revision_id,revision=v.completion_revision_id||linked||'';
      if(linked&&v.completion_revision_id&&linked!==v.completion_revision_id)bad=true;
      var c=obj(obj(map.B03).calculation),c2=obj(obj(map.C02).calculation);
      var parent=/PARENT/.test(String(v.record_mode||''))||/^s02p:/.test(revision)||!!(v.parent_taxonomy_version||c.parent_taxonomy_sha256);
      var fine=v.original_fine_theme||c.original_fine_theme||c2.original_fine_theme||null;
      var policy=v.parent_taxonomy_version||c.classification_policy||c2.classification_policy||'';
      var modes=String(v.record_timing||'')+' '+String(v.timing_class||'')+' '+String(v.record_mode||'');
      var supplement=parent||/SUPPLEMENT|POST_CUTOFF|RETROSPECTIVE|BACKFILL|COMPLETION/.test(modes);
      var counts={};fs.forEach(function(f){var s=factorState(f);counts[s]=(counts[s]||0)+1;});
      var complete=num(v.complete_score)?v.complete_score:v.research_score,ev=obj(v.input_evidence_status);
      var full=!bad&&known.length===12&&counts.CALCULATED===12&&num(complete)&&Math.abs(complete-sum)<1e-5&&ev.source_date_verified!==false&&ev.closing_verified!==false;
      var score=!bad&&num(v.known_subtotal)?(full?complete:v.known_subtotal):null;
      var modules=['A','B','C','D'].map(function(k){
        var rows=fs.filter(function(f){return f.factor_id[0]===k;}),good=rows.filter(function(f){return num(f.score);}),x=obj(obj(v.module_scores)[k]);
        var actual=good.reduce(function(a,f){return a+f.score;},0),stored=num(x.score)?x.score:num(x.known_subtotal)?x.known_subtotal:null;
        // An empty module may store known_subtotal=0; that is not a scored zero.
        if(good.length===0)stored=null;
        var derived=stored===null&&good.length>0;
        var inconsistent=(num(stored)&&Math.abs(stored-actual)>1e-5)||(num(x.score)&&good.length!==rows.length);
        if(derived)stored=actual; // display aggregation of existing factors only, never a new factor score
        if(inconsistent)bad=true;
        return {key:k,name:{A:'市场背景',B:'题材',C:'个股先手',D:'封板质量'}[k],max:{A:30,B:40,C:8,D:22}[k],score:stored,inconsistent:inconsistent,derived:derived,known:good.length,total:rows.length,complete:good.length===rows.length,rows:rows};
      });
      if(bad){score=null;full=false;}
      return {v:v,fs:fs,known:known,missing:missing,budget:budget,bad:bad,full:full,score:score,counts:counts,modules:modules,parent:parent,fine:fine,policy:policy,revision:revision,supplement:supplement,code:String(r.code||v.code||''),theme:v.theme_name||null};
    }
    function input(f){
      var x=obj(f.input_values),s=[],id=f.factor_id;function push(k,val){s.push(k+'：'+val);}
      if(id==='A01')push('原研究样本平均涨幅',num(x.r_pct)?x.r_pct.toFixed(4)+'%':'未提供');
      if(id==='A02')push('已发生二进三比例',percent(x.p23));
      if(id==='A03')push('高位失败比例',percent(x.fail_high));
      if(id==='A04'||id==='A05'){push('涨停',num(x.U)?x.U+'家':'未提供');var k=id==='A04'?'Z':'D';push(k==='Z'?'炸板':'跌停',num(x[k])?x[k]+'家':'未提供');}
      if(id==='B01')push('完整题材成员上涨比例',percent(x.breadth));
      if(id==='B02'){push('当日超额中位涨幅',num(x.excess_median_T)?x.excess_median_T.toFixed(2)+'个百分点':'未提供');push('前日超额中位涨幅',num(x.excess_median_previous)?x.excess_median_previous.toFixed(2)+'个百分点':'未提供');}
      if(id==='B03')['n1','n2','n3plus'].forEach(function(k,i){push(['其他首板','其他二板','三板及以上'][i],num(x[k])?x[k]+'家':'未提供');});
      if(id==='C02'){push('可比前日首板',num(x.n)?x.n+'家':'未提供');push('首封平均名次',num(x.rank)?String(x.rank):'未提供');}
      if(id==='D01')push('封板后交易时长',num(x.remaining_session_minutes)?x.remaining_session_minutes.toFixed(1)+'分钟':'未提供');
      if(id==='D02')push('开板次数',num(x.open_break_count)?x.open_break_count+'次':'未提供');
      if(id==='D03'){push('封单',money(x.seal_amount));push('流通市值',money(x.circulating_market_cap));if(num(x.seal_amount)&&num(x.circulating_market_cap)&&x.circulating_market_cap>0)push('相对规模',percent(x.seal_amount/x.circulating_market_cap));}
      return s.join('；');
    }
    function screen(v){return ({ELIGIBLE:'资格通过（非买入许可）',EXCLUDED:'按原规则排除',UNKNOWN:'资格待核',PENDING:'资格待核'})[v]||'资格待核';}
    function value(f){return num(f.score)?points(f.score):labels[factorState(f)];}
    function attrs(m){return ' data-plan-version="'+version+'" data-code="'+safe(m.code)+'" data-trade-date="'+safe(day(m.v.trade_date))+'" data-batch-id="'+safe(m.v.batch_id||'')+'" data-revision="'+safe(m.revision)+'" data-theme="'+safe(m.theme||'')+'" data-known-count="'+m.known.length+'" data-score="'+(num(m.score)?points(m.score):'')+'" data-record-consistent="'+(!m.bad)+'"';}
    function sheet(m){return '<div class="s02p-modules">'+m.modules.map(function(x){var state=x.inconsistent?'记录需核对':x.known===0?(x.rows.length===1?labels[factorState(x.rows[0])]:'暂无有效项'):x.derived?'分项展示合计':x.complete?'已完整':'已算小计';return '<div data-module="'+x.key+'"><span>'+x.name+'</span><strong>'+points(x.inconsistent?null:x.score)+' / '+x.max+'</strong><small>'+state+' · '+x.known+'/'+x.total+'项</small></div>';}).join('')+'</div>';}
    function observation(x){var d=obj(x.details);if(x.observation_id==='C01')return [d.industry?'行业：'+d.industry:'',d.theme?'原观察题材：'+d.theme:'业务关联仍以原观察证据为准'].filter(Boolean).join('；');if(x.observation_id==='C03')return num(d.relative_return_pct)?'连板前相对涨幅：'+d.relative_return_pct.toFixed(2)+'%':'原比较区间与基准尚未提供';if(x.observation_id==='D04')return [num(d.turnover_pct)?'当日换手：'+d.turnover_pct.toFixed(2)+'%':'',num(d.turnover_multiple)?'历史倍数：'+d.turnover_multiple.toFixed(2):'历史倍数未提供'].filter(Boolean).join('；');return '未提供可展示观察字段';}
    var css='<style>.s02p{color:var(--text,#dce5f2);font-size:13px;line-height:1.6;overflow-wrap:anywhere}.s02p h3,.s02p h4{margin:0 0 8px}.s02p h3{font-size:18px}.s02p h4{font-size:14px;color:#8dc8dc}.s02p-header,.s02p-section{padding:12px 16px;border-bottom:1px solid var(--line,#334154)}.s02p-score{font-size:28px;color:var(--gold,#f2c45b);margin-right:8px}.s02p-small,.s02p small{font-size:12px;color:#9caec7}.s02p-modules{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.s02p-modules>div{padding:7px;background:rgba(125,155,195,.08);border-radius:5px}.s02p-modules span,.s02p-modules strong,.s02p-modules small{display:block}.s02p-status{padding:2px 6px;border:1px solid #46566c;border-radius:4px;white-space:nowrap}.s02p details{margin:0}.s02p summary{cursor:pointer;min-height:36px;line-height:1.5;padding:6px 0}.s02p table{border-collapse:collapse;width:100%;font-size:12px;table-layout:auto}.s02p th,.s02p td{border-bottom:1px solid var(--line,#334154);padding:7px 5px;text-align:left;vertical-align:top}.s02p th:nth-child(2),.s02p td:nth-child(2){white-space:nowrap}.s02p a{color:var(--gold,#f2c45b);text-decoration:underline}.s02p-warn{color:#e5b56c}.s02p-factors{max-height:380px;overflow:auto}.s02p-line{padding:6px 0}.s02p-pause{color:#9caec7}.s02p details[open]>summary{margin-bottom:6px}.s02p-version{font-size:11px;color:#9caec7;word-break:break-all}.s02p-links{display:flex;flex-wrap:wrap;gap:12px}.s02p-basis{border-left:3px solid #587ca0;padding-left:10px}@media(max-width:600px){.s02p-modules{grid-template-columns:repeat(2,minmax(0,1fr))}.s02p-header,.s02p-section{padding:10px}.s02p-factors{max-height:300px}.s02p table{font-size:11px}.s02p th,.s02p td{padding:6px 3px}.s02p-status{white-space:normal}.s02p-score{font-size:26px}}</style>';
    return {version:version,model:model,safe:safe,points:points,num:num,day:day,dateText:dateText,input:input,blocker:blocker,observation:observation,screen:screen,sheet:sheet,css:css,caps:caps,names:names,hints:hints,labels:labels,state:factorState,value:value,attrs:attrs};
  })();
  function buildS02ResearchCard(r,i){
    var p=S02Plan,m=p.model(r),v=m.v,b=m.fs[7],c=m.fs[8],q=(v.screening||{}).strategy_status;
    var state=m.bad?'记录需核对':m.full?'完整研究分':m.parent?'父级修订':'原研究';
    var medalHtml = i === 0 ? '<span class="bc-medal bc-gold" title="今日最高分">1</span>'
      : i === 1 ? '<span class="bc-medal bc-silver" title="第2名">2</span>'
      : i === 2 ? '<span class="bc-medal bc-bronze" title="第3名">3</span>' : '';
    return '<div class="bc-card" data-idx="'+i+'"'+p.attrs(m)+'>'+medalHtml+'<div class="bc-header">' + '<div class="bc-rank" style="width:auto;font-size:11px">记录 '+(i+1)+'</div><div class="bc-name">'+p.safe(r.name||r.code)+'<em>2进3</em></div></div>'+
      '<div class="bc-meta">'+p.safe(m.theme||'主题材待核')+' · '+p.safe(p.dateText(v.trade_date))+'</div>'+
      '<div class="bc-score-row"><span class="bc-score" style="font-size:26px">'+p.points(m.score)+'</span><span class="bc-score-note">'+(m.full?'完整研究分 /100':'已算分项小计 · 非总分')+'</span></div>'+
      '<div class="bc-score-detail">'+state+' · 已算 '+m.known.length+'/12项 · 权重 '+m.budget+'/100</div>'+
      '<div style="font-size:12px;line-height:1.5;white-space:normal">梯队 '+p.value(b)+' /18 · 先手 '+p.value(c)+(p.num(c.score)?' /8':'')+'</div>'+
      '<div class="bc-strategy">'+p.safe(p.screen(q))+'</div><div class="bc-hint">'+(m.counts.PAUSED?'B01/B02本轮暂停 · ':'')+'点击查看原因与版本</div></div>';
  }
  function buildS02ResearchPopup(r){
    var pane=typeof document!=='undefined'&&document.getElementById?document.getElementById('bannerPopup'):null;
    if(pane){
      pane.style.overflowAnchor='none';
      var openingCode=String(r&&r.code||'');
      Promise.resolve().then(function(){
        var article=pane.querySelector('article[data-plan-version="S02_PARENT_CARD_CLOSEOUT_R1"]');
        if(article&&article.getAttribute('data-code')===openingCode)pane.scrollTop=0;
      }); // after original openPopup replaces innerHTML and makes the pane visible
    }
    var p=S02Plan,m=p.model(r),v=m.v,q=(v.screening||{}).strategy_status,targets=m.fs.filter(function(f){return f.factor_id==='B03'||f.factor_id==='C02';});
    var h=p.css+'<article class="s02p"'+p.attrs(m)+'><header class="s02p-header"><h3>'+p.safe(r.name||r.code)+' · 二进三研究预案</h3>'+
      '<div><strong class="s02p-score">'+p.points(m.score)+'</strong>'+(m.full?'完整研究分 /100':'已算分项小计 · 非总分')+'</div>'+
      '<div>'+p.safe(p.screen(q))+' · 已算 '+m.known.length+'/12项 · 已覆盖权重 '+m.budget+'/100</div>'+
      '<div class="s02p-small">研究日 '+p.safe(p.dateText(v.trade_date))+' · '+(m.parent?'父级题材：':'所选题材：')+'<b>'+p.safe(m.theme||'待核')+'</b></div>';
    if(m.fine)h+='<div class="s02p-small">原细分原因：'+p.safe(m.fine)+'（保留原始归因）</div>';
    if(m.supplement)h+='<div class="s02p-small">独立补录／父级复算版本，不是当时已知的原预案；不纳入原前瞻样本。</div>';
    if(m.bad)h+='<div class="s02p-warn">记录不一致：暂不展示小计；检查同日批次、分项及修订，不回退旧模型。</div>';
    if(v.input_mode==='SYNTHETIC'||v.input_mode==='PASTED_EXAMPLE')h+='<div class="s02p-warn">展示测试数据，未连接本机数据库，不是新采集行情。</div>';
    h+='</header><section class="s02p-section">'+p.sheet(m)+'</section><section class="s02p-section"><h4>题材梯队与首板先手</h4>';
    targets.forEach(function(f){var state=p.state(f);h+='<div class="s02p-line" data-target-factor="'+f.factor_id+'" data-factor-status="'+state+'"><b>'+p.names[f.factor_id]+'</b>　<strong>'+p.value(f)+(p.num(f.score)?' / '+p.caps[f.factor_id]:'')+'</strong>'+(p.num(f.score)?'　<span class="s02p-status">'+p.labels[state]+'</span>':'')+'<div class="s02p-small">'+p.safe(p.num(f.score)?p.input(f):p.blocker(f))+'</div></div>';});
    h+='</section>';
    if(m.counts.PAUSED)h+='<section class="s02p-section s02p-pause" data-paused="B01,B02"><b>本轮暂停：题材上涨广度10分、两日相对强度12分</b><div>仅处理两日涨停股，不采全市场；不填0、不归一化成完整总分。</div></section>';
    var others=m.fs.filter(function(f){return ['B01','B02','B03','C02'].indexOf(f.factor_id)<0&&p.state(f)!=='CALCULATED';});
    if(q!=='ELIGIBLE'||others.length)h+='<section class="s02p-section"><h4>其他待核条件</h4><div>'+p.safe(q==='EXCLUDED'?'已按原资格规则排除，保留记录，不进入候选预案。':q!=='ELIGIBLE'?'原资格仍待核，不重新解释成通过。':'')+'</div>'+others.map(function(f){return '<div>'+p.names[f.factor_id]+'：'+p.safe(p.blocker(f))+'</div>';}).join('')+'</section>';
    h+='<section class="s02p-section"><details class="s02p-factor-details"><summary>全部12项依据（分值、状态和输入）</summary><div class="s02p-factors"><table><thead><tr><th>分项</th><th>已存分值</th><th>状态与输入</th></tr></thead><tbody>';
    m.fs.forEach(function(f){var st=p.state(f);h+='<tr data-factor="'+f.factor_id+'" data-factor-status="'+st+'"><td>'+p.names[f.factor_id]+'</td><td>'+p.points(f.score)+' / '+p.caps[f.factor_id]+'</td><td><b>'+p.labels[st]+'</b><div>'+p.safe(p.num(f.score)?p.input(f):p.blocker(f))+'</div><small>'+p.safe(p.hints[f.factor_id])+'</small></td></tr>';});
    h+='</tbody></table></div></details></section><section class="s02p-section"><details><summary>三项观察 · 不计分</summary>';
    (Array.isArray(v.observations)?v.observations:[]).forEach(function(x){h+='<div class="s02p-line"><b>'+p.safe(x.name||'观察')+'</b>：'+p.safe(p.observation(x))+'</div>';});
    h+='</details></section><section class="s02p-section"><details class="s02p-version-details"><summary>数据版本与原记录</summary><div class="s02p-version">'+
      '批次：'+p.safe(v.batch_id||'未提供')+'<br>独立修订：'+p.safe(m.revision||'无独立修订，原研究记录')+'<br>父级规则：'+p.safe(m.policy||'未提供父级版本')+'</div><div class="s02p-small">原研究、资格和非目标分项保留；缺分、有效0分、不可比与主动暂停分别表示。</div></details></section>';
    var query=p.day(v.trade_date)?'?date='+encodeURIComponent(p.dateText(v.trade_date)):'';
    h+='<section class="s02p-section"><h4>原有日报与次日跟踪</h4><div class="s02p-links"><a href="/research/daily'+query+'" target="_blank" rel="noopener">当日研究日报</a><a href="/research/closed-loop'+query+'" target="_blank" rel="noopener">下一交易日结果</a></div><small>沿用原记录入口；本次不生成买点、仓位或新的交易条件。</small></section>'+
      '<footer class="s02p-section s02p-small">研究用途，非买入指令。小计不是排名依据；不把新增题材分重复叠加，不覆盖原研究，正式策略仍未启用。</footer></article>';
    return h;
  }
  // END 5535 S02 MAIN CARD VIEW V1

  if (globalThis.__P50_TEST__) globalThis.__P50_FUNCTIONS__={s02Value:s02Value,issueLabel:issueLabel,sourceLabel:sourceLabel,buildCard:buildS02ResearchCard,buildPopup:buildS02ResearchPopup};

  function renderBanner(list, runtime, scope) {
    resetBannerDetails();
    var box = $('bannerCandidates');
    if (!box) return;
    s02Toolbar(box);
    if (!list || !list.length) {
      var knownEmpty = runtime && runtime.status === 'VALID' && runtime.candidate_set_complete === true;
      var scopeUnknown = scope && scope.unknown_codes && scope.unknown_codes.length;
      box.innerHTML = '<div class="banner-empty">' + (!knownEmpty || scopeUnknown ? '候选数据或样本资格待证据，不能判断为无候选' : '本次有效输入中无二板候选') + '</div>';
      ['bannerPrev', 'bannerNext'].forEach(function (id) { var b = $(id); if (b) { b.disabled = true; b.onclick = null; } });
      if ($('bannerPage')) $('bannerPage').textContent = '--';
      return;
    }

    // V5.2.1：当日未收盘/输入未就绪（runtime 非 VALID 或候选集不完整）时，不渲染空壳卡片，直接提示收盘后再试
    var readyOk = runtime && runtime.status === 'VALID' && runtime.candidate_set_complete === true;
    if (!readyOk) {
      var dd = '';
      try { var mv0 = S02Plan.model(list[0]); var dv0 = (mv0.v && mv0.v.trade_date) || ''; dd = String(dv0).replace(/-/g, ''); } catch (e) { dd = ''; }
      var dtxt = /^\d{8}$/.test(dd) ? dd.slice(4, 6) + '.' + dd.slice(6, 8) : '今日';
      box.innerHTML = '<div class="banner-empty"><div style="font-size:15px;font-weight:600;color:#f0b429;margin-bottom:6px;">' + dtxt + ' 未收盘 / 当日数据未就绪</div><div style="font-size:13px;">收盘证据与市场样本尚未核实（状态 ' + String(runtime && runtime.status || '未知') + '），暂不能统计分析，请收盘后再试。</div></div>';
      ['bannerPrev', 'bannerNext'].forEach(function (id2) { var b2 = $(id2); if (b2) { b2.disabled = true; b2.onclick = null; } });
      if ($('bannerPage')) $('bannerPage').textContent = '--';
      return;
    }

    // 评级颜色
    function gradeColor(g) {
      if (g === 'S') return '#ff4d4f';
      if (g === 'A') return '#fa8c16';
      if (g === 'B') return '#fadb14';
      if (g === 'C') return '#60a5fa';
      return '#8c8c8c';
    }

    // V5.2.1：资格优先——ELIGIBLE 在前并按研究分降序；EXCLUDED/待核沉底且不进前三、不发奖牌
    list = list.slice().sort(function (a, b) {
      function cardRank(x) {
        var m = null, sc = -Infinity, q = '';
        try { m = S02Plan.model(x); } catch (e) { m = null; }
        if (m) {
          if (typeof m.score === 'number' && isFinite(m.score)) sc = m.score;
          q = (m.v && m.v.screening && m.v.screening.strategy_status) || '';
        }
        return { group: q === 'ELIGIBLE' ? 0 : 1, score: sc };
      }
      var ra = cardRank(a), rb = cardRank(b);
      if (ra.group !== rb.group) return ra.group - rb.group;
      return rb.score - ra.score;
    });
    box.innerHTML = '<div class="banner-track">' + list.map(function (r, i) {
      return buildS02ResearchCard(r,i);
    }).join('') + '</div>';
    // 奖牌仅发给资格通过(ELIGIBLE)的前三张；EXCLUDED/待核不发牌（合格不足3只时也不错发）
    (function () {
      var track = box.querySelector('.banner-track'); if (!track) return;
      var medalCls = ['bc-gold','bc-silver','bc-bronze'], medalNo = ['1','2','3'],
          medalTitle = ['今日最高分','第2名','第3名'], rankByCode = {}, eligibleSeen = 0;
      list.forEach(function (r) {
        var qq = '';
        try { var mm = S02Plan.model(r); qq = ((mm.v && mm.v.screening && mm.v.screening.strategy_status) || ''); } catch (e) { qq = ''; }
        if (qq === 'ELIGIBLE' && eligibleSeen < 3) { rankByCode[String(r.code)] = eligibleSeen; eligibleSeen++; }
      });
      var cards = track.querySelectorAll('.bc-card');
      for (var ci = 0; ci < cards.length; ci++) {
        var card = cards[ci], oldM = card.querySelector('.bc-medal');
        if (oldM && oldM.parentNode) oldM.parentNode.removeChild(oldM);
        var code = String(card.getAttribute('data-code') || '');
        if (Object.prototype.hasOwnProperty.call(rankByCode, code)) {
          var k = rankByCode[code], span = document.createElement('span');
          span.className = 'bc-medal ' + medalCls[k]; span.title = medalTitle[k]; span.textContent = medalNo[k];
          card.insertBefore(span, card.firstChild);
        }
      }
    })();

    // 横幅级浮层：点击卡片时在该卡片正下方显示完整评分
    var popup = $('bannerPopup');
    var activeCard = null;
    var hideTimer = null;
    var popupRequestGeneration = 0;
    bannerCleanup = function () { if (hideTimer) clearTimeout(hideTimer); popupRequestGeneration++; activeCard = null; };

    function positionPopup(card) {
      var cr=card.getBoundingClientRect(), vw=window.innerWidth, vh=window.innerHeight;
      var w=Math.min(680,Math.max(240,vw-24));
      popup.style.position='fixed';popup.style.width=w+'px';popup.style.maxWidth='calc(100vw - 24px)';
      popup.style.left='50%';popup.style.top='50%';popup.style.right='auto';popup.style.bottom='auto';popup.style.margin='0';popup.style.transform='translate(-50%, -50%)';/* 5535_POSITION_POPUP_CENTER_FINAL */
      popup.style.maxHeight=Math.floor(vh*.65)+'px';popup.style.overflowY='auto';popup.style.zIndex='10000';
      popup.setAttribute('role','dialog');popup.setAttribute('aria-label','预案研究详情');popup.setAttribute('tabindex','-1');
    }

    function cancelHide() {
      if (hideTimer) {
        clearTimeout(hideTimer);
        hideTimer = null;
      }
    }

    function scheduleHide() {
      cancelHide();
      // 5535_POPUP_NO_AUTO_HIDE: 不自动隐藏 popup，只有用户主动点击关闭或按 Escape 才会关闭
      // hideTimer = setTimeout(function () {
      //   popup.classList.remove('show');
      //   activeCard = null;
      //   hideTimer = null;
      // }, 250);
    }

    function buildPopupHTML(r) {
      return buildS02ResearchPopup(r);
    }

    function popupCloseButton() {
      return '<button type="button" class="p50-close" aria-label="关闭研究详情" style="float:right;min-width:44px;min-height:44px">关闭</button>';
    }

    function bindPopupClose() {
      var close = popup && popup.querySelector('.p50-close');
      if (close) close.onclick = closePopup;
    }

    function isCurrentPopup(card, generation, date, code) {
      return activeCard === card && popupRequestGeneration === generation &&
        LAST_RENDERED_DATE === date && String(card.getAttribute('data-code') || '') === code;
    }

    function openPopup(card) {
      cancelHide();
      var idx = parseInt(card.getAttribute('data-idx'), 10);
      var r = list[idx];
      if (!r) return;
      if (!popup || !document.querySelector('.banner')) return;
      var date = LAST_RENDERED_DATE;
      var code = String(card.getAttribute('data-code') || r.code || '');
      if (!/^\d{8}$/.test(date) || !code) return;
      var generation = ++popupRequestGeneration;
      activeCard = card;
      popup.innerHTML = popupCloseButton() + '<div class="banner-empty" role="status">正在加载完整研究详情...</div>';
      bindPopupClose();
      positionPopup(card);
      popup.classList.add('show');
      popup.focus({preventScroll:true});

      fetch('/api/cockpit/candidate-detail?date=' + encodeURIComponent(date) + '&code=' + encodeURIComponent(code), {
        cache: 'no-store', credentials: 'same-origin'
      }).then(function (response) {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.json();
      }).then(function (payload) {
        if (!payload || payload.date !== date || String(payload.code) !== code || !payload.candidate || String(payload.candidate.code) !== code) {
          throw new Error('candidate detail response did not match the selected card');
        }
        if (!isCurrentPopup(card, generation, date, code)) return;
        list[idx] = payload.candidate;
        popup.innerHTML = popupCloseButton() + buildPopupHTML(payload.candidate);
        bindPopupClose();
        positionPopup(card);
      }).catch(function () {
        if (!isCurrentPopup(card, generation, date, code)) return;
        popup.innerHTML = popupCloseButton() +
          '<div class="banner-empty" role="status">完整研究详情暂不可用，当前显示精简概览。</div>' + buildPopupHTML(r);
        bindPopupClose();
        positionPopup(card);
      });
    }
    function closePopup() {
      popupRequestGeneration++;
      if (popup) popup.classList.remove('show');
      var previous=activeCard;activeCard=null;if(previous)previous.focus({preventScroll:true});
    }

    box.querySelectorAll('.bc-card').forEach(function (card) {
      card.setAttribute('tabindex', '0');
      card.setAttribute('role', 'button');
      card.setAttribute('aria-haspopup', 'dialog');
      card.addEventListener('click', function (e) { e.stopPropagation(); openPopup(card); });
      card.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); openPopup(card); }
        if (e.key === 'Escape') { e.stopPropagation(); closePopup(); }
      });
      // 触摸：tap 打开（阻止 click 重复触发）
      // 鼠标离开卡片：延迟隐藏（给用户移到浮层的时间）
      card.addEventListener('mouseleave', function () { cancelHide(); });
      // 鼠标进入卡片：取消隐藏
      card.addEventListener('mouseenter', function () { cancelHide(); });
    });

    // 浮层交互：鼠标/触摸在浮层上时保持显示
    if (popup) {
      popup.onmouseenter = cancelHide; popup.onmouseleave = null;popup.ontouchstart=null;
    }

    // Esc 关闭
    var escHandler = function (e) { if (e.key === 'Escape') closePopup(); };
    document.addEventListener('keydown', escHandler);
    var prevCleanup = bannerCleanup;
    bannerCleanup = function () {
      if (prevCleanup) prevCleanup();
      document.removeEventListener('keydown', escHandler);
      activeCard = null;
    };

    initBannerPager(list.length);
  }

  // 三板预案横幅翻页
  var bannerState = { page: 0, perPage: 4, total: 0 };

  function initBannerPager(total) {
    // S02_NARROW_PAGER_R2: layout only. Never changes list order, scores or API data.
    var box = $('bannerCandidates');
    var track = box && box.querySelector('.banner-track');
    var prevBtn = $('bannerPrev'), nextBtn = $('bannerNext'), pageInfo = $('bannerPage');
    if (!box || !track || !prevBtn || !nextBtn || !pageInfo) return;
    var cards = Array.prototype.slice.call(track.querySelectorAll('.bc-card'));
    var initialWidth = cards[0] ? cards[0].getBoundingClientRect().width : 300;
    var preferredWidth = initialWidth > 0 ? Math.min(340, initialWidth) : 300;
    var disposed = false, frame = 0, observer = null;
    var count = cards.length; // The DOM is produced from the original list, never synthesize rows.
    var page = 0, per = 1, pages = Math.max(1, count), origin = 0;
    bannerState.total = count; bannerState.page = 0; bannerState.perPage = 1;
    var style = document.getElementById('s02-narrow-pager-style');
    if (!style) {
      style = document.createElement('style'); style.id = 's02-narrow-pager-style';
      style.textContent = '#bannerCandidates{min-width:0;box-sizing:border-box;overflow:hidden}' +
        '#bannerCandidates>.banner-track{display:flex!important;flex-wrap:nowrap!important;justify-content:flex-start!important;position:relative;min-width:0;max-width:none;margin:0;padding:0;transition:none!important}' +
        '#bannerCandidates .bc-card{box-sizing:border-box;overflow-wrap:anywhere}' +
        '@media(max-width:680px){.banner{min-width:0;max-width:calc(100vw - 24px);box-sizing:border-box}.banner-head{flex-wrap:wrap;min-width:0}.banner-head .banner-sub{white-space:normal;min-width:0;flex-basis:100%;order:3}.banner-head .banner-pager{flex:0 0 auto;max-width:100%;margin-left:auto}#bannerPrev,#bannerNext{min-width:36px;min-height:36px}}';
      (document.head || document.documentElement).appendChild(style);
    }
    function px(v) { var n = parseFloat(v); return Number.isFinite(n) ? n : 0; }
    function measure() {
      var r = box.getBoundingClientRect(), cs = getComputedStyle(box);
      var left = r.left + px(cs.borderLeftWidth) + px(cs.paddingLeft);
      var right = left + box.clientWidth - px(cs.paddingLeft) - px(cs.paddingRight);
      var visibleLeft = Math.max(left, 8), visibleRight = Math.min(right, window.innerWidth - 8);
      var available = Math.max(0, visibleRight - visibleLeft);
      if (available < 1 || !r.height && !cards.length) return null;
      origin = Math.max(0, visibleLeft - left);
      var gapStyle = getComputedStyle(track);
      var gap = px(gapStyle.columnGap === 'normal' ? gapStyle.gap : gapStyle.columnGap);
      var cw = Math.max(1, Math.floor(Math.min(preferredWidth, available) * 100) / 100);
      cards.forEach(function(card) {
        card.style.setProperty('min-width', '0px', 'important');
        card.style.setProperty('max-width', cw + 'px', 'important');
        card.style.setProperty('width', cw + 'px', 'important');
        card.style.setProperty('flex', '0 0 ' + cw + 'px', 'important');
        card.style.setProperty('box-sizing', 'border-box', 'important');
      });
      // Width and offset now include real border, padding and gap, not a fixed 310px step.
      var realWidth = cards[0] ? cards[0].getBoundingClientRect().width : cw;
      var step = cards.length > 1 ? cards[1].offsetLeft - cards[0].offsetLeft : realWidth + gap;
      if (!(step > 0)) step = realWidth + gap;
      per = Math.max(1, Math.floor((available + Math.max(0, step-realWidth) + .1) / step));
      per = Math.min(Math.max(1, count), per);
      pages = Math.max(1, Math.ceil(count / per));
      box.dataset.pagerAvailableWidth = available.toFixed(2);
      box.dataset.pagerCardWidth = realWidth.toFixed(2);
      return true;
    }
    function paint() {
      page = Math.max(0, Math.min(page, pages - 1));
      var index = page * per;
      var dx = cards[index] ? cards[index].offsetLeft - cards[0].offsetLeft : 0;
      track.style.transform = 'translateX(' + (origin - dx) + 'px)';
      pageInfo.textContent = (page + 1) + ' / ' + pages;
      pageInfo.setAttribute('aria-live', 'polite');
      prevBtn.disabled = page === 0; nextBtn.disabled = page >= pages - 1;
      prevBtn.style.opacity = prevBtn.disabled ? '0.3' : '1';
      nextBtn.style.opacity = nextBtn.disabled ? '0.3' : '1';
      cards.forEach(function(card, i) {
        var onPage = i >= index && i < Math.min(index + per, count);
        card.tabIndex = onPage ? 0 : -1;
        card.setAttribute('aria-hidden', onPage ? 'false' : 'true');
        card.dataset.pagerVisible = onPage ? 'true' : 'false';
      });
      bannerState.page = page; bannerState.perPage = per;
      box.dataset.pagerVersion = 'S02_NARROW_PAGER_R2';
      box.dataset.pagerPage = String(page);
      box.dataset.pagerPerPage = String(per);
      box.dataset.pagerPageCount = String(pages);
      box.dataset.pagerFirstIndex = String(index);
      box.dataset.pagerReady = 'true';
    }
    function goPage(next) {
      if (disposed || !document.contains(track)) return;
      if (!measure()) { box.dataset.pagerReady = 'false'; return; }
      page = next; paint();
      var popup = $('bannerPopup');
      if (popup) popup.classList.remove('show');
    }
    function resize() {
      if (disposed) return;
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(function() {
        frame = 0;
        if (disposed || !document.contains(track)) return;
        var anchor = page * per;
        if (!measure()) { box.dataset.pagerReady = 'false'; return; }
        page = Math.floor(anchor / per); paint();
      });
    }
    function onKey(e) {
      if (!e.target.closest || !e.target.closest('.bc-card')) return;
      var next = page;
      if (e.key === 'ArrowRight') next++;
      else if (e.key === 'ArrowLeft') next--;
      else if (e.key === 'Home') next = 0;
      else if (e.key === 'End') next = pages-1;
      else return;
      e.preventDefault(); goPage(next);
      if (cards[page*per]) cards[page*per].focus({preventScroll:true});
    }
    prevBtn.onclick = function() { goPage(page-1); };
    nextBtn.onclick = function() { goPage(page+1); };
    box.addEventListener('keydown', onKey);
    bannerResizeHandler = resize; window.addEventListener('resize', resize);
    if (typeof ResizeObserver === 'function') {
      var lastWidth = -1;
      observer = new ResizeObserver(function(entries) {
        var w = entries[0] && entries[0].contentRect.width;
        if (Number.isFinite(w) && Math.abs(w-lastWidth) > .25) { lastWidth=w; resize(); }
      });
      observer.observe(box);
    }
    var previousCleanup = bannerCleanup;
    bannerCleanup = function() {
      disposed = true;
      if (frame) cancelAnimationFrame(frame);
      if (observer) observer.disconnect();
      box.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', resize);
      if (previousCleanup) previousCleanup();
    };
    goPage(0);
    resize(); // Wait one layout frame; no timer polling and no data request.
  }

  function renderPool(pool, d) {
    pool = pool || {};
    d = d || {};
    var poolFailed = (d.optional_component_errors || []).some(function (e) { return e.module === 'pool_analyzer' && e.status === 'ERROR'; });
    renderSecondPool(pool.second_board, !poolFailed && Array.isArray(pool.second_board));
    renderFirstPool(pool.first_board, !poolFailed && Array.isArray(pool.first_board));
    renderBanner(pool.tomorrow, d.three_board_runtime, d.input_evidence && d.input_evidence.scope);
  }

  // ============================================================
  // 龙头监控
  // ============================================================

  function renderLeader(leader, sourcePending) {
    leader = leader || {};
    var highest = leader.highest || {};
    var signals = leader.signals || {};
    var highBoards = leader.high_boards || [];
    var highBreak = leader.high_break || [];

    // --- 最高板卡片 ---
    var hEl = $('lmHighest');
    if (highest && highest.name) {
      var statusClass = 'sealed';
      var statusText = highest.status || '封板';
      if (highest.status === '回封') statusClass = 'resealed';
      else if (highest.status === '已炸板') statusClass = 'broken';

      var coLeaders = (highest.co_leaders && highest.co_leaders.length)
        ? '<span>并列: <span class="lm-val">' + highest.co_leaders.join('、') + '</span></span>'
        : '';

      hEl.innerHTML =
        '<div class="lm-label">' + (sourcePending ? '输入池参考 / 非完整市场最高板' : '最高板 / 空间龙头') + '</div>' +
        '<div class="lm-stock-row">' +
          '<span class="lm-stock-name">' + highest.name + '</span>' +
          '<span class="lm-board-badge">' + highest.board + '板</span>' +
          '<span class="lm-status ' + statusClass + '">' + statusText + '</span>' +
        '</div>' +
        '<div class="lm-detail">' +
          '<span>封板: <span class="lm-val">' + (highest.first_time || '--') + '</span></span>' +
          '<span>封单: <span class="lm-val">' + (highest.seal_amount || '--') + '</span></span>' +
          '<span>换手: <span class="lm-val">' + (highest.turnover || '--') + '</span></span>' +
          '<span>行业: <span class="lm-val">' + (highest.industry || '--') + '</span></span>' +
          (highest.open_count > 0 ? '<span>炸板: <span class="lm-val" style="color:var(--red)">' + highest.open_count + '次</span></span>' : '') +
          coLeaders +
        '</div>';
    } else {
      hEl.innerHTML = '<div class="lm-label">最高板 / 空间龙头</div><div style="color:var(--muted);font-size:13px;padding:8px 0;">最高板数据待证据</div>';
    }

    // --- 风险信号 ---
    var rEl = $('lmRisk');
    var riskLevel = typeof signals.risk_level === 'string' ? signals.risk_level.trim() : '';
    var riskKnown = !sourcePending && ['高', '中', '低'].indexOf(riskLevel) >= 0 &&
      !/ERROR|INVALID|PENDING|PAUSED/.test(String(leader.status || signals.status || ''));
    var riskClass = !riskKnown ? '' : (riskLevel === '高' ? 'risk-high' : (riskLevel === '中' ? 'risk-mid' : 'risk-low'));
    rEl.className = 'lm-risk ' + riskClass;
    rEl.innerHTML =
      '<div class="risk-level">' + (riskKnown ? esc(riskLevel) + '风险' : '风险待证据') + '</div>' +
      '<div class="risk-desc">' + esc(riskKnown ? (signals.risk_desc || '风险说明未提供') : (sourcePending ? '源日期或完整性未核实，原始梯队不构成当前风险等级' : '没有有效信号，不能判断为低风险')) + '</div>';

    // --- 高标股列表（3板及以上） ---
    var hbEl = $('lmHighBoards');
    if (highBoards.length > 0) {
      var hbHtml = '<span class="lm-hb-label">高标股(' + highBoards.length + '):</span>';
      highBoards.forEach(function (s) {
        var stClass = 'sealed';
        if (s.status === '回封') stClass = 'resealed';
        else if (s.status === '已炸板') stClass = 'broken';
        hbHtml +=
          '<span class="lm-hb-tag">' +
            '<span class="hb-board">' + s.board + '板</span>' +
            '<span class="hb-name">' + s.name + '</span>' +
            '<span class="hb-status ' + stClass + '">' + s.status + '</span>' +
          '</span>';
      });
      hbEl.innerHTML = hbHtml;
      hbEl.style.display = 'flex';
    } else {
      hbEl.innerHTML = '';
      hbEl.style.display = 'none';
    }

    // --- 高位炸板股 ---
    var hbrEl = $('lmHighBreak');
    if (highBreak.length > 0) {
      var hbrHtml = '<span class="lm-hbr-label">高位炸板(' + highBreak.length + '):</span>';
      highBreak.forEach(function (s) {
        hbrHtml +=
          '<span class="lm-hbr-tag">' +
            '<span class="hbr-name">' + s.name + '</span>' +
            '<span class="hbr-prev-board">昨' + s.yesterday_board + '板</span>' +
            '<span class="hbr-open-count">炸' + s.open_count + '次</span>' +
          '</span>';
      });
      hbrEl.innerHTML = hbrHtml;
      hbrEl.style.display = 'flex';
    } else {
      hbrEl.innerHTML = '';
      hbrEl.style.display = 'none';
    }
  }

  // ============================================================
  // 空数据 / 主入口 / 交易日回放
  // ============================================================

  function showEmpty(msg, title) {
    resetBannerDetails();
    CURRENT_INDEX = 0;
    syncReplayUI('');
    var el = $('emptyTip');
    if (!el) return;
    el.classList.remove('hidden');
    el.innerHTML = '<div class="empty-title">' + esc(title || '暂无仪表盘数据') + '</div>' +
      '<div class="empty-desc">' + esc(msg || '请先运行原程序生成数据，再刷新页面。') +
      (DISPLAY_COHERENT && LAST_RENDERED_DATE ? '<br>下方保留上一次成功快照 ' + esc(fmtDate(LAST_RENDERED_DATE)) + '，不是本次请求的结果。' : '<br>页面未完整渲染，不应把下方内容作为一次有效快照。') +
      '<br><button type="button" id="dashboardRetry">重试当前请求</button></div>';
    if ($('playState')) $('playState').textContent = DISPLAY_COHERENT && LAST_RENDERED_DATE ? '加载失败 · 保留上次快照' : '加载失败';
    if (!DISPLAY_COHERENT) document.documentElement.removeAttribute('data-dashboard-date');
    document.documentElement.setAttribute('data-dashboard-state', 'ERROR');
    $('dashboardRetry').onclick = function () { if (!LOADING) loadDashboard(LAST_REQUESTED_DATE); };
  }

  var AVAILABLE_DATES = [];
  var CURRENT_INDEX = 0;
  var LOADING = false;
  var LAST_RENDERED_DATE = '';
  var LAST_RENDERED_DATA = null;
  var DISPLAY_COHERENT = false;
  var LAST_REQUESTED_DATE = '';

  // A copied/legacy snapshot is readable history, not evidence that approved
  // filtering, source selection or suspended five-day rules have run. Never
  // rewrite the response or infer new market numbers to make it look current.
  function hasCurrentPolicyEvidence(d) {
    return d && d.schema_version === '5535-direct-repair-1' &&
      d.provenance && typeof d.provenance === 'object' &&
      d.input_evidence && typeof d.input_evidence === 'object' &&
      d.three_board_runtime && typeof d.three_board_runtime === 'object';
  }

  function renderSnapshotEvidence(d) {
    var provenFields = !!hasCurrentPolicyEvidence(d);
    var note = $('snapshotEvidenceNotice');
    if (!note) {
      note = document.createElement('div');
      note.id = 'snapshotEvidenceNotice';
      note.className = 'empty';
      note.setAttribute('role', 'status');
      note.style.cssText = 'margin:12px 0;padding:12px;text-align:left;font-size:13px;line-height:1.6';
      var anchor = $('emptyTip');
      if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(note, anchor.nextSibling);
    }
    var sourceMeta = d.input_evidence && d.input_evidence.source_meta;
    var sourcePending = provenFields && sourceMeta && ['today', 'previous'].some(function (key) {
      var meta = sourceMeta[key] || {};
      return meta.date_verified !== true || meta.complete !== true || !meta.source_date;
    });
    note.hidden = provenFields && !sourcePending;
    note.textContent = sourcePending ?
      '新流程已生成，但行情源日期或样本完整性尚未核实。抓到记录不等于已验证当日行情；原始候选仅作待证据参考，空值不代表市场为零。' : provenFields ? '' :
      '当前响应缺少已批准规则的生成证据：以下数据仅作历史/待核参考，不能据此确认ST与新股过滤、883900备用链或有效分母已生效。五日周期及仓位建议继续暂停，原始数据未被修改。';
    document.documentElement.setAttribute('data-policy-evidence', sourcePending ? 'FIELDS_PRESENT_SOURCE_PENDING' : provenFields ? 'FIELDS_PRESENT_NOT_MARKET_VERIFICATION' : 'UNVERIFIED_OR_LEGACY');
    return provenFields;
  }

  function renderDashboard(d) {
    // Missing sections are unknown, not zero-valued substitutes.
    renderHeader(d);
    ensureCompactTopRow();
    var hasPolicyEvidence = renderSnapshotEvidence(d);
    var shownCycle = hasPolicyEvidence ? (d.cycle || {}) : {
      status: 'PAUSED_BY_USER',
      description: '历史响应未验证按当前规则生成；五日判断暂停，不展示旧周期作为当前结论。'
    };
    var shownPosition = hasPolicyEvidence ? (d.position || {}) : {
      status: 'NOT_ENABLED', suggest: null, risk: null, evidence_pending: true,
      strategy: '五日判断及仓位依赖暂停；历史响应中的旧建议仅保留在原始数据，不作为当前操作建议。'
    };
    renderEmotionScore(d.emotion || {});
    renderMarket(d.market || {});
    renderLimit(d.limit || {}, d.smash || {}, d.history || [], d.previous_date);
    renderLadder(d.ladder || [], d.smash || {});
    renderSmash(d.smash || {}, d.smash_history || []);
    renderTrend(d.history || [], shownCycle);
    var fundCycle = d.five_day_fund_cycle ||
      (d.five_day_money_effect && d.five_day_money_effect.current) || {};
    renderTags(shownCycle, d.smash || {}, d.emotion || {}, fundCycle);
    renderMoneyEffect(d);
    render883900CacheNotice(d);
    renderPosition(shownPosition);
    renderStrategy(shownPosition, shownCycle);
    renderPool(d.pool, d);
    var leaderMeta = d.input_evidence && d.input_evidence.source_meta && d.input_evidence.source_meta.today;
    renderLeader(d.leader || {}, !!leaderMeta && (leaderMeta.date_verified !== true || leaderMeta.complete !== true));
  }

        function syncReplayUI(fallbackDate) {
    var date = AVAILABLE_DATES[CURRENT_INDEX] || fallbackDate || '';
    var sel = $('playDate');
    if (sel && sel.tagName === 'SELECT') {
        sel.innerHTML = '';
      if (!AVAILABLE_DATES.length) {
        var empty = document.createElement('option');
        empty.value = '';
        empty.textContent = '请选择日期';
        sel.appendChild(empty);
        sel.disabled = true;
      } else {
        sel.disabled = false;
      for (var i = 0; i < AVAILABLE_DATES.length; i++) {
        var o = document.createElement('option');
        o.value = AVAILABLE_DATES[i];
        o.textContent = (i === 0 ? '今日 ' : '') + fmtDate(AVAILABLE_DATES[i]);
        sel.appendChild(o);
      }
      }
      if (AVAILABLE_DATES.length) sel.value = date || AVAILABLE_DATES[0];
    } else if (sel) {
      sel.textContent = date ? fmtDate(date) : '--';
    }
    if (!AVAILABLE_DATES.length) {
      $('playState').textContent = date ? '快照日期' : '暂无快照';
      $('playState').className = 'rp-state';
      var bt0 = $('backToday'); if (bt0) bt0.style.display = 'none';
      return;
    }
    var latest = AVAILABLE_DATES[0] || '';
    $('playState').textContent = date === latest ? '最新' : '回放 ' + fmtDate(date);
    $('playState').className = 'rp-state' + (date === latest ? ' live' : ' old');
    var bt = $('backToday');
    if (bt) bt.style.display = (date === latest) ? 'none' : 'inline-flex';
  }

function loadDashboard(date) {
    var url = '/api/cockpit' + (date ? ('?date=' + encodeURIComponent(date)) : '');
    var requestStarted = performance.now();
    var prefetched = !date && window.__5535_BOOT_FETCH__;
    if (prefetched) window.__5535_BOOT_FETCH__ = null;
    var networkDone = null;
    LAST_REQUESTED_DATE = date || '';
    LOADING = true;
    document.documentElement.setAttribute('data-dashboard-state', 'LOADING');
    document.documentElement.removeAttribute('data-cockpit-ready');
    return (prefetched || fetch(url, {cache:'no-store'}))
      .then(function (r) {
        networkDone = performance.now();
        if (r.ok === false) {
          // Surface the database-only error code (e.g. DB_ROUTE_NOT_MATERIALIZED)
          // instead of a bare HTTP status.
          return r.json().catch(function () { return {}; }).then(function (body) {
            var msg = (body && (body.error || body.code))
              ? ((body.error || '') + (body.code ? ' (' + body.code + ')' : ''))
              : ('HTTP ' + r.status);
            throw new Error(msg);
          });
        }
        return r.json();
      })
      .then(function (d) {
        // Load the V2 money-effect fact alongside the dashboard snapshot. A
        // missing/incomplete fact must leave the panel pending, never invent a
        // value from a later trading day.
        return loadMoneyEffectFact(d && d.date).then(function (money) {
          if (money) d.five_day_money_effect = money;
          return d;
        });
      })
      .then(function (d) {
        LOADING = false;
        if (!d || typeof d !== 'object' || !d.date) {
          showEmpty(d && d.error ? d.error : '接口没有返回有效快照日期。', '仪表盘数据待证据');
          return false;
        }
        if (date && fmtDate(d.date) !== fmtDate(date)) {
          showEmpty('请求日期与返回快照日期不一致，未将返回数据作为该日快照展示。', '快照日期不匹配');
          return false;
        }
        try {
          if (Array.isArray(d.navigation_dates)) AVAILABLE_DATES = d.navigation_dates;
          DISPLAY_COHERENT = false;
          var renderStarted=performance.now();
          renderDashboard(d);
          var index = AVAILABLE_DATES.indexOf(date || d.date);
          if (index >= 0) CURRENT_INDEX = index;
          LAST_RENDERED_DATE = d.date;
          LAST_RENDERED_DATA = d;
          DISPLAY_COHERENT = true;
          syncReplayUI(d.date);
          if ($('emptyTip')) $('emptyTip').classList.add('hidden');
          document.documentElement.setAttribute('data-dashboard-state', 'RENDERED');
          document.documentElement.setAttribute('data-dashboard-date', String(d.date));
          var renderEnded=performance.now(), firstReady=!window.__5535_COCKPIT_METRICS__;
          var fontsReady=(document.fonts&&document.fonts.ready)||Promise.resolve();
          fontsReady.then(function(){requestAnimationFrame(function(){requestAnimationFrame(function(){
            if (String(d.date)!==LAST_RENDERED_DATE) return;
            var ready=performance.now();
            var m={schema:'5535_COCKPIT_READY_V1',date:d.date,transport:d.cockpit_transport||null,
              navigation_to_ready_ms:ready,request_to_ready_ms:ready-requestStarted,
              response_wait_ms:networkDone-requestStarted,render_js_ms:renderEnded-renderStarted,
              chart_count:charts.length,after_two_paint_frames:true,fonts_ready:true,initial_navigation:firstReady,
              target_ms:1000,under_one_second:(firstReady?ready:ready-requestStarted)<1000};
            window.__5535_COCKPIT_METRICS__=m;
            document.documentElement.setAttribute('data-cockpit-ready','true');
            document.documentElement.setAttribute('data-cockpit-load-ms',String(Math.round(firstReady?ready:ready-requestStarted)));
            var elapsed=firstReady?ready:ready-requestStarted;
            if(typeof performance.mark==='function')performance.mark('5535-cockpit-ready');
            window.dispatchEvent(new CustomEvent('5535:cockpit-ready',{detail:m}));
          });});});
          return true;
        } catch (err) {
          // Rendering is not atomic; restore the last complete view, not a mix of two dates.
          if (LAST_RENDERED_DATA) {
            try { renderDashboard(LAST_RENDERED_DATA); DISPLAY_COHERENT = true; }
            catch (restoreError) { DISPLAY_COHERENT = false; }
          }
          showEmpty('页面渲染失败：' + err.message + '。数据请求可能已成功，请检查实际加载的脚本和浏览器错误。', '仪表盘渲染失败');
          return false;
        }
      }, function (err) {
        LOADING = false;
        showEmpty('数据请求失败：' + err.message + '。请检查原站 API 与服务状态。', '仪表盘请求失败');
        return false;
      });
  }

  function goPrev() {
    if (!AVAILABLE_DATES.length || LOADING) return;
    if (CURRENT_INDEX < AVAILABLE_DATES.length - 1) {
      loadDashboard(AVAILABLE_DATES[CURRENT_INDEX + 1]);
    }
  }

  function goNext() {
    if (!AVAILABLE_DATES.length || LOADING) return;
    if (CURRENT_INDEX > 0) {
      loadDashboard(AVAILABLE_DATES[CURRENT_INDEX - 1]);
    }
  }

  // 883900_CACHE_NOTICE_V1: stale pixels are never declared fresh acceptance.
  var cacheRefreshTimer = null;
  function render883900CacheNotice(d) {
    var p=d.cockpit_transport||{}, state=p.cache_state, n=$('cockpitFreshness');
    if(!n){n=document.createElement('div');n.id='cockpitFreshness';n.setAttribute('role','status');n.style.cssText='font-size:12px;line-height:1.7;padding:8px 12px;border:1px solid var(--line);color:var(--gold);margin:8px 0;';
      var host=document.querySelector('main')||document.body;host.insertBefore(n,host.firstChild);}
    if(cacheRefreshTimer){clearTimeout(cacheRefreshTimer);cacheRefreshTimer=null;}
    document.documentElement.setAttribute('data-cockpit-fresh',state==='FRESH'?'true':'false');
    if(state==='FRESH'){n.style.display='none';return;}
    n.style.display='block';n.textContent='当前显示 '+fmtDate(d.date)+' 的上次完整版本；新数据视图正在后台生成，生成后自动替换。未将旧值冒充本次更新结果。';
    if(state==='STALE_REBUILD_FAILED')n.textContent='新视图生成失败，保留 '+fmtDate(d.date)+' 的上次完整数据。查看本机运行日志；没有清空历史。';
    var requested=LAST_REQUESTED_DATE;
    cacheRefreshTimer=setTimeout(function(){if(!LOADING && LAST_REQUESTED_DATE===requested)loadDashboard(requested);},2000);
  }

  function main() {
    // The bootstrap contains the SAME database date list and display snapshot.
    // It starts while HTML is parsed; no /dates -> /dashboard serial round trip.
    loadDashboard('');

    var prevBtn = $('prevDay');
    var nextBtn = $('nextDay');
    if (prevBtn) prevBtn.addEventListener('click', goPrev);
    if (nextBtn) nextBtn.addEventListener('click', goNext);

    var dateSel = $('playDate');
    if (dateSel && dateSel.tagName === 'SELECT') {
      dateSel.addEventListener('change', function () {
        if (LOADING) return;
        var v = this.value;
        if (v && v !== LAST_RENDERED_DATE) loadDashboard(v);
      });
    }
    var backToday = $('backToday');
    if (backToday) {
      backToday.addEventListener('click', function () { if (!LOADING) loadDashboard(''); });
    }


    // 更新数据按钮
    var updateBtn = $('updateBtn');
    var updateOverlay = $('updateOverlay');
    var updateClose = $('updateClose');
    var updateProgress = $('updateProgress');
    var updateResult = $('updateResult');
    var updateError = $('updateError');
    var updateTitle = $('updateTitle');
    var updatePollTimer = null;
    var updateTaskSteps = null;
    var updateCancelBtn = null;

    function ensureUpdateTaskUI() {
      if (!updateOverlay || !updateProgress) return;
      var bar = updateOverlay.querySelector('.uo-bar');
      var fill = bar && bar.querySelector('.uo-bar-fill');
      if (bar && fill) {
        bar.setAttribute('role', 'progressbar');
        bar.setAttribute('aria-label', '采集与计算进度');
        bar.setAttribute('aria-valuemin', '0');
        bar.setAttribute('aria-valuemax', '100');
        fill.style.animation = 'none';
      }
      if (!updateTaskSteps) {
        updateTaskSteps = document.createElement('ol');
        updateTaskSteps.id = 'updateTaskSteps';
        updateTaskSteps.style.cssText = 'margin:10px 0;padding-left:22px;max-height:190px;overflow:auto;font-size:12px;line-height:1.8;color:var(--muted)';
        updateProgress.after(updateTaskSteps);
      }
      if (!updateCancelBtn) {
        updateCancelBtn = document.createElement('button');
        updateCancelBtn.type = 'button';
        updateCancelBtn.id = 'updateCancelBtn';
        updateCancelBtn.textContent = '停止任务';
        updateCancelBtn.title = '停止当前采集或计算子进程，已入库证据保留';
        updateCancelBtn.style.cssText = 'margin-top:8px;min-height:36px;padding:6px 12px;border:1px solid #b84040;background:#7d2525;color:#fff;cursor:pointer';
        updateTaskSteps.after(updateCancelBtn);
        updateCancelBtn.addEventListener('click', function () {
          if (updateCancelBtn.disabled) return;
          if (!confirm('确认停止当前采集/计算任务？\n\n系统会终止当前子进程；已入库证据保留，不会伪造完成结果。')) return;
          updateCancelBtn.disabled = true;
          updateProgress.textContent = '正在请求停止当前任务...';
          fetch('/api/update/cancel', { method: 'POST', cache: 'no-store' })
            .then(function (r) { return r.json().then(function (o) { if (!r.ok) throw new Error(o.error || 'HTTP ' + r.status); return o; }); })
            .then(function (res) { renderUpdateTask(res.task_progress); })
            .catch(function (err) { updateError.textContent = '停止请求未确认：' + err.message + '。任务可能仍在运行。'; updateError.style.display = 'block'; updateCancelBtn.disabled = false; });
        });
      }
    }

    function renderUpdateTask(task) {
      if (!task) return;
      ensureUpdateTaskUI();
      updateProgress.textContent = task.message || '处理中...';
      var bar = updateOverlay && updateOverlay.querySelector('.uo-bar');
      var fill = bar && bar.querySelector('.uo-bar-fill');
      var percent = typeof task.percent === 'number' ? Math.max(0, Math.min(100, task.percent)) : 0;
      if (bar) bar.setAttribute('aria-valuenow', String(percent));
      if (fill) { fill.style.transform = 'none'; fill.style.width = percent + '%'; }
      if (updateTaskSteps) {
        updateTaskSteps.innerHTML = '';
        (task.steps || []).forEach(function (step) {
          var item = document.createElement('li');
          var prefix = step.state === 'DONE' ? '完成: ' : step.state === 'RUNNING' ? '进行中: ' : step.state === 'BLOCKED' ? '已停止: ' : '等待: ';
          item.textContent = prefix + (step.label || step.id || '未命名步骤');
          updateTaskSteps.appendChild(item);
        });
      }
      if (updateCancelBtn) {
        updateCancelBtn.disabled = !task.running || !!task.cancel_requested;
        updateCancelBtn.textContent = task.cancel_requested ? '停止请求已发送' : '停止任务';
      }
    }

    if (updateClose) {
      updateClose.addEventListener('click', function () {
        updateOverlay.classList.remove('show');
      });
    
    }

    var backfillBtn = $('backfillBtn');
    var backfillDate = $('backfillDate');
    function updateBackfillButton() {
      if (backfillBtn) backfillBtn.disabled = !backfillDate || !backfillDate.value;
    }

    function loadBackfillDates() {
      if (!backfillDate) return;
      fetch('/api/backfill/dates', {cache: 'no-store'})
        .then(function (r) { return r.json().then(function (body) { if (!r.ok) throw new Error(body.error || '交易日历不可用'); return body; }); })
        .then(function (data) {
          backfillDate.innerHTML = '';
          var placeholder = document.createElement('option');
          placeholder.value = '';
          placeholder.textContent = '请选择补录日期';
          backfillDate.appendChild(placeholder);
          (data.dates || []).slice().reverse().forEach(function (date) {
            var option = document.createElement('option');
            option.value = date;
            option.textContent = fmtDate(date);
            backfillDate.appendChild(option);
          });
          backfillDate.disabled = !(data.dates || []).length;
          updateBackfillButton();
        })
        .catch(function (err) {
          backfillDate.innerHTML = '<option value="">交易日历不可用</option>';
          backfillDate.disabled = true;
          updateBackfillButton();
          console.warn('补录交易日历加载失败：' + err.message);
        });
    }

    if (backfillBtn && !backfillBtn.dataset.backfillBound) {
      backfillBtn.dataset.backfillBound = '1';
      backfillBtn.addEventListener('click', function () {
        if (backfillBtn.classList.contains('running')) return;
        if (!backfillDate || !backfillDate.value) return;
        var targetDate = backfillDate.value;
        
        // 确认
        if (!confirm('确认补录 ' + targetDate + ' 的数据？\n\n将重新采集并计算该日的全部数据。\n\n该操作可能需要较长时间。')) return;
        
        // 重置UI
        backfillBtn.classList.add('running');
        updateOverlay.classList.add('show');
        updateTitle.textContent = '补录 ' + targetDate + ' 数据';
        updateProgress.textContent = '正在初始化...';
        ensureUpdateTaskUI();
        updateResult.style.display = 'none';
        updateError.style.display = 'none';
        
        // 触发补录
        fetch('/api/update', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({requested_date: targetDate}) })
          .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
          .then(function (res) {
            if (res.status === 'error') throw new Error(res.error || '补录未启动');
            if (res.status === 'already_running') {
              updateProgress.textContent = res.progress || '补录正在进行中...';
            }
            // 开始轮询进度
            startUpdatePoll();
          })
          .catch(function (err) {
            updateError.textContent = '请求失败：' + err.message;
            updateError.style.display = 'block';
            backfillBtn.classList.remove('running');
          });
      });
    }

    if (backfillDate) backfillDate.addEventListener('change', updateBackfillButton);
    // The standalone index initializer owns calendar loading. Keeping the
    // request outside this block lets the supplement control work even when
    // the dashboard snapshot request fails.

    if (updateBtn) {
      updateBtn.addEventListener('click', function () {
        if (updateBtn.classList.contains('running')) return;

        // 确认
        if (!confirm('确认更新今日数据？\n\n将执行：获取最新行情 → 计算砸盘情绪 → 计算市场情绪 → 保存历史 → 生成快照\n\n首次历史补齐可能较长；有效数据直接复用，进度写入数据库')) return;

        // 重置UI
        updateBtn.classList.add('running');
        updateOverlay.classList.add('show');
        updateTitle.textContent = '数据更新中';
        updateProgress.textContent = '正在初始化...';
        ensureUpdateTaskUI();
        updateResult.style.display = 'none';
        updateError.style.display = 'none';

        // 触发更新
        fetch('/api/update', { method: 'POST' })
          .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
          .then(function (res) {
            if (res.status === 'error') throw new Error(res.error || '更新未启动');
            if (res.status === 'already_running') {
              updateProgress.textContent = res.progress || '更新正在进行中...';
            }
            // 开始轮询进度
            startUpdatePoll();
          })
          .catch(function (err) {
            updateError.textContent = '请求失败：' + err.message;
            updateError.style.display = 'block';
            updateBtn.classList.remove('running');
          });
      });
    }

    function startUpdatePoll() {
      if (updatePollTimer) clearInterval(updatePollTimer);
      updatePollTimer = setInterval(function () {
        fetch('/api/update/status')
          .then(function (r) { return r.json(); })
          .then(function (res) {
            renderUpdateTask(res.task_progress);
            if (!res.task_progress) updateProgress.textContent = res.progress || '处理中...';

            if (res.task_progress && !res.task_progress.running && res.task_progress.result_status === 'CANCELLED') {
              clearInterval(updatePollTimer);
              updateBtn.classList.remove('running');
              if (backfillBtn) backfillBtn.classList.remove('running');
              updateTitle.textContent = '任务已停止';
              updateResult.textContent = '当前采集或计算子进程已终止；已入库证据保留，可在确认原因后重新发起。';
              updateResult.style.display = 'block';
              return;
            }

            if (res.error) {
              updateError.textContent = '更新失败：' + res.error;
              updateError.style.display = 'block';
              updateTitle.textContent = '更新失败';
              updateBtn.classList.remove('running');
              clearInterval(updatePollTimer);
              return;
            }

            if (!res.running && res.result) {
              // 更新完成
              clearInterval(updatePollTimer);
              updateBtn.classList.remove('running');
              updateTitle.textContent = res.result.status === 'DATA_PENDING' ? '仍有数据待核，原发布版本未替换' : '更新完成（不代表策略启用）';

              var r = res.result;
              var html = '<div>日期：<span class="highlight">' + r.date + '</span></div>'
                + '<div>情绪分：<span class="highlight">' + fmtNum(r.emotion_score) + '</span></div>'
                + '<div>砸盘分：<span class="highlight">' + (hasNumericValue(r.smash_score) ? Number(r.smash_score).toFixed(2) : '待证据') + '</span></div>'
                + '<div>最高板：<span class="highlight">' + (hasNumericValue(r.highest_board) ? Number(r.highest_board) + '板' : '待证据') + '（' + esc(r.highest_stock || '待证据') + '）</span></div>'
                + '<div>涨停：<span class="highlight">' + fmtNum(r.limit_up_count) + '</span> 只 / 跌停：' + fmtNum(r.limit_down_count) + ' 只</div>'
                + '<div>周期：<span class="highlight">' + esc(r.cycle_stage || '待证据') + '</span></div>'
                + '<div>耗时：' + r.duration + ' 秒</div>'
                + '<div style="margin-top:8px;color:var(--gold);cursor:pointer;" onclick="location.reload()">↻ 点击刷新页面查看最新数据</div>';
              updateResult.innerHTML = html;
              updateResult.style.display = 'block';
              // Refresh the selected dashboard after a completed backfill so
              // the new position advice replaces the stale "待证据" view.
              // Keep an open research popup untouched; the user closes it
              // explicitly, matching the polling interaction contract.
              var detailPopup = $('bannerPopup');
              var popupOpen = !!(detailPopup && detailPopup.classList.contains('show'));
              var selectedDate = LAST_REQUESTED_DATE || LAST_RENDERED_DATE;
              if (!popupOpen && r.date && (!selectedDate || fmtDate(selectedDate) === fmtDate(r.date))) {
                setTimeout(function () {
                  if (!LOADING) loadDashboard(r.date);
                }, 250);
              }
            } else if (!res.running && res.task_progress) {
              clearInterval(updatePollTimer);
              updateBtn.classList.remove('running');
              if (backfillBtn) backfillBtn.classList.remove('running');
            }
          })
          .catch(function () {
            // 轮询失败，忽略
          });
      }, 1500);
    }
  }

  window.addEventListener('resize', function () {
    charts.forEach(function (c) { c.resize(); });
  });

  window.__5535ChartInstances = function(){return charts.slice();};
  main();

  // ===== V5.2.1 块外补丁：删除S02卡片浮层关闭按钮 + 点击浮层外自动关闭 =====
  (function(){
    // 删除 .p50-close 按钮
    function killCloseBtn(){
      document.querySelectorAll('.p50-close').forEach(function(b){ b.remove(); });
    }
    // 监听 DOM 变化，新出现的浮层就删按钮
    var mo = new MutationObserver(function(){
      killCloseBtn();
    });
    mo.observe(document.body, {childList:true, subtree:true});
    // 点击浮层外区域关闭
    document.addEventListener('click', function(e){
      var pops = document.querySelectorAll('.p50-popup.show, [class*="popup"].show');
      pops.forEach(function(pop){
        if (pop.contains(e.target)) return;
        if (e.target.closest && e.target.closest('.bc-card')) return;
        pop.classList.remove('show');
      });
    });
  })();

  // Keep a user-opened S02 detail visible across a same-date background redraw.
  (function preserveS02PopupAcrossRefresh() {
    var intent = null, queued = false;
    function popup() { return document.getElementById('bannerPopup'); }
    function date() { return String(document.documentElement.getAttribute('data-dashboard-date') || '').replace(/-/g, ''); }
    function clearWhenClosed() {
      setTimeout(function () { var pane = popup(); if (!pane || !pane.classList.contains('show')) intent = null; }, 0);
    }
    function restore() {
      queued = false;
      var pane = popup();
      if (!intent || !pane || pane.classList.contains('show')) return;
      if (date() !== intent.date) { intent = null; return; }
      var cards = document.querySelectorAll('#bannerCandidates .bc-card');
      for (var i = 0; i < cards.length; i++) {
        if (String(cards[i].getAttribute('data-code') || '') === intent.code) { cards[i].click(); return; }
      }
      intent = null;
    }
    function queueRestore() {
      if (queued || !intent) return;
      queued = true;
      requestAnimationFrame(function () { requestAnimationFrame(restore); });
    }
    document.addEventListener('click', function (event) {
      var card = event.target.closest && event.target.closest('#bannerCandidates .bc-card');
      if (!card) return;
      var code = String(card.getAttribute('data-code') || '');
      var currentDate = date();
      intent = /^\d{6}$/.test(code) && /^\d{8}$/.test(currentDate) ? { code: code, date: currentDate } : null;
    }, true);
    document.addEventListener('click', clearWhenClosed);
    document.addEventListener('keydown', function (event) { if (event.key === 'Escape') clearWhenClosed(); });
    var pane = popup();
    if (pane) new MutationObserver(queueRestore).observe(pane, { childList: true, attributes: true, attributeFilter: ['class'] });
  })();

})();
