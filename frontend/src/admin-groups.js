const esc = value => String(value ?? '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#39;');

export async function renderGroups(container, api) {
  container.innerHTML = '<div class="panel">Đang tải Facebook Groups...</div>';

  let groups = [];

  async function load() {
    try {
      const response = await api('/groups');
      groups = response.groups;
      draw();
    } catch (error) {
      container.innerHTML = '';
      const message = document.createElement('div');
      message.className = 'panel';
      message.textContent = 'Không thể tải Groups: ' + error.message;
      container.append(message);
    }
  }

  function draw() {
    container.innerHTML = `
      <div class="groups-toolbar">
        <div>
          <h2>Facebook Groups</h2>
          <p>Quản lý các nhóm mà Macket thu thập bài đăng.</p>
        </div>
        <button class="primary-btn" id="add-group">+ Thêm nhóm</button>
      </div>

      <div class="groups-summary">
        <span>Tổng nhóm: <strong>${groups.length}</strong></span>
        <span>Đang bật: <strong>${groups.filter(g => g.enabled).length}</strong></span>
      </div>

      <div id="group-form-area"></div>
      <div class="groups-table-wrap">
        <table class="groups-table">
          <thead>
            <tr>
              <th>Nhóm Facebook</th>
              <th>Trạng thái</th>
              <th>Giới hạn</th>
              <th>Thao tác</th>
            </tr>
          </thead>
          <tbody>
            ${groups.map(group => `
              <tr>
                <td>
                  <strong>${esc(group.name)}</strong>
                  <a href="${esc(group.url)}"
                     target="_blank" rel="noopener noreferrer">
                    ${esc(group.url)}
                  </a>
                </td>
                <td>
                  <label class="group-switch">
                    <input type="checkbox"
                      data-toggle="${group.id}"
                      ${group.enabled ? 'checked' : ''}>
                    <span>${group.enabled ? 'Đang bật' : 'Đã tắt'}</span>
                  </label>
                </td>
                <td>${group.max_posts ?? 'Mặc định'}</td>
                <td>
                  <div class="group-actions">
                    <button data-edit="${group.id}">Sửa</button>
                    <button data-delete="${group.id}"
                      class="danger-btn">Xóa</button>
                  </div>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>

      <p id="groups-message" class="groups-message" role="status"></p>
    `;

    document.querySelector('#add-group')?.addEventListener(
      'click', () => showForm()
    );

    container.querySelectorAll('[data-edit]').forEach(button => {
      button.onclick = () => {
        const group = groups.find(
          g => g.id === Number(button.dataset.edit)
        );
        showForm(group);
      };
    });

    container.querySelectorAll('[data-toggle]').forEach(input => {
      input.onchange = async () => {
        const enabled = input.checked;
        input.disabled = true;

        try {
          await api(`/groups/${input.dataset.toggle}`, {
            method: 'PATCH',
            body: JSON.stringify({ enabled })
          });
          await load();
        } catch (error) {
          input.checked = !enabled;
          input.disabled = false;
          alert('Không thể cập nhật: ' + error.message);
        }
      };
    });

    container.querySelectorAll('[data-delete]').forEach(button => {
      button.onclick = async () => {
        const group = groups.find(
          g => g.id === Number(button.dataset.delete)
        );

        if (!group) return;

        if (!confirm(
          `Xóa nhóm "${group.name}"?\n\n` +
          'Nhóm có bài đăng trong RDS có thể không xóa được. ' +
          'Bạn có thể tắt crawl nhóm thay thế.'
        )) return;

        try {
          await api(`/groups/${group.id}`, { method: 'DELETE' });
          await load();
        } catch (error) {
          alert(
            'Không thể xóa nhóm: ' + error.message +
            '\nNếu nhóm đã có bài đăng, hãy tắt nhóm thay vì xóa.'
          );
        }
      };
    });
  }

  function showForm(group = null) {
    const area = container.querySelector('#group-form-area');
    if (!area) return;

    area.innerHTML = `
      <form id="group-editor" class="group-editor">
        <h3>${group ? 'Chỉnh sửa nhóm' : 'Thêm Facebook Group'}</h3>
        <label>
          Tên nhóm
          <input name="name" required maxlength="255"
            value="${esc(group?.name ?? '')}">
        </label>
        <label>
          Facebook Group URL
          <input name="url" type="url" required
            placeholder="https://www.facebook.com/groups/..."
            value="${esc(group?.url ?? '')}">
        </label>
        <label class="group-checkbox">
          <input name="enabled" type="checkbox"
            ${group?.enabled !== false ? 'checked' : ''}>
          Cho phép crawl nhóm
        </label>
        <p class="group-note">
          Giới hạn số bài hiện sử dụng cấu hình chung của Crawler.
          Chưa hỗ trợ giới hạn riêng từng nhóm trong Lambda.
        </p>
        <div class="group-actions">
          <button type="submit" class="primary-btn">Lưu thay đổi</button>
          <button type="button" id="cancel-group">Hủy</button>
        </div>
        <p id="group-form-error" class="error" role="alert"></p>
      </form>
    `;

    area.querySelector('#cancel-group').onclick = () => {
      area.innerHTML = '';
    };

    area.querySelector('#group-editor').onsubmit = async event => {
      event.preventDefault();

      const form = event.currentTarget;
      const button = form.querySelector('[type="submit"]');
      const errorElement = form.querySelector('#group-form-error');

      const data = {
        name: form.elements.name.value.trim(),
        url: form.elements.url.value.trim(),
        enabled: form.elements.enabled.checked
      };

      button.disabled = true;

      try {
        await api(group ? `/groups/${group.id}` : '/groups', {
          method: group ? 'PATCH' : 'POST',
          body: JSON.stringify(data)
        });
        await load();
      } catch (error) {
        errorElement.textContent = error.message;
        button.disabled = false;
      }
    };

    area.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  await load();
}
