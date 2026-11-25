export async function renderCrawler(container, api) {
  container.innerHTML = '<div class="panel">Đang tải cấu hình crawler...</div>';

  try {
    const settings = await api('/crawler-settings');

    container.innerHTML = `
      <div class="groups-toolbar">
        <div>
          <h2>Crawler Settings</h2>
          <p>Điều chỉnh cấu hình thu thập dữ liệu từ Facebook.</p>
        </div>
      </div>

      <form id="crawler-form" class="group-editor">
        <label>
          Số bài tối đa mỗi nhóm
          <input type="number" name="max_posts_per_group"
            min="1" max="100" required>
        </label>

        <label class="group-checkbox">
          <input type="checkbox" name="only_new_posts">
          Chỉ thu thập bài đăng mới
        </label>

        <label>
          Giới hạn chi phí mỗi lượt crawl (USD)
          <input type="number" name="max_total_charge_usd"
            min="0.01" max="10" step="0.01" required>
        </label>

        <p class="group-note">
          Cấu hình được lưu vào RDS. Lambda sẽ đọc cấu hình
          mới nhất khi bắt đầu lượt crawl tiếp theo.
        </p>

        <div class="group-actions">
          <button class="primary-btn" type="submit">
            Lưu cấu hình
          </button>
          <button type="button" id="reload-crawler">
            Khôi phục giá trị đã lưu
          </button>
        </div>

        <p id="crawler-message" role="status"></p>
      </form>

      <div class="panel">
        <h2>Trạng thái hệ thống</h2>
        <p>
          EventBridge Scheduler đang được quản lý riêng.
          Thay đổi Crawler Settings không tự động kích hoạt lịch crawl.
        </p>
      </div>
    `;

    const form = container.querySelector('#crawler-form');
    const message = container.querySelector('#crawler-message');

    function populate(data) {
      form.elements.max_posts_per_group.value =
        data.max_posts_per_group;
      form.elements.only_new_posts.checked =
        data.only_new_posts;
      form.elements.max_total_charge_usd.value =
        data.max_total_charge_usd;
    }

    populate(settings);

    container.querySelector('#reload-crawler').onclick = async () => {
      try {
        populate(await api('/crawler-settings'));
        message.textContent = 'Đã tải lại cấu hình.';
      } catch (error) {
        message.textContent = 'Lỗi: ' + error.message;
      }
    };

    form.onsubmit = async event => {
      event.preventDefault();

      const data = {
        max_posts_per_group:
          Number(form.elements.max_posts_per_group.value),
        only_new_posts:
          form.elements.only_new_posts.checked,
        max_total_charge_usd:
          Number(form.elements.max_total_charge_usd.value)
      };

      const button = form.querySelector('[type="submit"]');
      button.disabled = true;
      message.textContent = 'Đang lưu...';

      try {
        const updated = await api('/crawler-settings', {
          method: 'PATCH',
          body: JSON.stringify(data)
        });

        populate(updated);
        message.textContent = '✓ Đã lưu cấu hình vào RDS.';
        message.style.color = '#21805a';
      } catch (error) {
        message.textContent = 'Lỗi: ' + error.message;
        message.style.color = '#bf4646';
      } finally {
        button.disabled = false;
      }
    };
  } catch (error) {
    container.textContent =
      'Không thể tải Crawler Settings: ' + error.message;
  }
}
