const services = [
  {
    id: 'openai',
    name: 'OpenAI',
    description: 'API Key dành cho AI Classification.'
  },
  {
    id: 'apify',
    name: 'Apify',
    description: 'API Token dành cho Facebook Collector.'
  }
];

export async function renderCredentials(container, api) {
  container.innerHTML =
    '<div class="panel">Đang tải trạng thái API Credentials...</div>';

  try {
    const result = await api('/credentials');
    const existing = new Map(
      result.credentials.map(item => [item.service, item])
    );

    container.innerHTML = `
      <div class="groups-toolbar">
        <div>
          <h2>API Credentials</h2>
          <p>Quản lý khóa API được mã hóa và lưu trên PostgreSQL.</p>
        </div>
      </div>

      <div class="credentials-grid">
        ${services.map(service => `
          <form class="credential-card" data-service="${service.id}">
            <div class="credential-heading">
              <h3>${service.name}</h3>
              <span class="credential-status"></span>
            </div>

            <p>${service.description}</p>

            <label for="credential-${service.id}">
              ${service.name} API Token
            </label>

            <div class="credential-input-row">
              <input
                id="credential-${service.id}"
                name="token"
                type="password"
                placeholder="Nhập API Key / Token mới"
                autocomplete="off"
                spellcheck="false"
                required
              >
              <button type="button" class="credential-visibility">
                Hiện
              </button>
            </div>

            <div class="credential-footer">
              <small class="credential-updated"></small>
              <button type="submit" class="primary-btn">
                Lưu khóa
              </button>
            </div>

            <p class="credential-message" role="status"></p>
          </form>
        `).join('')}
      </div>

      <div class="panel">
        <h2>Lưu ý bảo mật</h2>
        <p>
          API Key được gửi qua HTTPS, mã hóa tại FastAPI và lưu
          vào RDS. Hệ thống không hiển thị lại khóa đã lưu.
          Khi cập nhật, hãy nhập toàn bộ khóa mới.
        </p>
        <p>
          Apify Token trong RDS chưa được đồng bộ với Lambda.
          OpenAI Key sẽ được sử dụng khi hoàn thiện AI Classification.
        </p>
      </div>
    `;

    function updateStatus(form, data) {
      const status = form.querySelector('.credential-status');
      const updated = form.querySelector('.credential-updated');

      status.textContent = data?.configured
        ? 'Đã cấu hình'
        : 'Chưa cấu hình';

      status.classList.toggle(
        'configured',
        Boolean(data?.configured)
      );

      updated.textContent = data?.updated_at
        ? 'Cập nhật: ' + new Date(data.updated_at).toLocaleString('vi-VN')
        : 'Chưa lưu khóa';
    }

    for (const service of services) {
      const form = container.querySelector(
        `[data-service="${service.id}"]`
      );

      const input = form.elements.token;
      const message = form.querySelector('.credential-message');
      const saveButton = form.querySelector('[type="submit"]');
      const visibility = form.querySelector('.credential-visibility');

      updateStatus(form, existing.get(service.id));

      visibility.onclick = () => {
        const visible = input.type === 'password';
        input.type = visible ? 'text' : 'password';
        visibility.textContent = visible ? 'Ẩn' : 'Hiện';
      };

      form.onsubmit = async event => {
        event.preventDefault();

        const token = input.value.trim();
        if (!token) return;

        saveButton.disabled = true;
        message.textContent = 'Đang lưu khóa...';
        message.className = 'credential-message';

        try {
          const updated = await api(
            `/credentials/${service.id}`,
            {
              method: 'PUT',
              body: JSON.stringify({ token })
            }
          );

          updateStatus(form, updated);

          input.value = '';
          input.type = 'password';
          visibility.textContent = 'Hiện';

          message.textContent = 'Đã lưu khóa mã hóa thành công.';
          message.classList.add('success');
        } catch (error) {
          message.textContent = 'Không thể lưu: ' + error.message;
          message.classList.add('failed');
        } finally {
          saveButton.disabled = false;
        }
      };
    }
  } catch (error) {
    container.textContent =
      'Không thể tải API Credentials: ' + error.message;
  }
}
