export async function renderClassificationLogs(container, api) {
  container.innerHTML = `
    <div class="groups-toolbar">
      <div>
        <h2>AI Classification Logs</h2>
        <p>Lịch sử phân loại bài đăng Facebook bằng AI.</p>
      </div>
    </div>


    <div id="classification-stats"
         class="credentials-grid"
         style="margin-bottom:20px">
      <div class="panel">Đang tải thống kê AI...</div>
    </div>
    <div class="panel">
      <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:end">
        <div>
          <label for="log-label">Seller Type</label>
          <select id="log-label">
            <option value="">Tất cả</option>
            <option value="seller">Seller</option>
            <option value="individual">Individual</option>
            <option value="unknown">Unknown</option>
          </select>
        </div>
        <div>
          <label for="log-post-id">Post ID</label>
          <input id="log-post-id" type="number" min="1"
                 placeholder="Tìm theo Post ID">
        </div>
        <button id="log-search" class="primary-btn">Tìm kiếm</button>
      </div>

      <p id="log-summary" role="status"></p>
      <div id="log-results"></div>

      <div style="display:flex;gap:12px;margin-top:16px">
        <button id="log-prev">Trang trước</button>
        <button id="log-next">Trang tiếp</button>
      </div>
    </div>

    <div class="panel" id="log-detail" hidden>
      <h3>Classification Detail</h3>
      <div id="log-detail-content"></div>
    </div>
  `;

  const $ = selector => container.querySelector(selector);
  let offset = 0;
  const limit = 20;
  let requestVersion = 0;


  async function loadStats() {
    const root = $('#classification-stats');

    try {
      const stats = await api('/classification-logs/stats');
      if (!container.isConnected) return;

      const cards = [
        ['Tổng lượt phân loại', stats.total_classifications],
        ['Bài đăng duy nhất', stats.unique_posts],
        ['Tổng tokens', stats.total_tokens],
        ['Chi phí ước tính',
          '$' + Number(stats.estimated_cost_usd).toFixed(8)]
      ];

      root.replaceChildren();

      for (const [label, value] of cards) {
        const card = document.createElement('div');
        card.className = 'panel';

        const heading = document.createElement('p');
        heading.textContent = label;

        const number = document.createElement('h2');
        number.textContent =
          typeof value === 'number'
            ? value.toLocaleString('vi-VN')
            : value;

        card.append(heading, number);
        root.append(card);
      }

      if (stats.unpriced_classifications > 0) {
        const warning = document.createElement('p');
        warning.textContent =
          stats.unpriced_classifications +
          ' lượt chưa có dữ liệu chi phí. Tổng tiền chưa đầy đủ.';
        warning.style.cssText =
          'grid-column:1/-1;font-size:13px;opacity:.75';
        root.append(warning);
      }

    } catch (error) {
      if (container.isConnected) {
        root.textContent = 'Không tải được thống kê: ' + error.message;
      }
    }
  }

  async function load() {
    const version = ++requestVersion;
    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset)
    });

    const label = $('#log-label').value;
    const postId = $('#log-post-id').value.trim();

    if (label) params.set('seller_type', label);
    if (postId) params.set('post_id', postId);

    $('#log-summary').textContent = 'Đang tải...';

    try {
      const data = await api(`/classification-logs?${params}`);

      if (version !== requestVersion || !container.isConnected) return;

      $('#log-summary').textContent =
        `${data.total} kết quả • Trang ${Math.floor(offset / limit) + 1}`;

      const results = $('#log-results');
      results.replaceChildren();

      for (const item of data.items) {
        const row = document.createElement('div');
        row.style.cssText =
          'padding:14px 0;border-bottom:1px solid #ddd;';

        const heading = document.createElement('div');
        heading.style.cssText =
          'display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;';

        const info = document.createElement('div');

        const title = document.createElement('strong');
        title.textContent =
          `Post #${item.post_id} — ${item.author_name || 'Unknown Author'}`;

        const metadata = document.createElement('p');
        metadata.textContent =
          `${item.seller_type.toUpperCase()} • ` +
          `Confidence: ${item.confidence == null ? 'N/A' : (item.confidence * 100).toFixed(0) + '%'} • ` +
          `Prompt v${item.prompt_version} • ${item.model}` +
          ` • Tokens: ${item.total_tokens ?? 'N/A'}` +
          ` • Time: ${item.processing_ms == null ? 'N/A' : (item.processing_ms / 1000).toFixed(2) + 's'}`;

        const preview = document.createElement('p');
        preview.textContent = item.content_preview || '';

        const view = document.createElement('button');
        view.type = 'button';
        view.textContent = 'Xem chi tiết';

        view.onclick = async () => {
          try {
            const detail = await api(`/classification-logs/${item.id}`);
            if (!container.isConnected) return;

            const panel = $('#log-detail');
            const content = $('#log-detail-content');
            content.replaceChildren();

            const summary = document.createElement('p');
            summary.textContent =
              `Post #${detail.post_id} | ${detail.seller_type} | ` +
              `Prompt v${detail.prompt_version}`;

            const reason = document.createElement('p');
            reason.textContent = `Reason: ${detail.reason || 'N/A'}`;

            const original = document.createElement('pre');
            original.style.cssText =
              'white-space:pre-wrap;overflow-wrap:anywhere;';
            original.textContent = detail.post_content || '';

            const json = document.createElement('pre');
            json.style.cssText =
              'white-space:pre-wrap;overflow-wrap:anywhere;';
            json.textContent = JSON.stringify(detail.raw_result, null, 2);

            const metrics = document.createElement('p');
            metrics.textContent =
              `Input: ${detail.input_tokens ?? 'N/A'} tokens | ` +
              `Output: ${detail.output_tokens ?? 'N/A'} tokens | ` +
              `Total: ${detail.total_tokens ?? 'N/A'} tokens | ` +
              `Processing: ${detail.processing_ms ?? 'N/A'} ms | ` +
              `Estimated Cost: ${
                detail.estimated_cost_usd == null
                  ? 'N/A'
                  : '$' + detail.estimated_cost_usd
              }`;

            content.append(summary, reason, metrics);

            if (detail.post_url?.startsWith('https://')) {
              const link = document.createElement('a');
              link.href = detail.post_url;
              link.target = '_blank';
              link.rel = 'noopener noreferrer';
              link.textContent = 'Xem bài Facebook';
              content.append(link);
            }

            const originalTitle = document.createElement('h4');
            originalTitle.textContent = 'Nội dung bài đăng';

            const jsonTitle = document.createElement('h4');
            jsonTitle.textContent = 'AI Result JSON';

            content.append(originalTitle, original, jsonTitle, json);

            panel.hidden = false;
            panel.scrollIntoView({ behavior: 'smooth' });
          } catch (error) {
            $('#log-summary').textContent = error.message;
          }
        };

        info.append(title, metadata, preview);
        heading.append(info, view);
        row.append(heading);
        results.append(row);
      }

      if (!data.items.length) {
        results.textContent = 'Không tìm thấy kết quả.';
      }

      $('#log-prev').disabled = offset === 0;
      $('#log-next').disabled = offset + limit >= data.total;

    } catch (error) {
      if (version === requestVersion && container.isConnected) {
        $('#log-summary').textContent = `Lỗi: ${error.message}`;
      }
    }
  }

  $('#log-search').onclick = () => {
    offset = 0;
    $('#log-detail').hidden = true;
    load();
  };

  $('#log-prev').onclick = () => {
    offset = Math.max(0, offset - limit);
    load();
  };

  $('#log-next').onclick = () => {
    offset += limit;
    load();
  };

  await Promise.all([loadStats(), load()]);
}
