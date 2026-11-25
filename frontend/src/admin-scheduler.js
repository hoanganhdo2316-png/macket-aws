export async function renderScheduler(container, api) {
  container.innerHTML =
    '<div class="panel">Đang đọc AWS EventBridge Scheduler...</div>';

  async function load() {
    try {
      const data = await api('/scheduler');
      draw(data);
    } catch (error) {
      container.innerHTML = '';
      const panel = document.createElement('div');
      panel.className = 'panel';
      panel.textContent = 'Không thể đọc Scheduler: ' + error.message;
      container.append(panel);
    }
  }

  function draw(data) {
    container.innerHTML = `
      <div class="groups-toolbar">
        <div>
          <h2>EventBridge Scheduler</h2>
          <p>Quản lý lịch kích hoạt Lambda Collector.</p>
        </div>
        <button id="refresh-scheduler" class="secondary-btn">
          Làm mới
        </button>
      </div>

      <div class="stat-grid">
        <article class="stat-card">
          <span>Trạng thái AWS</span>
          <strong id="aws-state"></strong>
          <small>Trạng thái thực tế trên EventBridge</small>
        </article>

        <article class="stat-card">
          <span>Chu kỳ crawl</span>
          <strong id="schedule-interval"></strong>
          <small>Phút / lượt</small>
        </article>

        <article class="stat-card">
          <span>Đồng bộ RDS / AWS</span>
          <strong id="sync-state"></strong>
          <small>Trạng thái đối chiếu cấu hình</small>
        </article>
      </div>

      <form id="scheduler-form" class="group-editor scheduler-editor">
        <h3>Cấu hình lịch chạy</h3>

        <label>
          Chu kỳ chạy (phút)
          <input
            type="number"
            name="interval_minutes"
            min="1"
            max="1440"
            step="1"
            required
          >
        </label>

        <div class="scheduler-info">
          <span>AWS Schedule Expression</span>
          <code id="aws-expression"></code>
        </div>

        <div class="scheduler-info">
          <span>Múi giờ</span>
          <strong id="schedule-timezone"></strong>
        </div>

        <div class="scheduler-lock">
          <strong>Chạy tự động: đang khóa</strong>
          <p>
            Chưa cho phép bật Scheduler trong giai đoạn phát triển.
            Bạn vẫn có thể điều chỉnh chu kỳ chạy.
          </p>
        </div>

        <div class="group-actions">
          <button type="submit" class="primary-btn">
            Lưu chu kỳ
          </button>
          <button type="button" id="reset-scheduler">
            Hủy thay đổi
          </button>
        </div>

        <p id="scheduler-message" role="status"></p>
      </form>
    `;

    const form = container.querySelector('#scheduler-form');
    const message = container.querySelector('#scheduler-message');

    function updateDisplay(value) {
      container.querySelector('#aws-state').textContent =
        value.aws_state;

      container.querySelector('#schedule-interval').textContent =
        String(value.interval_minutes) + ' phút';

      container.querySelector('#sync-state').textContent =
        value.aws_sync_status === 'synced'
          ? 'Synced'
          : 'Mismatch';

      container.querySelector('#aws-expression').textContent =
        value.aws_expression;

      container.querySelector('#schedule-timezone').textContent =
        value.timezone;

      form.elements.interval_minutes.value =
        value.interval_minutes;

      const mismatch = value.aws_sync_status !== 'synced';

      container.querySelector('#sync-state').style.color =
        mismatch ? '#bf4646' : '#21805a';

      form.querySelector('[type="submit"]').disabled =
        mismatch || value.aws_state !== 'DISABLED';

      if (mismatch) {
        message.textContent =
          'AWS và RDS chưa đồng bộ. Không nên chỉnh lịch trước khi kiểm tra.';
        message.style.color = '#bf4646';
      }
    }

    updateDisplay(data);

    container.querySelector('#refresh-scheduler').onclick =
      () => load();

    container.querySelector('#reset-scheduler').onclick =
      () => load();

    form.onsubmit = async event => {
      event.preventDefault();

      const minutes = Number(
        form.elements.interval_minutes.value
      );

      if (!Number.isInteger(minutes) ||
          minutes < 1 || minutes > 1440) {
        message.textContent =
          'Chu kỳ phải là số nguyên từ 1 đến 1440 phút.';
        return;
      }

      const button = form.querySelector('[type="submit"]');
      button.disabled = true;
      message.textContent = 'Đang đồng bộ AWS và RDS...';
      message.style.color = '#777';

      try {
        const updated = await api('/scheduler', {
          method: 'PATCH',
          body: JSON.stringify({
            interval_minutes: minutes
          })
        });

        updateDisplay(updated);
        message.textContent =
          'Đã cập nhật chu kỳ trên AWS và RDS.';
        message.style.color = '#21805a';
      } catch (error) {
        message.textContent = 'Lỗi: ' + error.message;
        message.style.color = '#bf4646';
      } finally {
        if (
          container.querySelector('#sync-state')?.textContent
            === 'Synced'
        ) {
          button.disabled = false;
        }
      }
    };
  }

  await load();
}
