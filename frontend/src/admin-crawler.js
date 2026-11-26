const scanLabels = {
  IDLE: 'Chưa có lượt quét được ghi nhận.',
  QUEUED: 'Đã gửi yêu cầu, đang chờ Lambda.',
  STARTING: 'Collector đang chuẩn bị.',
  READY: 'Apify đang chờ tài nguyên.',
  RUNNING: 'Apify đang quét Facebook.',
  ABORTING: 'Apify đang dừng lượt quét.',
  'TIMING-OUT': 'Apify đang kết thúc lượt quá thời gian.',
  AWAITING_INGESTION: 'Apify đã quét xong, đang chờ nhập dữ liệu.',
  INGESTED: 'Đã nhập dữ liệu từ lượt quét.',
  FAILED: 'Lượt quét không thành công.',
  ABORTED: 'Lượt quét đã bị hủy.',
  'TIMED-OUT': 'Lượt quét đã quá thời gian.',
  EXPIRED: 'Yêu cầu hết hạn trước khi Collector nhận.',
  UNKNOWN: 'Chưa xác minh được lượt quét. Tạm khóa các lượt quét mới.',
  STATUS_UNAVAILABLE: 'Tạm thời không đọc được trạng thái Apify.'
};

function bindScan(panel, api) {
  const trigger = panel.querySelector('#trigger-facebook-scan');
  const status = panel.querySelector('#facebook-scan-status');
  const message = panel.querySelector('#facebook-scan-message');
  let timer;
  let request = 0;

  async function refresh() {
    if (!panel.isConnected) return;
    const current = ++request;
    let delay = 15000;

    try {
      const scan = await api('/api/scan/status');
      if (!panel.isConnected || current !== request) return;
      trigger.disabled = !scan.can_trigger;
      const label = scanLabels[scan.status] || 'Chưa đọc được trạng thái lượt quét.';
      const source = scan.source === 'scheduler' ? 'Lịch tự động' : 'Thủ công';
      const text = (scan.enabled ? '' : 'Quét thủ công chưa được bật. ')
        + label + (scan.source ? ` Yêu cầu: ${source}.` : '');
      if (status.textContent !== text) status.textContent = text;
      if (['QUEUED', 'STARTING', 'READY', 'RUNNING', 'AWAITING_INGESTION'].includes(scan.status)) {
        delay = 5000;
      }
    } catch {
      if (!panel.isConnected || current !== request) return;
      trigger.disabled = true;
      status.textContent = 'Không thể tải trạng thái quét. Đang thử lại.';
    }

    timer = setTimeout(refresh, delay);
  }

  trigger.onclick = async () => {
    clearTimeout(timer);
    request++;
    trigger.disabled = true;
    message.textContent = 'Đang gửi yêu cầu...';
    try {
      await api('/api/scan/trigger', { method: 'POST' });
      message.textContent = '';
    } catch (error) {
      message.textContent = error.message;
    }
    await refresh();
  };

  refresh();
}

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

      <section class="panel" id="facebook-scan">
        <h2>Quét Facebook</h2>
        <p id="facebook-scan-status" role="status">Đang đọc trạng thái quét...</p>
        <button class="primary-btn" type="button" id="trigger-facebook-scan" disabled>
          Quét ngay
        </button>
        <p id="facebook-scan-message" role="status"></p>
      </section>

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
    bindScan(container.querySelector('#facebook-scan'), api);

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
