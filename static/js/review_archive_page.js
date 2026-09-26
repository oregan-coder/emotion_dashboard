/* Only the independent archive page loads this script. Never computes or saves. */
(function () {
  'use strict';
  var root = document.getElementById('themeReviewArchivePanel');
  var button = document.getElementById('archiveRead');
  var dateInput = document.getElementById('archiveDate');
  var status = document.getElementById('archiveStatus');
  if (!root || !button || !dateInput || !status) return;
  var generation = 0;
  function clear() { root.replaceChildren(); }
  button.addEventListener('click', async function () {
    var date = dateInput.value;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) { status.textContent = '请先选择要查看的研究日期。'; return; }
    var seq = ++generation; clear(); button.disabled = true; status.textContent = '正在只读加载已保存记录…';
    try {
      var response = await fetch('/api/research/theme-review?date=' + encodeURIComponent(date.replace(/-/g, '')), {cache: 'no-store'});
      var data = await response.json();
      if (seq !== generation) return;
      if (response.ok && data.state === 'READY' && data.schema === 'P48_THEME_REVIEW_PANEL_V1' && data.panel) {
        if (!window.ReviewPanel) throw new Error('renderer unavailable');
        window.ReviewPanel.mount(root, data.panel);
        status.textContent = '已读取该日期的独立存档。暂停状态不变，未进行任何写入。';
      } else if (response.status === 404) {
        status.textContent = '该日期没有对应的已保存修订，不展示其他日期的结果。';
      } else { status.textContent = '存档暂时无法读取，请查看数据与验证页或服务日志。'; }
    } catch (error) {
      if (seq === generation) { clear(); status.textContent = '存档暂时无法读取，请检查本机服务后重试。'; }
    } finally { if (seq === generation) button.disabled = false; }
  });
  dateInput.addEventListener('change', function () {
    ++generation; button.disabled = false; clear();
    status.textContent = '日期已切换，请点击查看已保存记录。';
  });
})();
