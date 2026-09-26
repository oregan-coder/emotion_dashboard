/* Framework-neutral, dependency-free read-only component. No fetch, save or score calculation. */
(function (global) {
  'use strict';
  let instanceCounter = 0;
  const MISSING = '—（缺项）';
  const format = value => value === null || value === undefined ? MISSING : Number(value).toFixed(2);
  const text = value => value === null || value === undefined || value === '' ? '未提供' : String(value);
  function node(tag, content, className) {
    const e = document.createElement(tag);
    if (content !== undefined && content !== null) e.textContent = String(content);
    if (className) e.className = className;
    return e;
  }
  function pill(content, variant) { return node('span', content, 'rp-pill ' + (variant || '')); }
  function datum(label, value) {
    const e = node('div', null, 'rp-datum');
    e.append(node('span', label, 'rp-label'), node('strong', value));
    return e;
  }
  function table(headers, rows, className) {
    const wrap = node('div', null, 'rp-scroll');
    wrap.tabIndex = 0;
    wrap.setAttribute('role', 'region');
    wrap.setAttribute('aria-label', '可横向滚动的数据表');
    const t = node('table', null, className || '');
    const head = node('thead'), tr = node('tr');
    headers.forEach(h => { const th = node('th', h); th.scope = 'col'; tr.append(th); });
    head.append(tr); t.append(head);
    const body = node('tbody');
    rows.forEach(cells => {
      const row = node('tr');
      cells.forEach(c => { const td = node('td'); td.append(c instanceof Node ? c : node('span', c)); row.append(td); });
      body.append(row);
    });
    t.append(body); wrap.append(t); return wrap;
  }
  function disclosure(label, content) {
    const d = node('details'); d.append(node('summary', label), content); return d;
  }
  function originalFactor(row, id) { return row.original.theme_factors.find(f => f.factor_id === id); }
  function role(r) { return ({core: '龙头／最强', peripheral: '普通跟随', unranked: '角色未定', weakly_related: '弱关联'})[r] || text(r); }
  function seal(value) {
    const v = String(value === null || value === undefined ? '' : value);
    return /^\d{6}$/.test(v) ? v.slice(0, 2) + ':' + v.slice(2, 4) + ':' + v.slice(4, 6) : text(value);
  }
  function referenceDetails(f) {
    const box = node('div', null, 'rp-factor');
    const title = node('div', null, 'rp-factor-title');
    title.append(node('h4', f.factor_id + ' · ' + f.name), node('strong', format(f.display_score) + ' / ' + f.max_score));
    box.append(title, node('p', f.complete ? '名单已确认；角色不加分。' : '名单尚未完整确认；不展示完整名单参考分。', 'rp-muted'),
               node('p', text(f.formula), 'rp-formula'),
               node('pre', JSON.stringify(f.values, null, 2), 'rp-values'));
    if ((f.blockers || []).length || (f.pending_members || []).length) {
      box.append(node('p', '本因子阻断：' + JSON.stringify({blockers: f.blockers, pending_members: f.pending_members}), 'rp-warning'));
    }
    const members = f.member_details.map(m => [m.code, m.name, role(m.within_theme_role),
      text(m.board_count), seal(m.first_seal_time), text(m.calculation_inclusion)]);
    box.append(node('p', '明细保留剔除项；明细行数不等于有效计算人数。', 'rp-muted'));
    box.append(disclosure('查看成员明细 · ' + members.length + '条', table(['代码', '名称', '题材内角色', '板数', '首封时间', '计算纳入状态'], members)));
    box.append(node('p', text(f.reference_note), 'rp-muted'));
    return box;
  }
  function stockDetails(row) {
    const section = node('article', null, 'rp-stock');
    section.dataset.stock = row.code;
    const banner = node('div', null, 'rp-stock-banner');
    banner.append(node('h3', row.code + '  ' + row.name), pill(row.theme));
    section.append(banner);
    const columns = node('div', null, 'rp-columns');
    const original = node('section', null, 'rp-original');
    original.append(node('h4', '原研究 · 历史快照'),
      node('p', '不覆盖、不合并。下列“待补”是原记录状态，不代表本次14份名单仍待确认。', 'rp-muted'));
    const moduleRows = Object.entries(row.original.module_scores).map(([id, m]) => [id + ' · ' + m.name, format(m.score),
      format(m.known_subtotal), m.known_items + '/' + m.item_count]);
    original.append(table(['原模块', '原模块分', '已知项小计', '有效项'], moduleRows));
    const s = row.original.screening_as_stored || {};
    original.append(node('p', '原资格状态：' + text(s.strategy_status) + '（存档，不等于启用交易）', 'rp-muted'));
    const oldIssues = node('div');
    row.original.theme_factors.forEach(f => {
      oldIssues.append(node('h5', f.factor_id + ' · ' + f.name + ' · ' + text(f.data_status)),
        node('pre', (f.issues || []).join('\n'), 'rp-raw'));
    });
    original.append(disclosure('原B03/C02缺项说明（历史快照）', oldIssues));
    const reviewed = node('section', null, 'rp-reviewed');
    reviewed.append(node('h4', '事后题材复核 · 独立参考分'), referenceDetails(row.reference.B03), referenceDetails(row.reference.C02));
    columns.append(original, reviewed); section.append(columns);
    const gaps = node('div', null, 'rp-gaps');
    gaps.append(node('h4', '剩余独立缺项 · 不因本次保存自动消除'));
    row.remaining_independent_gaps.forEach(g => {
      gaps.append(disclosure(g.factor_id + ' · ' + g.name, node('pre', (g.issues || []).join('\n'), 'rp-raw')));
    });
    // The payload only lists some independent gaps. Preserve incomplete module evidence too.
    Object.entries(row.original.module_scores).filter(([, m]) => m.known_items < m.item_count && !['题材', '个股先手'].includes(m.name)).forEach(([id, m]) => {
      gaps.append(node('p', '原' + id + '模块仍有缺项：' + m.known_items + '/' + m.item_count + '；未从此回包推断具体缺失因子。', 'rp-warning'));
    });
    const sources = node('div');
    sources.append(node('p', '以下为用户提供的来源文字；未因保存成功升级为独立核验事实。', 'rp-muted'),
      node('pre', JSON.stringify(row.source_references_as_supplied, null, 2), 'rp-raw'));
    gaps.append(disclosure('题材来源与证据边界', sources));
    section.append(gaps); return section;
  }
  function mount(root, model) {
    if (!(root instanceof HTMLElement)) throw new TypeError('An HTML root is required');
    if (!model || model.schema !== 'P48_THEME_REVIEW_PANEL_V1') throw new TypeError('Unsupported panel model');
    const prefix = 'rp-' + (++instanceCounter);
    root.replaceChildren(); root.classList.add('review-panel');
    const fragment = document.createDocumentFragment();
    const head = node('header', null, 'rp-header');
    head.append(node('p', '5535 / RESEARCH REVISION', 'rp-kicker'), node('h2', model.title));
    const badgeRow = node('div', null, 'rp-badges');
    badgeRow.append(pill(model.persistence.label, model.persistence.saved ? 'rp-good' : 'rp-pending'), pill('只读展示'),
      pill('NOT_APPROVED · 未批准'), pill('NOT_ENABLED · 未启用'));
    head.append(badgeRow, node('p', '与原研究并列保留，不回写原正式分，不生成总分、推荐排名或交易权限。', 'rp-subtitle'));
    fragment.append(head);
    const note = node('div', model.persistence.note, model.source.mode === 'EXPORTED_SNAPSHOT' ? 'rp-source-note' : 'rp-read-note');
    note.setAttribute('role', 'note'); fragment.append(note);
    const counts = node('div', null, 'rp-counts');
    counts.append(datum('名单确认', model.counts.confirmed_sets + ' / ' + model.counts.total_sets),
      datum('可展示参考项', model.counts.reviewed_reference_items + ' 项'),
      datum('股票数（按代码）', model.counts.candidates + ' 只'),
      datum('原数字项计数（回包所载）', model.counts.original_numeric_items_as_supplied + ' 项'));
    fragment.append(counts);
    const meta = node('div', null, 'rp-meta');
    meta.append(datum('研究日 / 前一交易日', model.key.trade_date + ' / ' + model.key.previous_trade_date),
      datum('本次结果生成时间（不是首次保存时间）', text(model.source.report_generated_at)),
      datum('首次保存时间（仅使用真实库字段）', text(model.persistence.saved_at_as_stored)),
      datum('修订编号', model.key.review_id), datum('基准批次', model.key.base_batch_id));
    fragment.append(disclosure('修订身份、时间与读取来源', meta));
    const control = node('div', null, 'rp-controls');
    const label = node('label', '筛选股票、代码或题材');
    const search = node('input'); search.type = 'search'; search.placeholder = '例如：澳弘 / 605058 / PCB';
    label.append(search);
    const resultCount = node('span', model.rows.length + ' / ' + model.rows.length + ' 只', 'rp-muted');
    resultCount.setAttribute('aria-live', 'polite'); control.append(label, resultCount); fragment.append(control);
    fragment.append(node('p', '原分缺项保留“—”；0.00是有效参考分。按股票代码排列，不是推荐排名。窄屏可横向滚动表格。', 'rp-table-note'));
    const grid = node('div'); fragment.append(grid);
    const detailArea = node('div', null, 'rp-details-area'); fragment.append(detailArea);
    function renderRows() {
      const query = search.value.trim().toLowerCase();
      const rows = model.rows.filter(r => (r.code + ' ' + r.name + ' ' + r.theme).toLowerCase().includes(query));
      resultCount.textContent = rows.length + ' / ' + model.rows.length + ' 只';
      grid.replaceChildren(); detailArea.replaceChildren();
      if (!rows.length) { grid.append(node('p', '没有符合筛选条件的股票。没有修改或删除研究记录。', 'rp-empty')); return; }
      const cells = rows.map(row => {
        const button = node('button', '展开对照'); button.type = 'button';
        button.setAttribute('aria-expanded', 'false');
        button.setAttribute('aria-label', '展开' + row.name + '的原研究与复核明细');
        const id = prefix + '-detail-' + row.code;
        button.setAttribute('aria-controls', id);
        button.addEventListener('click', () => {
          const existing = detailArea.querySelector('[data-stock="' + row.code + '"]');
          if (existing) { existing.remove(); button.textContent = '展开对照'; button.setAttribute('aria-expanded', 'false'); return; }
          const section = stockDetails(row); section.id = id; detailArea.append(section);
          button.textContent = '收起对照'; button.setAttribute('aria-expanded', 'true');
        });
        const stock = node('div', null, 'rp-stock-cell'); stock.append(node('strong', row.name), node('span', row.code, 'rp-mono'));
        return [stock, row.theme, format(originalFactor(row, 'B03').score), format(originalFactor(row, 'C02').score),
          format(row.reference.B03.display_score), format(row.reference.C02.display_score),
          (row.reference.B03.complete && row.reference.C02.complete) ? '两日已确认' : '存在未确认', button];
      });
      grid.append(table(['股票 / 代码', '已选题材', '原B03 / 18', '原C02 / 8', '复核B03 / 18', '复核C02 / 8', '名单状态', '明细'], cells, 'rp-main-table'));
    }
    search.addEventListener('input', renderRows);
    const footer = node('footer', null, 'rp-footer');
    footer.append(node('p', 'B01须另核完整题材上涨广度；B02须另核两日全市场中位数基准。本面板不补数、不替换口径。'),
      node('p', model.source.original_verification_note),
      node('p', '刷新、切换日期和展开明细只能触发读取。此组件没有重新确认、重新计算或SAVE入口。'));
    fragment.append(footer); root.append(fragment); renderRows(); root.dataset.renderReady = 'true';
    return {destroy: function () { root.replaceChildren(); delete root.dataset.renderReady; }};
  }
  global.ReviewPanel = Object.freeze({mount, formatScore: format});
})(window);
