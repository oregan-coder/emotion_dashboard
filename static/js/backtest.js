// A股情绪驾驶舱 V3.2 - 历史回测页面脚本
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ============================================================
  // 概览统计
  // ============================================================
  function renderOverview(ov) {
    if (!ov) return;
    var box = $('btOverview');
    var stats = [
      { label: '总交易日', value: ov.total_days, sub: ov.date_range },
      { label: '平均情绪分', value: ov.avg_emotion, cls: '' },
      { label: '最高情绪分', value: ov.max_emotion, cls: 'up', sub: ov.max_emotion_date },
      { label: '最低情绪分', value: ov.min_emotion, cls: 'down', sub: ov.min_emotion_date },
      { label: '平均涨停数', value: ov.avg_limit_up },
      { label: '平均炸板率', value: ov.avg_open_board_rate + '%' },
      { label: '平均最高板', value: ov.avg_highest_board + '板' },
      { label: '平均1进2晋级率', value: ov.avg_rate_12 + '%' },
    ];
    box.innerHTML = stats.map(function (s) {
      return '<div class="bt-stat">' +
        '<div class="label">' + s.label + '</div>' +
        '<div class="value ' + (s.cls || '') + '">' + esc(s.value) + '</div>' +
        (s.sub ? '<div class="sub">' + esc(s.sub) + '</div>' : '') +
        '</div>';
    }).join('');
  }

  // ============================================================
  // 情绪分历史走势
  // ============================================================
  function renderTrend(trend) {
    var el = $('btTrendChart');
    if (!el || !trend || !trend.dates || !trend.dates.length) return;
    var chart = echarts.init(el);
    chart.setOption({
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', backgroundColor: 'rgba(20,26,43,0.95)', borderColor: '#2b3549', textStyle: { color: '#c9d1dc', fontSize: 12 } },
      legend: { data: ['情绪分', '涨停数', '最高板'], textStyle: { color: '#8a94a6', fontSize: 11 }, top: 4 },
      grid: { left: 50, right: 50, top: 40, bottom: 30 },
      xAxis: { type: 'category', data: trend.dates, axisLabel: { color: '#8a94a6', fontSize: 11 }, axisLine: { lineStyle: { color: '#2b3549' } } },
      yAxis: [
        { type: 'value', name: '情绪分', nameTextStyle: { color: '#8a94a6', fontSize: 10 }, axisLabel: { color: '#8a94a6', fontSize: 11 }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } } },
        { type: 'value', name: '数量', nameTextStyle: { color: '#8a94a6', fontSize: 10 }, axisLabel: { color: '#8a94a6', fontSize: 11 }, splitLine: { show: false } }
      ],
      series: [
        { name: '情绪分', type: 'line', data: trend.emotion_scores, smooth: true, lineStyle: { color: '#f0b90b', width: 2 }, itemStyle: { color: '#f0b90b' }, areaStyle: { color: 'rgba(240,185,11,0.1)' }, symbol: 'circle', symbolSize: 6 },
        { name: '涨停数', type: 'bar', yAxisIndex: 1, data: trend.limit_ups, itemStyle: { color: 'rgba(246,70,93,0.6)' }, barWidth: '30%' },
        { name: '最高板', type: 'line', yAxisIndex: 1, data: trend.highest_boards, smooth: true, lineStyle: { color: '#2ebd85', width: 1.5, type: 'dashed' }, itemStyle: { color: '#2ebd85' }, symbol: 'diamond', symbolSize: 5 }
      ]
    });
    window.addEventListener('resize', function () { chart.resize(); });
  }

  // ============================================================
  // 情绪分区间回测（柱状图 + 表格）
  // ============================================================
  function renderEmotionZones(zones) {
    if (!zones || !zones.length) return;

    // 柱状图：次日上涨概率
    var el = $('btZoneChart');
    if (el) {
      var chart = echarts.init(el);
      var validZones = zones.filter(function (z) { return z.count > 0; });
      chart.setOption({
        backgroundColor: 'transparent',
        tooltip: {
          trigger: 'axis',
          backgroundColor: 'rgba(20,26,43,0.95)',
          borderColor: '#2b3549',
          textStyle: { color: '#c9d1dc', fontSize: 12 },
          formatter: function (params) {
            var z = zones[params[0].dataIndex];
            return '<b>' + z.zone + '</b><br/>' +
              '样本数: ' + z.count + ' 天<br/>' +
              '占比: ' + z.ratio + '%<br/>' +
              '次日情绪变化: ' + (z.avg_next_emotion_change > 0 ? '+' : '') + z.avg_next_emotion_change + '<br/>' +
              '次日上涨概率: ' + z.up_probability + '%';
          }
        },
        grid: { left: 50, right: 30, top: 30, bottom: 50 },
        xAxis: {
          type: 'category',
          data: zones.map(function (z) { return z.zone; }),
          axisLabel: { color: '#8a94a6', fontSize: 10, interval: 0, rotate: 15 },
          axisLine: { lineStyle: { color: '#2b3549' } }
        },
        yAxis: {
          type: 'value',
          name: '次日上涨概率(%)',
          nameTextStyle: { color: '#8a94a6', fontSize: 10 },
          max: 100,
          axisLabel: { color: '#8a94a6', fontSize: 11 },
          splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } }
        },
        series: [{
          type: 'bar',
          data: zones.map(function (z) {
            return {
              value: z.up_probability,
              itemStyle: { color: z.count > 0 ? z.color : 'rgba(100,100,100,0.3)' }
            };
          }),
          barWidth: '50%',
          label: { show: true, position: 'top', color: '#c9d1dc', fontSize: 11, formatter: function (p) { return p.value > 0 ? p.value + '%' : '-'; } }
        }]
      });
      window.addEventListener('resize', function () { chart.resize(); });
    }

    // 表格
    var tbody = $('btZoneTable').querySelector('tbody');
    tbody.innerHTML = zones.map(function (z) {
      var change = z.avg_next_emotion_change;
      var changeCls = change > 0 ? 'up' : (change < 0 ? 'down' : '');
      var changeStr = (change > 0 ? '+' : '') + change;
      return '<tr>' +
        '<td style="color:' + z.color + ';font-weight:600;">' + esc(z.zone) + '</td>' +
        '<td>' + z.count + (z.sample_enough ? '' : ' <span style="color:#f0b90b;font-size:10px;">(样本不足)</span>') + '</td>' +
        '<td>' + z.ratio + '%</td>' +
        '<td class="' + changeCls + '">' + changeStr + '</td>' +
        '<td style="font-weight:600;">' + (z.count > 0 ? z.up_probability + '%' : '-') + '</td>' +
        '</tr>';
    }).join('');
  }

  // ============================================================
  // 砸盘情绪回测
  // ============================================================
  function renderSmashBacktest(sb) {
    if (!sb || !sb.zones) return;
    var tbody = $('btSmashTable').querySelector('tbody');
    tbody.innerHTML = sb.zones.map(function (z) {
      var change = z.avg_next_change;
      var changeCls = change > 0 ? 'up' : (change < 0 ? 'down' : '');
      var changeStr = (change > 0 ? '+' : '') + change;
      return '<tr>' +
        '<td>' + esc(z.zone) + '</td>' +
        '<td>' + z.count + '</td>' +
        '<td class="' + changeCls + '">' + changeStr + '</td>' +
        '<td>' + (z.count > 0 ? z.up_prob + '%' : '-') + '</td>' +
        '</tr>';
    }).join('');

    var corrEl = $('btSmashCorr');
    if (corrEl) {
      corrEl.innerHTML = '砸盘分数与次日情绪变化相关系数: <b style="color:var(--gold);">' + sb.correlation + '</b> — ' + esc(sb.interpretation || '');
    }
  }

  // ============================================================
  // 最高板回测
  // ============================================================
  function renderHighestBacktest(hb) {
    if (!hb || !hb.length) return;
    var tbody = $('btHighestTable').querySelector('tbody');
    tbody.innerHTML = hb.map(function (h) {
      var change = h.avg_next_emotion_change;
      var changeCls = change > 0 ? 'up' : (change < 0 ? 'down' : '');
      var changeStr = (change > 0 ? '+' : '') + change;
      return '<tr>' +
        '<td style="font-weight:600;">' + esc(h.level) + '</td>' +
        '<td>' + h.count + '</td>' +
        '<td>' + (h.count > 0 ? h.avg_next_rate_12 + '%' : '-') + '</td>' +
        '<td class="' + changeCls + '">' + changeStr + '</td>' +
        '</tr>';
    }).join('');
  }

  // ============================================================
  // 主入口
  // ============================================================
  function main() {
    fetch('/api/backtest')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        // 样本不足警告
        if (data.sample_warning) {
          var w = $('btWarning');
          w.style.display = 'block';
          w.innerHTML = '⚠ 当前仅积累 ' + (data.overview ? data.overview.total_days : 0) + ' 个交易日数据，回测统计样本不足，结果仅供参考。建议积累 20+ 交易日后再做决策参考。数据每日自动沉淀。';
        }
        renderOverview(data.overview);
        renderTrend(data.trend);
        renderEmotionZones(data.emotion_zones);
        renderSmashBacktest(data.smash_backtest);
        renderHighestBacktest(data.highest_board_backtest);
      })
      .catch(function (err) {
        console.error('回测数据加载失败:', err);
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', main);
  } else {
    main();
  }
})();
