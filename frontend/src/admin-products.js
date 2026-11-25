const esc = value => String(value ?? '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#39;');

const safeUrl = value => {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' ? url.href : '';
  } catch {
    return '';
  }
};

const money = value => {
  const n = Number(value);
  return Number.isFinite(n) && n > 0
    ? new Intl.NumberFormat('vi-VN').format(n) + 'đ'
    : 'Liên hệ';
};

export async function renderProducts(container, api) {
  let status = 'visible';
  let page = 1;
  const limit = 20;
  let busy = false;

  container.innerHTML = '<div class="panel">Đang tải sản phẩm...</div>';

  async function load() {
    try {
      const data = await api(
        `/products?status=${status}&page=${page}&limit=${limit}`
      );
      draw(data);
    } catch (error) {
      container.innerHTML = `
        <div class="panel">
          <h2>Không tải được sản phẩm</h2>
          <p>${esc(error.message)}</p>
        </div>`;
    }
  }

  function draw(data) {
    container.innerHTML = `
      <div class="panel">
        <div class="groups-toolbar">
          <div>
            <h2>Quản lý sản phẩm</h2>
            <p>Kiểm duyệt các bài đăng đang xuất hiện trên Client Macket.</p>
          </div>
          <select id="product-status" class="product-status-select">
            <option value="visible" ${status === 'visible' ? 'selected' : ''}>
              Đang hiển thị
            </option>
            <option value="hidden" ${status === 'hidden' ? 'selected' : ''}>
              Đã ẩn
            </option>
            <option value="all" ${status === 'all' ? 'selected' : ''}>
              Tất cả
            </option>
          </select>
        </div>

        <p class="product-count">
          Tổng: <strong>${data.total}</strong> bài đăng
        </p>

        <div class="admin-product-list">
          ${data.items.length
            ? data.items.map(item => {
                const p = item.products?.[0] || {};
                const title = [p.brand, p.model].filter(Boolean).join(' ')
                  || 'Thiết bị điện tử';
                const image = safeUrl(item.thumbnail_url);
                const facebook = safeUrl(item.facebook_url);

                return `
                  <article class="admin-product-card">
                    <div class="admin-product-photo">
                      ${image
                        ? `<img src="${esc(image)}" alt="${esc(title)}"
                            loading="lazy" referrerpolicy="no-referrer">`
                        : '<span>Chưa có ảnh</span>'}
                    </div>

                    <div class="admin-product-info">
                      <div class="admin-product-heading">
                        <strong>${esc(title)}</strong>
                        <span class="product-state ${item.is_hidden ? 'is-hidden' : ''}">
                          ${item.is_hidden ? 'Đã ẩn' : 'Đang hiển thị'}
                        </span>
                      </div>

                      <div class="admin-product-price">
                        ${money(p.price_vnd)}
                      </div>

                      <div class="admin-product-meta">
                        #${item.id} · ${esc(item.author_name || 'Không rõ')}
                        · ${item.image_count} ảnh
                      </div>

                      ${item.is_hidden && item.moderation_reason
                        ? `<p class="product-reason">
                            Lý do ẩn: ${esc(item.moderation_reason)}
                          </p>`
                        : ''}

                      <div class="admin-product-actions">
                        ${facebook
                          ? `<a href="${esc(facebook)}" target="_blank"
                              rel="noopener noreferrer">
                              Xem Facebook
                            </a>`
                          : ''}

                        ${item.is_hidden
                          ? `<button type="button"
                              data-restore="${item.id}">
                              Khôi phục
                            </button>`
                          : `<button type="button" class="danger-btn"
                              data-hide="${item.id}">
                              Ẩn sản phẩm
                            </button>`}
                      </div>
                    </div>
                  </article>`;
              }).join('')
            : '<p>Không có sản phẩm ở trạng thái này.</p>'}
        </div>

        <div class="admin-product-pagination">
          <button id="product-prev" ${page <= 1 ? 'disabled' : ''}>
            Trang trước
          </button>
          <span>Trang ${page} / ${Math.max(1, Math.ceil(data.total / limit))}</span>
          <button id="product-next"
            ${page * limit >= data.total ? 'disabled' : ''}>
            Trang sau
          </button>
        </div>
      </div>`;

    container.querySelector('#product-status').onchange = event => {
      status = event.target.value;
      page = 1;
      load();
    };

    container.querySelector('#product-prev').onclick = () => {
      page--;
      load();
    };

    container.querySelector('#product-next').onclick = () => {
      page++;
      load();
    };

    container.querySelectorAll('[data-hide]').forEach(button => {
      button.onclick = async () => {
        if (busy) return;

        const id = Number(button.dataset.hide);
        const reason = prompt(
          `Lý do ẩn bài #${id}?\nVí dụ: Người bán chuyên / thợ đăng bán`
        );

        if (reason === null) return;

        const cleaned = reason.trim();

        if (cleaned.length < 3 || cleaned.length > 500) {
          alert('Lý do phải có từ 3 đến 500 ký tự.');
          return;
        }

        busy = true;
        button.disabled = true;

        try {
          await api(`/products/${id}/hide`, {
            method: 'POST',
            body: JSON.stringify({reason: cleaned}),
          });

          await load();
        } catch (error) {
          alert('Ẩn sản phẩm thất bại: ' + error.message);
          button.disabled = false;
        } finally {
          busy = false;
        }
      };
    });

    container.querySelectorAll('[data-restore]').forEach(button => {
      button.onclick = async () => {
        if (busy) return;

        const id = Number(button.dataset.restore);

        if (!confirm(`Khôi phục bài #${id} lên Client Macket?`)) {
          return;
        }

        busy = true;
        button.disabled = true;

        try {
          await api(`/products/${id}/restore`, {
            method: 'POST',
          });

          await load();
        } catch (error) {
          alert('Khôi phục thất bại: ' + error.message);
          button.disabled = false;
        } finally {
          busy = false;
        }
      };
    });
  }

  await load();
}
