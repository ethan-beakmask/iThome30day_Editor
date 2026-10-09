/* 預覽 iframe 內的表格就地編輯互動。 */

(function () {
  let tables = [];
  let currentCell = null;
  let activeEdit = null;
  let hoverTable = null;
  let toolbar = null;
  let hideTimer = null;

  function setupPreviewTables(nextTables, focus) {
    tables = JSON.parse(JSON.stringify(nextTables || []));
    currentCell = null;
    activeEdit = null;
    ensureToolbar();
    document.querySelectorAll('table[data-table-index]').forEach(prepareTable);
    if (focus) {
      window.setTimeout(function () {
        const cell = findCell(focus.index, focus.row, focus.col);
        if (cell) beginEdit(cell, true);
      }, 0);
    }
  }

  function ensureToolbar() {
    if (toolbar) return;
    toolbar = document.createElement('div');
    toolbar.className = 'ie-table-toolbar btn-group';
    toolbar.style.display = 'none';
    const actions = [
      ['上方插入列', insertRowAbove],
      ['下方插入列', insertRowBelow],
      ['刪除列', deleteRow],
      ['左方插入欄', insertColumnLeft],
      ['右方插入欄', insertColumnRight],
      ['刪除欄', deleteColumn],
      ['對齊：靠左', cycleAlign],
    ];
    actions.forEach(function (item) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn btn-default btn-xs';
      button.textContent = item[0];
      button.addEventListener('mousedown', function (event) {
        event.preventDefault();
      });
      button.addEventListener('click', function (event) {
        event.preventDefault();
        item[1]();
      });
      toolbar.appendChild(button);
    });
    document.body.appendChild(toolbar);
    toolbar.addEventListener('mouseenter', function () {
      clearTimeout(hideTimer);
    });
    toolbar.addEventListener('mouseleave', function () {
      if (!activeEdit) scheduleHideToolbar();
    });
    window.addEventListener('scroll', positionToolbar, true);
    window.addEventListener('resize', positionToolbar);
  }

  function prepareTable(table) {
    const index = Number(table.dataset.tableIndex);
    table.classList.add('ie-table');
    table.addEventListener('mouseenter', function () {
      hoverTable = table;
      showToolbar(table);
    });
    table.addEventListener('mouseleave', function () {
      if (!activeEdit) scheduleHideToolbar();
    });
    table.querySelectorAll('th,td').forEach(function (cell) {
      const row = cell.tagName.toLowerCase() === 'th' ? -1 : bodyRowIndex(cell);
      const col = cell.cellIndex;
      cell.classList.add('ie-cell');
      cell.dataset.tableIndex = String(index);
      cell.dataset.row = String(row);
      cell.dataset.col = String(col);
      cell.addEventListener('click', function () {
        currentCell = {index: index, row: row, col: col};
        showToolbar(table);
        beginEdit(cell, false);
      });
    });
  }

  function bodyRowIndex(cell) {
    const row = cell.parentElement;
    const tbody = row.closest('tbody');
    if (!tbody) return -1;
    return Array.prototype.indexOf.call(tbody.querySelectorAll('tr'), row);
  }

  function beginEdit(cell, selectAll) {
    if (activeEdit && activeEdit.cell !== cell) {
      commitEdit(null);
    }
    const index = Number(cell.dataset.tableIndex);
    const row = Number(cell.dataset.row);
    const col = Number(cell.dataset.col);
    const value = cellValue(index, row, col);
    const originalHtml = cell.innerHTML;
    const textarea = document.createElement('textarea');
    textarea.rows = 1;
    textarea.className = 'ie-cell-editor';
    textarea.value = value;
    cell.innerHTML = '';
    cell.appendChild(textarea);
    activeEdit = {cell: cell, index: index, row: row, col: col, value: value, originalHtml: originalHtml, done: false};
    currentCell = {index: index, row: row, col: col};
    autoGrow(textarea);
    textarea.focus();
    if (selectAll) textarea.select();

    textarea.addEventListener('input', function () {
      autoGrow(textarea);
    });
    textarea.addEventListener('keydown', function (event) {
      if (event.key === 'Enter') {
        event.preventDefault();
        if (!event.shiftKey) commitEdit(null);
      } else if (event.key === 'Escape') {
        event.preventDefault();
        cancelEdit();
      } else if (event.key === 'Tab') {
        event.preventDefault();
        const focus = nextFocus(activeEdit.index, activeEdit.row, activeEdit.col, event.shiftKey);
        commitEdit(focus);
      }
    });
    textarea.addEventListener('blur', function () {
      commitEdit(null);
    });
  }

  function autoGrow(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = textarea.scrollHeight + 'px';
  }

  function commitEdit(focus) {
    if (!activeEdit || activeEdit.done) return;
    activeEdit.done = true;
    const textarea = activeEdit.cell.querySelector('textarea');
    const nextValue = textarea ? textarea.value : activeEdit.value;
    const changed = nextValue !== activeEdit.value;
    if (changed) {
      setCellValue(activeEdit.index, activeEdit.row, activeEdit.col, nextValue);
      postTableUpdate(activeEdit.index, focus);
    } else if (focus) {
      postTableUpdate(activeEdit.index, focus);
    } else {
      activeEdit.cell.innerHTML = activeEdit.originalHtml;
    }
    activeEdit = null;
  }

  function cancelEdit() {
    if (!activeEdit) return;
    activeEdit.done = true;
    activeEdit.cell.innerHTML = activeEdit.originalHtml;
    activeEdit = null;
  }

  function cellValue(index, row, col) {
    const table = tables[index];
    if (!table) return '';
    if (row < 0) return table.header[col] || '';
    return table.rows[row] && table.rows[row][col] ? table.rows[row][col] : '';
  }

  function setCellValue(index, row, col, value) {
    const table = tables[index];
    if (!table) return;
    if (row < 0) table.header[col] = value;
    else {
      while (table.rows.length <= row) table.rows.push(emptyRow(table.header.length));
      table.rows[row][col] = value;
    }
  }

  function postTableUpdate(index, focus) {
    const table = tables[index];
    if (!table) return;
    parent.postMessage({
      type: 'table-update',
      index: index,
      aligns: table.aligns,
      header: table.header,
      rows: table.rows,
      focus: focus,
    }, '*');
  }

  function nextFocus(index, row, col, reverse) {
    const table = tables[index];
    const lastCol = table.header.length - 1;
    if (reverse) {
      if (row < 0 && col <= 0) return {index: index, row: -1, col: 0};
      if (col > 0) return {index: index, row: row, col: col - 1};
      return {index: index, row: row - 1, col: lastCol};
    }
    if (col < lastCol) return {index: index, row: row, col: col + 1};
    if (row < table.rows.length - 1) return {index: index, row: row + 1, col: 0};
    table.rows.push(emptyRow(table.header.length));
    return {index: index, row: row + 1, col: 0};
  }

  function emptyRow(count) {
    return Array.from({length: count}, function () {
      return '';
    });
  }

  function selectedTarget() {
    const tableEl = hoverTable || document.querySelector('table[data-table-index]');
    if (!tableEl) return null;
    const index = Number(tableEl.dataset.tableIndex);
    const table = tables[index];
    if (!table) return null;
    if (!currentCell || currentCell.index !== index) {
      currentCell = {index: index, row: table.rows.length ? table.rows.length - 1 : -1, col: Math.max(0, table.header.length - 1)};
    }
    return {index: index, table: table, row: currentCell.row, col: currentCell.col};
  }

  function insertRowAbove() {
    const target = selectedTarget();
    if (!target) return;
    const row = target.row < 0 ? 0 : target.row;
    target.table.rows.splice(row, 0, emptyRow(target.table.header.length));
    postTableUpdate(target.index, {index: target.index, row: row, col: target.col});
  }

  function insertRowBelow() {
    const target = selectedTarget();
    if (!target) return;
    const row = target.row < 0 ? 0 : target.row + 1;
    target.table.rows.splice(row, 0, emptyRow(target.table.header.length));
    postTableUpdate(target.index, {index: target.index, row: row, col: target.col});
  }

  function deleteRow() {
    const target = selectedTarget();
    if (!target || target.row < 0 || target.table.rows.length === 0) return;
    target.table.rows.splice(target.row, 1);
    const row = Math.min(target.row, target.table.rows.length - 1);
    postTableUpdate(target.index, {index: target.index, row: row < 0 ? -1 : row, col: target.col});
  }

  function insertColumnLeft() {
    const target = selectedTarget();
    if (!target) return;
    insertColumn(target, target.col);
  }

  function insertColumnRight() {
    const target = selectedTarget();
    if (!target) return;
    insertColumn(target, target.col + 1);
  }

  function insertColumn(target, col) {
    target.table.header.splice(col, 0, '欄位' + (target.table.header.length + 1));
    target.table.aligns.splice(col, 0, 'left');
    target.table.rows.forEach(function (row) {
      row.splice(col, 0, '');
    });
    postTableUpdate(target.index, {index: target.index, row: target.row, col: col});
  }

  function deleteColumn() {
    const target = selectedTarget();
    if (!target || target.table.header.length <= 1) return;
    target.table.header.splice(target.col, 1);
    target.table.aligns.splice(target.col, 1);
    target.table.rows.forEach(function (row) {
      row.splice(target.col, 1);
    });
    const col = Math.min(target.col, target.table.header.length - 1);
    postTableUpdate(target.index, {index: target.index, row: target.row, col: col});
  }

  function cycleAlign() {
    const target = selectedTarget();
    if (!target) return;
    const states = ['left', 'center', 'right'];
    const current = target.table.aligns[target.col] || '';
    const next = states[(states.indexOf(current) + 1) % states.length];
    target.table.aligns[target.col] = next;
    postTableUpdate(target.index, {index: target.index, row: target.row, col: target.col});
  }

  function showToolbar(table) {
    clearTimeout(hideTimer);
    hoverTable = table;
    updateAlignButton();
    positionToolbar();
    toolbar.style.display = 'block';
  }

  function scheduleHideToolbar() {
    clearTimeout(hideTimer);
    hideTimer = window.setTimeout(hideToolbar, 160);
  }

  function hideToolbar() {
    hoverTable = null;
    if (toolbar) toolbar.style.display = 'none';
  }

  function positionToolbar() {
    if (!toolbar || !hoverTable) return;
    const rect = hoverTable.getBoundingClientRect();
    // 工具列放在表格左上方；上方空間不足時改放表格下方，避免壓到表頭
    const above = rect.top + window.scrollY - toolbar.offsetHeight - 4;
    toolbar.style.top = (above >= 0 ? above : rect.bottom + window.scrollY + 4) + 'px';
    toolbar.style.left = Math.max(0, rect.left + window.scrollX) + 'px';
  }

  function updateAlignButton() {
    const target = selectedTarget();
    if (!target || !toolbar) return;
    const button = toolbar.querySelector('button:last-child');
    const labels = {left: '靠左', center: '置中', right: '靠右', '': '未設定'};
    button.textContent = '對齊：' + labels[target.table.aligns[target.col] || ''];
  }

  function findCell(index, row, col) {
    return document.querySelector('table[data-table-index="' + index + '"] .ie-cell[data-row="' + row + '"][data-col="' + col + '"]');
  }

  window.setupPreviewTables = setupPreviewTables;
})();
