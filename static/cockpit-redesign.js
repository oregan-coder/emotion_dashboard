/* Presentation-only enhancement. It reads existing rendered DOM values and never calls an API. */
(function () {
  'use strict';
  var $ = function (selector, root) { return (root || document).querySelector(selector); };
  var esc = function (value) { return String(value == null ? '' : value).replace(/[&<>\"']/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', "'": '&#39;' })[c]; }); };

  function tagLayoutSections() {
    var grids = Array.prototype.slice.call(document.querySelectorAll('main.container > section.grid2:not(#smashMoneyTopRow)'));
    if (grids[0]) grids[0].classList.add('market-position-grid');
    if (grids[grids.length - 1]) grids[grids.length - 1].classList.add('cycle-history-grid');
  }

  function ensureKpis() {
    if ($('.cockpit-kpi-grid')) return;
    var root = $('.container');
    if (!root) return;
    var grid = document.createElement('section');
    grid.className = 'cockpit-kpi-grid';
    grid.setAttribute('aria-label', '关键决策指标');
    grid.innerHTML = [
      ['emotion', '情绪分', 'emotionScore', '市场状态', 'accent'],
      ['position', '仓位', 'positionScore', '资金周期映射', 'warn'],
      ['earning', '赚钱效应', '', '昨日涨停表现', 'up'],
      ['cycle', '资金周期', '', 'T-4 前收盘至 T 收盘', 'accent']
    ].map(function (item) {
      return '<article class="cockpit-kpi" data-kpi="' + item[0] + '" data-tone="' + item[4] + '">' +
        '<span class="cockpit-kpi-label">' + item[1] + '</span>' +
        '<strong class="cockpit-kpi-value kpi-rolling" data-kpi-value="' + item[0] + '">' + (item[2] ? '<span id="kpi-' + item[2] + '">待证据</span>' : '待证据') + '</strong>' +
        '<span class="cockpit-kpi-note">' + item[3] + '</span></article>';
    }).join('');
    var first = $('.banner', root) || root.firstElementChild;
    root.insertBefore(grid, first);
  }

  function readMoneyStats() {
    var text = ($('#moneyEffectStats') || {}).textContent || '';
    var match = text.match(/赚钱效应\s+([-+]?\d+(?:\.\d+)?%|数据不足).*?资金周期\s+([-+]?\d+(?:\.\d+)?%|数据不足)/);
    return match ? { earning: match[1], cycle: match[2] } : { earning: '待证据', cycle: '待证据' };
  }

  function parseMetric(value) {
    var match = String(value == null ? '' : value).trim().match(/^([+-]?\d+(?:\.\d+)?)(.*)$/);
    if (!match) return null;
    var number = Number(match[1]);
    return Number.isFinite(number) ? { number: number, suffix: match[2], decimals: (match[1].split('.')[1] || '').length } : null;
  }

  function formatMetric(value, decimals, suffix) {
    return value.toFixed(decimals).replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1') + suffix;
  }

  function animateMetric(node, next) {
    if (!node || node.dataset.metricText === next) return;
    node.dataset.metricText = next;
    if (node._metricFrame) cancelAnimationFrame(node._metricFrame);
    var target = parseMetric(next);
    var current = parseMetric(node.textContent);
    if (!target || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      node.textContent = next;
      return;
    }
    var from = current && current.suffix === target.suffix ? current.number : 0;
    var decimals = Math.max(target.decimals, current ? current.decimals : 0);
    var started = performance.now();
    var duration = 560;
    function tick(now) {
      var progress = Math.min(1, (now - started) / duration);
      var eased = 1 - Math.pow(1 - progress, 3);
      node.textContent = formatMetric(from + (target.number - from) * eased, decimals, target.suffix);
      if (progress < 1) node._metricFrame = requestAnimationFrame(tick);
      else node.textContent = next;
    }
    node._metricFrame = requestAnimationFrame(tick);
  }

  function syncKpis() {
    ensureKpis();
    var emotion = $('#emotionScore');
    var position = $('#positionScore');
    var money = readMoneyStats();
    var target = function (id, value) {
      var node = $('[data-kpi-value="' + id + '"]');
      var next = value || '待证据';
      if (node && node.textContent !== next) animateMetric(node, next);
    };
    target('emotion', emotion ? emotion.textContent : '待证据');
    target('position', position ? position.textContent : '待证据');
    target('earning', money.earning);
    target('cycle', money.cycle);
  }

  function enhanceFirstPool() {
    var box = $('#firstPool');
    if (!box) return;
    if ($('.first-board-table', box)) return;
    var rows = Array.prototype.slice.call(box.querySelectorAll('.pool-row'));
    if (!rows.length) return;
    var data = rows.map(function (row) {
      var name = row.querySelector('b');
      var muted = row.querySelector('.muted');
      var concepts = row.querySelector('.pool-sub');
      return { name: name ? name.textContent.trim() : '', time: muted ? muted.textContent.trim() : '', concepts: concepts ? concepts.innerHTML : '' };
    });
    var table = document.createElement('table');
    table.className = 'first-board-table';
    table.setAttribute('aria-label', '首板个股可排序列表');
    table.innerHTML = '<thead><tr>' +
      '<th scope="col"><button type="button" class="table-sort" data-sort="time" aria-sort="ascending">首封时间</button></th>' +
      '<th scope="col"><button type="button" class="table-sort" data-sort="name" aria-sort="none">名称</button></th>' +
      '<th scope="col">概念分组</th></tr></thead><tbody></tbody>';
    var tbody = $('tbody', table);
    function render(sortKey, direction) {
      data.slice().sort(function (a, b) {
        var av = sortKey === 'time' ? a.time : a.name;
        var bv = sortKey === 'time' ? b.time : b.name;
        return (av < bv ? -1 : av > bv ? 1 : 0) * direction;
      }).forEach(function (item) {
        var tr = document.createElement('tr');
        tr.innerHTML = '<td class="table-time">' + esc(item.time) + '</td><td><strong>' + esc(item.name) + '</strong></td><td class="table-concepts">' + item.concepts + '</td>';
        tbody.appendChild(tr);
      });
    }
    render('time', 1);
    table.addEventListener('click', function (event) {
      var button = event.target.closest('.table-sort');
      if (!button) return;
      var key = button.getAttribute('data-sort');
      var descending = button.getAttribute('aria-sort') === 'ascending';
      Array.prototype.forEach.call(table.querySelectorAll('.table-sort'), function (other) { other.setAttribute('aria-sort', 'none'); });
      button.setAttribute('aria-sort', descending ? 'descending' : 'ascending');
      tbody.replaceChildren();
      render(key, descending ? -1 : 1);
    });
    box.replaceChildren(table);
  }

  function start() {
    tagLayoutSections();
    ensureKpis();
    syncKpis();
    var observer = new MutationObserver(function (records) {
      var relevant = records.some(function (record) {
        var node = record.target && (record.target.nodeType === 1 ? record.target : record.target.parentElement);
        return !(node && node.closest && node.closest('.cockpit-kpi-grid'));
      });
      if (relevant) {
        syncKpis();
        enhanceFirstPool();
      }
    });
    observer.observe(document.body, { subtree: true, childList: true, characterData: true });
    enhanceFirstPool();
    window.setInterval(function () { syncKpis(); enhanceFirstPool(); }, 800);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
