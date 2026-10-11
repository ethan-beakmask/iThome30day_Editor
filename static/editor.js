/* 本地編輯器前端互動。 */

function articleList() {
  return {
    prefix: window.APP_PREFIX,
    articles: window.INITIAL_ARTICLES || [],
    sortField: 'updated_at',
    sortAsc: false,
    newSlug: '',
    newTitle: '',
    importPath: '',
    importSlug: '',
    importTitle: '',
    error: '',
    get sorted() {
      const rows = [...this.articles];
      rows.sort((a, b) => {
        const av = a[this.sortField] || '';
        const bv = b[this.sortField] || '';
        return this.sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
      });
      return rows;
    },
    mark(field) {
      if (this.sortField !== field) return '↕';
      return this.sortAsc ? '↑' : '↓';
    },
    sortBy(field) {
      if (this.sortField === field) this.sortAsc = !this.sortAsc;
      else {
        this.sortField = field;
        this.sortAsc = field === 'title';
      }
    },
    async createArticle() {
      this.error = '';
      const res = await fetch(this.prefix + '/api/articles', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({slug: this.newSlug, title: this.newTitle})
      });
      const data = await res.json();
      if (!data.ok) {
        this.error = data.error;
        return;
      }
      location.href = this.prefix + '/edit/' + data.article.slug;
    },
    async importArticle() {
      this.error = '';
      const res = await fetch(this.prefix + '/api/articles/import', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path: this.importPath, slug: this.importSlug, title: this.importTitle})
      });
      const data = await res.json();
      if (!data.ok) {
        this.error = data.error;
        return;
      }
      location.href = this.prefix + '/edit/' + data.article.slug;
    },
    async removeArticle(item, mode) {
      const message = mode === 'record'
        ? '只移除列表記錄，article.md 與圖片會留在 articles/' + item.slug + '/ 目錄。確定？'
        : '將刪除 articles/' + item.slug + '/ 整個目錄（含 article.md 與所有圖片），無法復原。確定？';
      if (!window.confirm(message)) return;
      const res = await fetch(this.prefix + '/api/articles/' + item.slug, {
        method: 'DELETE',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mode: mode})
      });
      const data = await res.json();
      if (!data.ok) {
        this.error = data.error || '刪除失敗';
        return;
      }
      this.articles = this.articles.filter(article => article.slug !== item.slug);
      this.error = '';
    }
  };
}

