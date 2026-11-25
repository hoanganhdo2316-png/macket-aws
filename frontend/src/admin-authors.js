const esc = value => String(value ?? '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#39;');

const labels = {
  seller: 'Cửa hàng / người bán chuyên',
  individual: 'Người bán cá nhân',
  unknown: 'Chưa xác định'
};

export async function renderAuthors(container, api) {
  let authors = [];
  container.innerHTML = '<div class="panel">Đang tải tác giả...</div>';

  async function load() {
    try {
      const result = await api('/authors');
      authors = result.authors;
      draw();
    } catch (error) {
      container.innerHTML = '';
      const panel = document.createElement('div');
      panel.className = 'panel';
      panel.textContent = 'Lỗi tải Author Skip List: ' + error.message;
      container.append(panel);
    }
  }

  function draw() {
    container.innerHTML = `
      <div class="groups-toolbar">
        <div>
          <h2>Author Skip List</h2>
          <p>Quản lý các tài khoản Facebook được nhận diện và bỏ qua khi crawl.</p>
        </div>
        <button id="add-author" class="primary-btn">+ Thêm tác giả</button>
      </div>

      <div class="groups-summary">
        <span>Tổng: <strong>${authors.length}</strong></span>
        <span>Đang bỏ qua:
          <strong>${authors.filter(a => a.skip_enabled).length}</strong>
        </span>
        <span>Seller:
          <strong>${authors.filter(a => a.classification === 'seller').length}</strong>
        </span>
      </div>

      <div id="author-form-area"></div>

      <div class="groups-table-wrap">
        <table class="groups-table">
          <thead>
            <tr>
              <th>Tác giả</th>
              <th>Phân loại</th>
              <th>Skip</th>
              <th>Thao tác</th>
            </tr>
          </thead>
          <tbody>
            ${authors.map(a => `
              <tr>
                <td>
                  <strong>${esc(a.display_name || 'Chưa có tên')}</strong>
                  <div class="author-detail">ID: ${esc(a.facebook_author_id || '—')}</div>
                  ${a.profile_url
                    ? `<a href="${esc(a.profile_url)}" target="_blank"
                         rel="noopener noreferrer">Facebook Profile</a>`
                    : ''}
                  ${a.reason
                    ? `<div class="author-detail">${esc(a.reason)}</div>`
                    : ''}
                </td>
                <td>${esc(labels[a.classification] || a.classification)}</td>
                <td>
                  <label class="group-switch">
                    <input type="checkbox" data-skip="${a.id}"
                      ${a.skip_enabled ? 'checked' : ''}
                      ${a.classification !== 'seller' ? 'disabled' : ''}>
                    <span>${a.skip_enabled ? 'Đang skip' : 'Không skip'}</span>
                  </label>
                </td>
                <td>
                  <div class="group-actions">
                    <button data-edit-author="${a.id}">Sửa</button>
                    <button data-delete-author="${a.id}" class="danger-btn">Xóa</button>
                  </div>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;

    container.querySelector('#add-author').onclick = () => showForm();

    container.querySelectorAll('[data-edit-author]').forEach(button => {
      button.onclick = () => showForm(
        authors.find(a => a.id === Number(button.dataset.editAuthor))
      );
    });

    container.querySelectorAll('[data-skip]').forEach(input => {
      input.onchange = async () => {
        const a = authors.find(
          x => x.id === Number(input.dataset.skip)
        );
        if (!a || a.classification !== 'seller') return;

        const enabled = input.checked;
        input.disabled = true;

        try {
          await api(`/authors/${a.id}`, {
            method: 'PATCH',
            body: JSON.stringify({ skip_enabled: enabled })
          });
          await load();
        } catch (error) {
          input.checked = !enabled;
          input.disabled = false;
          alert('Lỗi cập nhật: ' + error.message);
        }
      };
    });

    container.querySelectorAll('[data-delete-author]').forEach(button => {
      button.onclick = async () => {
        const a = authors.find(
          x => x.id === Number(button.dataset.deleteAuthor)
        );
        if (!a) return;
        if (!confirm(`Xóa tác giả "${a.display_name || a.facebook_author_id}"?`)) {
          return;
        }

        try {
          await api(`/authors/${a.id}`, { method: 'DELETE' });
          await load();
        } catch (error) {
          alert('Lỗi xóa tác giả: ' + error.message);
        }
      };
    });
  }

  function showForm(author = null) {
    const area = container.querySelector('#author-form-area');

    area.innerHTML = `
      <form id="author-editor" class="group-editor">
        <h3>${author ? 'Chỉnh sửa tác giả' : 'Thêm tác giả'}</h3>

        <label>
          Facebook Author ID
          <input name="facebook_author_id" maxlength="255"
            value="${esc(author?.facebook_author_id || '')}"
            placeholder="Ví dụ: 61574048068922">
        </label>

        <label>
          Facebook Profile URL
          <input name="profile_url" type="url"
            value="${esc(author?.profile_url || '')}"
            placeholder="https://www.facebook.com/...">
        </label>

        <label>
          Tên hiển thị
          <input name="display_name" maxlength="255"
            value="${esc(author?.display_name || '')}"
            placeholder="Tên người bán">
        </label>

        <label>
          Phân loại
          <select name="classification">
            ${Object.entries(labels).map(([value, label]) => `
              <option value="${value}"
                ${author?.classification === value ? 'selected' : ''}>
                ${label}
              </option>
            `).join('')}
          </select>
        </label>

        <label class="group-checkbox">
          <input name="skip_enabled" type="checkbox"
            ${author?.skip_enabled ? 'checked' : ''}>
          Bỏ qua khi crawl
        </label>

        <p class="group-note">
          Chỉ bật Skip đối với tài khoản được phân loại Seller.
          Cần có Author ID hoặc Profile URL.
        </p>

        <label>
          Ghi chú
          <textarea name="reason" rows="3"
            placeholder="Lý do nhận diện hoặc bỏ qua">${esc(author?.reason || '')}</textarea>
        </label>

        <div class="group-actions">
          <button class="primary-btn" type="submit">Lưu</button>
          <button type="button" id="cancel-author">Hủy</button>
        </div>
        <p id="author-form-error" class="error" role="alert"></p>
      </form>
    `;

    const form = area.querySelector('#author-editor');
    const classification = form.elements.classification;
    const skip = form.elements.skip_enabled;

    function syncSkip() {
      if (classification.value !== 'seller') {
        skip.checked = false;
        skip.disabled = true;
      } else {
        skip.disabled = false;
      }
    }

    classification.onchange = syncSkip;
    syncSkip();

    area.querySelector('#cancel-author').onclick = () => {
      area.innerHTML = '';
    };

    form.onsubmit = async event => {
      event.preventDefault();

      const id = form.elements.facebook_author_id.value.trim();
      const url = form.elements.profile_url.value.trim();
      const error = form.querySelector('#author-form-error');

      if (!id && !url) {
        error.textContent = 'Cần nhập Author ID hoặc Profile URL.';
        return;
      }

      const data = {
        facebook_author_id: id || null,
        profile_url: url || null,
        display_name: form.elements.display_name.value.trim() || null,
        classification: classification.value,
        skip_enabled: classification.value === 'seller' && skip.checked,
        reason: form.elements.reason.value.trim() || null
      };

      const save = form.querySelector('[type="submit"]');
      save.disabled = true;

      try {
        await api(author ? `/authors/${author.id}` : '/authors', {
          method: author ? 'PATCH' : 'POST',
          body: JSON.stringify(data)
        });
        await load();
      } catch (err) {
        error.textContent = err.message;
        save.disabled = false;
      }
    };

    area.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  await load();
}
