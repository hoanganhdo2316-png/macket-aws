export async function renderPrompts(container, api) {
  container.innerHTML = '<div class="panel">Đang tải AI System Prompt...</div>';

  const root = document.createElement('div');
  root.className = 'ai-prompts-page';

  root.innerHTML = `
    <div class="groups-toolbar">
      <div>
        <h2>AI System Prompt</h2>
        <p>Quản lý hướng dẫn phân loại bài đăng của Macket AI.</p>
      </div>
    </div>

    <div class="panel">
      <h3>Phiên bản đang hoạt động</h3>
      <p id="prompt-active-status">Đang tải...</p>
    </div>

    <div class="panel">
      <h3>Prompt Editor</h3>
      <p>Tạo phiên bản mới. Phiên bản hiện tại không bị ghi đè.</p>

      <form id="prompt-form">
        <label for="prompt-description">Mô tả phiên bản</label>
        <input
          id="prompt-description"
          type="text"
          placeholder="Ví dụ: Cải thiện phân loại cửa hàng"
          maxlength="255"
        >

        <label for="prompt-content">System Prompt</label>
        <textarea
          id="prompt-content"
          rows="18"
          required
          spellcheck="false"
          placeholder="Nhập System Prompt..."
          style="width:100%;box-sizing:border-box;margin-top:8px;font-family:monospace;line-height:1.6;resize:vertical;"
        ></textarea>

        <div style="margin-top:16px">
          <button class="primary-btn" type="submit" id="prompt-save">
            Lưu phiên bản mới
          </button>
        </div>
      </form>
      <p id="prompt-message" role="status"></p>
    </div>

    <div class="panel">
      <h3>Version History</h3>
      <p>Chọn một phiên bản để xem nội dung hoặc kích hoạt lại.</p>
      <div id="prompt-history">Đang tải...</div>
    </div>
  `;

  container.replaceChildren(root);

  const $ = selector => root.querySelector(selector);
  const message = $('#prompt-message');

  function notify(text, error = false) {
    message.textContent = text;
    message.style.color = error ? '#dc2626' : '#15803d';
  }

  async function load() {
    try {
      const [versions, active] = await Promise.all([
        api('/ai-prompts'),
        api('/ai-prompts/active')
      ]);

      $('#prompt-active-status').textContent = active
        ? `Version ${active.version} — ${active.description || 'Không có mô tả'}`
        : 'Chưa có phiên bản nào được kích hoạt.';

      const history = $('#prompt-history');
      history.replaceChildren();

      if (!versions.length) {
        history.textContent = 'Chưa có phiên bản nào.';
        return;
      }

      for (const version of versions) {
        const item = document.createElement('div');
        item.style.cssText =
          'padding:14px 0;border-bottom:1px solid #ddd;';

        const heading = document.createElement('div');
        heading.style.cssText =
          'display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:center;';

        const info = document.createElement('div');

        const title = document.createElement('strong');
        title.textContent = `Version ${version.version}`;
        info.append(title);

        if (version.is_active) {
          const status = document.createElement('span');
          status.textContent = ' — ACTIVE';
          status.style.color = '#15803d';
          info.append(status);
        }

        const description = document.createElement('p');
        description.textContent = version.description || 'Không có mô tả';
        info.append(description);

        const actions = document.createElement('div');
        actions.style.cssText = 'display:flex;gap:8px;flex-wrap:wrap;';

        const viewButton = document.createElement('button');
        viewButton.type = 'button';
        viewButton.textContent = 'Xem / Chỉnh sửa thành bản mới';

        viewButton.onclick = async () => {
          try {
            const detail = await api(`/ai-prompts/${version.id}`);
            $('#prompt-content').value = detail.system_prompt;
            $('#prompt-description').value =
              `Dựa trên version ${detail.version}`;
            notify(`Đã tải version ${detail.version} vào Editor. Chưa lưu thay đổi.`);
            $('#prompt-content').scrollIntoView({ behavior: 'smooth' });
          } catch (error) {
            notify(error.message, true);
          }
        };

        actions.append(viewButton);

        if (!version.is_active) {
          const activateButton = document.createElement('button');
          activateButton.type = 'button';
          activateButton.textContent = 'Kích hoạt';

          activateButton.onclick = async () => {
            if (!confirm(`Kích hoạt System Prompt version ${version.version}?`)) {
              return;
            }

            activateButton.disabled = true;
            try {
              await api(`/ai-prompts/${version.id}/activate`, {
                method: 'POST'
              });
              await load();
              notify(`Đã kích hoạt version ${version.version}.`);
            } catch (error) {
              notify(error.message, true);
              activateButton.disabled = false;
            }
          };

          actions.append(activateButton);
        }

        heading.append(info, actions);
        item.append(heading);
        history.append(item);
      }
    } catch (error) {
      $('#prompt-history').textContent = 'Không tải được lịch sử phiên bản.';
      notify(error.message, true);
    }
  }

  $('#prompt-form').onsubmit = async event => {
    event.preventDefault();

    const system_prompt = $('#prompt-content').value.trim();
    const description = $('#prompt-description').value.trim();

    if (!system_prompt) {
      notify('System Prompt không được để trống.', true);
      return;
    }

    const saveButton = $('#prompt-save');
    saveButton.disabled = true;

    try {
      const created = await api('/ai-prompts', {
        method: 'POST',
        body: JSON.stringify({
          system_prompt,
          description: description || null
        })
      });

      await load();
      notify(
        `Đã lưu version ${created.version}. ` +
        'Phiên bản mới chưa được kích hoạt.'
      );
    } catch (error) {
      notify(error.message, true);
    } finally {
      saveButton.disabled = false;
    }
  };

  await load();
}