function editorApp() {
  return {
    prefix: window.APP_PREFIX,
    slug: window.ARTICLE.slug,
    title: window.ARTICLE.title,
    body: window.ARTICLE.body,
    draftUrl: window.ARTICLE.draft_url || '',
    saveStatus: '',
    dirty: false,
    renderTimer: null,
    saveTimer: null,
    savePromise: null,
    images: [],
    tables: [],
    pendingFocus: null,
    tablePopoverOpen: false,
    tableRows: 3,
    tableCols: 3,
    modalOpen: false,
    modalTitle: '',
    modalText: '',
    init() {
      this.scheduleRender();
      window.addEventListener('message', (event) => {
        if (!event.data || event.data.type !== 'table-update') return;
        this.applyTableUpdate(event.data);
      });
      window.addEventListener('keydown', (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
          event.preventDefault();
          this.saveNow();
        }
      });
      window.addEventListener('beforeunload', (event) => {
        if (!this.dirty) return;
        event.preventDefault();
        event.returnValue = '';
      });
      setInterval(() => {
        if (this.dirty) this.saveNow();
      }, 5000);
    },
    changed() {
      this.dirty = true;
      this.saveStatus = '尚未儲存';
      this.scheduleRender();
    },
    scheduleRender() {
      clearTimeout(this.renderTimer);
      this.renderTimer = setTimeout(() => this.render(), 400);
    },
    async render() {
      const res = await fetch(this.prefix + '/api/render', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({slug: this.slug, body: this.body})
      });
      const data = await res.json();
      if (!data.ok) return;
      this.images = data.images || [];
      this.tables = data.tables || [];
      // Alpine 的 reactive Proxy 不能被 postMessage 結構化複製，必須轉成純物件
      const focus = this.pendingFocus ? JSON.parse(JSON.stringify(this.pendingFocus)) : null;
      this.pendingFocus = null;
      this.$refs.preview.contentWindow.postMessage({type: 'render', html: data.html, tables: data.tables || [], focus: focus}, '*');
    },
    async saveNow() {
      // 自動儲存與手動儲存可能重疊：有儲存進行中就等它結束，仍有未存變更才再存一次
      if (this.savePromise) {
        const previous = await this.savePromise;
        if (!this.dirty) return previous;
      }
      this.savePromise = this.performSave();
      try {
        return await this.savePromise;
      } finally {
        this.savePromise = null;
      }
    },
    async performSave() {
      this.saveStatus = '儲存中';
      const res = await fetch(this.prefix + '/api/articles/' + this.slug, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({title: this.title, body: this.body, draft_url: this.draftUrl})
      });
      const data = await res.json();
      if (!data.ok) {
        this.saveStatus = data.error;
        return false;
      }
      this.dirty = false;
      this.images = data.images || this.images;
      this.saveStatus = '已儲存';
      return true;
    },
    selectedRange() {
      const el = this.$refs.textarea;
      return {start: el.selectionStart, end: el.selectionEnd, text: this.body.slice(el.selectionStart, el.selectionEnd)};
    },
    replaceSelection(text, cursorOffset) {
      const range = this.selectedRange();
      const pos = range.start + (cursorOffset === undefined ? text.length : cursorOffset);
      this.replaceRange(range.start, range.end, text, pos);
    },
    replaceRange(start, end, text, cursorPos) {
      // 透過 execCommand 改寫，讓瀏覽器原生的 Ctrl+Z / Ctrl+Y 可以反悔工具列、表格編輯等程式化修改；
      // 直接指定 textarea.value 會清掉瀏覽器的復原堆疊
      const el = this.$refs.textarea;
      // execCommand 會觸發 input 事件讓 x-model 先改掉 this.body，所以期望值必須先用舊內容算好
      const expected = this.body.slice(0, start) + text + this.body.slice(end);
      el.focus();
      el.setSelectionRange(start, end);
      let inserted = false;
      try {
        inserted = document.execCommand('insertText', false, text);
      } catch (_err) {
        inserted = false;
      }
      if (inserted && el.value === expected) {
        this.body = el.value;
      } else {
        this.body = expected;
      }
      this.changed();
      this.$nextTick(() => {
        el.focus();
        el.setSelectionRange(cursorPos, cursorPos);
      });
    },
    replaceWholeBody(newBody) {
      // 只改寫前後相同部分之間的差異區段，讓復原堆疊只記錄實際變動
      const oldBody = this.body;
      let head = 0;
      const maxHead = Math.min(oldBody.length, newBody.length);
      while (head < maxHead && oldBody[head] === newBody[head]) head += 1;
      let tail = 0;
      while (tail < maxHead - head && oldBody[oldBody.length - 1 - tail] === newBody[newBody.length - 1 - tail]) tail += 1;
      const text = newBody.slice(head, newBody.length - tail);
      this.replaceRange(head, oldBody.length - tail, text, head + text.length);
    },
    wrap(prefix, suffix) {
      const range = this.selectedRange();
      if (!range.text) {
        // 沒有圈選：只插入語法符號，游標停在符號之間
        this.replaceSelection(prefix + suffix, prefix.length);
        return;
      }
      this.replaceSelection(prefix + range.text + suffix);
    },
    linePrefix(prefix, numbered) {
      const range = this.selectedRange();
      if (!range.text) {
        this.replaceSelection(prefix);
        return;
      }
      // 空白列不加前綴也不編號；有序清單依序編號
      let index = 0;
      const lines = range.text.split('\n').map(line => {
        if (!line.trim()) return line;
        index += 1;
        return (numbered ? index + '. ' : prefix) + line;
      }).join('\n');
      this.replaceSelection(lines);
    },
    insertText(text) {
      this.replaceSelection(text);
    },
    insertCodeBlock() {
      this.replaceSelection('```\n\n```', 4);
    },
    async insertTable() {
      const cols = Math.max(1, Number(this.tableCols) || 1);
      const rowCount = Math.max(2, Number(this.tableRows) || 2);
      const header = Array.from({length: cols}, (_item, index) => '欄位' + (index + 1));
      const rows = Array.from({length: rowCount - 1}, () => Array.from({length: cols}, () => ''));
      const markdown = await this.serializeTable(Array.from({length: cols}, () => 'left'), header, rows);
      if (markdown) {
        this.insertMarkdownBlock(markdown);
        this.tablePopoverOpen = false;
      }
    },
    insertMarkdownBlock(markdown) {
      const range = this.selectedRange();
      const before = this.body.slice(0, range.start);
      const after = this.body.slice(range.end);
      let prefix = '';
      let suffix = '';
      if (before && !before.endsWith('\n\n')) prefix = before.endsWith('\n') ? '\n' : '\n\n';
      if (after && !after.startsWith('\n\n')) suffix = after.startsWith('\n') ? '\n' : '\n\n';
      this.replaceSelection(prefix + markdown + suffix);
    },
    async serializeTable(aligns, header, rows) {
      const res = await fetch(this.prefix + '/api/table/serialize', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({aligns: aligns, header: header, rows: rows})
      });
      const data = await res.json();
      if (!data.ok) {
        this.showModal('表格建立失敗', data.error);
        return '';
      }
      return data.markdown;
    },
    async applyTableUpdate(message) {
      const table = this.tables[message.index];
      if (!table) {
        this.showModal('表格更新失敗', '找不到對應的表格。');
        return;
      }
      const res = await fetch(this.prefix + '/api/table/apply', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          body: this.body,
          start_line: table.start_line,
          end_line: table.end_line,
          aligns: message.aligns,
          header: message.header,
          rows: message.rows
        })
      });
      const data = await res.json();
      if (!data.ok) {
        this.showModal('表格更新失敗', data.error);
        return;
      }
      this.pendingFocus = message.focus || null;
      this.replaceWholeBody(data.body);
    },
    async uploadPicked(event) {
      const file = event.target.files[0];
      if (file) await this.uploadFile(file);
      event.target.value = '';
    },
    async dropFiles(event) {
      for (const file of event.dataTransfer.files) await this.uploadFile(file);
    },
    async handlePaste(event) {
      for (const item of event.clipboardData.items || []) {
        if (item.type.startsWith('image/')) {
          event.preventDefault();
          await this.uploadFile(item.getAsFile());
          return;
        }
      }
      const text = event.clipboardData.getData('text/plain');
      if (!text) return;
      const normalized = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').replace(/\n$/, '');
      const lines = normalized.split('\n');
      if (lines.length < 2 || !lines.every(line => line.includes('\t'))) return;
      event.preventDefault();
      const cells = lines.map(line => line.split('\t'));
      const header = cells[0];
      const rows = cells.slice(1);
      const markdown = await this.serializeTable(Array.from({length: header.length}, () => 'left'), header, rows);
      if (markdown) this.insertMarkdownBlock(markdown);
    },
    async uploadFile(file) {
      const form = new FormData();
      form.append('image', file);
      const res = await fetch(this.prefix + '/api/articles/' + this.slug + '/images', {method: 'POST', body: form});
      const data = await res.json();
      if (!data.ok) {
        this.showModal('圖片上傳失敗', data.error);
        return;
      }
      this.insertText(data.markdown);
    },
    async publish() {
      if (!(await this.saveNow())) return;
      this.showModal('準備上稿', '執行中');
      const res = await fetch(this.prefix + '/api/articles/' + this.slug + '/publish', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({draft_url: this.draftUrl})
      });
      const data = await res.json();
      if (!data.ok) {
        this.showModal('準備上稿失敗', data.error);
        return;
      }
      this.showModal('準備上稿完成', data.log.join('\n') + '\n\n' + data.published_md);
    },
    async checkOfficial() {
      if (!(await this.saveNow())) return;
      this.showModal('官方比對', '執行中');
      const res = await fetch(this.prefix + '/api/articles/' + this.slug + '/check', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({draft_url: this.draftUrl})
      });
      const data = await res.json();
      if (!data.ok) {
        this.showModal('官方比對失敗', data.error);
        return;
      }
      this.showModal('官方比對', data.identical ? '一致\n' + data.diff : data.diff);
    },
    showModal(title, text) {
      this.modalTitle = title;
      this.modalText = text || '';
      this.modalOpen = true;
    }
  };
}
