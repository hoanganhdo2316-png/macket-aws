import './style.css';

const API = '/api/products';
const app = document.querySelector('#app');

const icons = {
  heart: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/>',
  home: '<path d="m3 10 9-7 9 7v11H3z"/><path d="M9 21v-7h6v7"/>',
  pin: '<path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0Z"/><circle cx="12" cy="10" r="2"/>',
  back: '<path d="m15 18-6-6 6-6"/>'
};

const svg = name => `<svg width="21" height="21" viewBox="0 0 24 24"
  fill="none" stroke="currentColor" stroke-width="1.8"
  stroke-linecap="round" stroke-linejoin="round"
  aria-hidden="true">${icons[name] || ''}</svg>`;

const esc = value => String(value ?? '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#39;');

function safeUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' ? url.href : '';
  } catch {
    return '';
  }
}

const money = value => {
  const n = Number(value);
  return Number.isFinite(n) && n > 0
    ? new Intl.NumberFormat('vi-VN').format(n) + 'đ'
    : 'Liên hệ';
};

const state = {
  items: [],
  total: 0,
  page: 0,
  limit: 50,
  loading: false,
  error: '',
  query: '',
  category: 'all',
  sort: 'new',
  tab: 'home',
  detail: null,
  imageIndex: 0,
  favorites: new Set(),
};

try {
  state.favorites = new Set(
    JSON.parse(localStorage.getItem('macket-favorites') || '[]')
      .map(Number)
  );
} catch {
  state.favorites = new Set();
}

const product = post => post.products?.[0] || {};

function titleOf(post) {
  const p = product(post);
  return [p.brand, p.model].filter(Boolean).join(' ') ||
    'Thiết bị điện tử';
}

function categoryOf(post) {
  return String(product(post).category || 'Khác').trim();
}

function priceOf(post) {
  const value = Number(product(post).price_vnd);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function dateOf(post) {
  if (!post.published_at) return '';
  const value = post.published_at.replace(' ', 'T');
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleDateString('vi-VN');
}

function filtered() {
  let items = state.items.filter(post => {
    if (state.category !== 'all' &&
        categoryOf(post) !== state.category) return false;

    if (state.tab === 'favorites' &&
        !state.favorites.has(post.id)) return false;

    const haystack = [
      titleOf(post), post.content, post.location,
      JSON.stringify(product(post).specifications || {})
    ].join(' ').toLocaleLowerCase('vi');

    return haystack.includes(state.query.toLocaleLowerCase('vi'));
  });

  if (state.sort === 'price') {
    items.sort((a, b) =>
      (priceOf(a) ?? Infinity) - (priceOf(b) ?? Infinity));
  }

  return items;
}

function imageHtml(url, alt, className = '') {
  const safe = safeUrl(url);

  return safe
    ? `<img class="${className}" src="${esc(safe)}"
        alt="${esc(alt)}" loading="lazy"
        referrerpolicy="no-referrer">`
    : `<div class="no-photo">Chưa có ảnh</div>`;
}

function card(post) {
  const saved = state.favorites.has(post.id);

  return `
    <article class="listing" data-open="${post.id}" tabindex="0"
      role="button" aria-label="Xem ${esc(titleOf(post))}">
      <div class="listing-photo">
        ${imageHtml(post.thumbnail_url, titleOf(post))}
        <span class="photo-badge">Người bán cá nhân</span>
        <button class="favorite ${saved ? 'saved' : ''}"
          data-favorite="${post.id}" aria-label="Lưu tin">
          ${svg('heart')}
        </button>
      </div>
      <div class="listing-body">
        <div class="listing-title">${esc(titleOf(post))}</div>
        <div class="price">${money(priceOf(post))}</div>
        <div class="meta">
          <span>${svg('pin')} ${esc(post.location || 'Chưa rõ vị trí')}</span>
          <span>${esc(dateOf(post))}</span>
        </div>
      </div>
    </article>`;
}

function renderCards() {
  const grid = document.querySelector('#listing-grid');
  const count = document.querySelector('#feed-count');
  if (!grid) return;

  const items = filtered();
  count.textContent = `${items.length} tin đã tải`;

  grid.innerHTML = items.length
    ? items.map(card).join('')
    : `<div class="empty">Chưa có sản phẩm phù hợp.</div>`;

  const more = document.querySelector('#load-more');
  if (more) {
    more.hidden = state.items.length >= state.total;
    more.disabled = state.loading;
  }
}

function renderHome() {
  const categories = [...new Set(state.items.map(categoryOf))];

  app.innerHTML = `
    <div class="shell">
      <header class="hero">
        <div class="topbar">
          <div class="logo">macket<span>.</span></div>
          <div class="top-actions">
            <button class="icon-btn" data-tab="favorites"
              aria-label="Tin đã lưu">${svg('heart')}</button>
          </div>
        </div>
        <div class="headline">
          <div class="eyebrow">ELECTRONICS MARKETPLACE</div>
          <h1>Đồ công nghệ,<br>tìm đúng người bán.</h1>
          <p>Tin rao thực tế · Ưu tiên người bán cá nhân</p>
        </div>
        <div class="search-wrap">
          <div class="search-field">
            ${svg('search')}
            <input id="search" type="search"
              placeholder="Tìm máy, thương hiệu, cấu hình..."
              value="${esc(state.query)}"
              aria-label="Tìm sản phẩm">
          </div>
        </div>
      </header>

      <main>
        <section class="categories-section">
          <div class="section-title">
            <h2>Danh mục</h2>
            <span>Sản phẩm đã xác minh bằng AI</span>
          </div>
          <div class="category-list">
            ${['all', ...categories].map(category => `
              <button class="category ${state.category === category ? 'active' : ''}"
                data-category="${esc(category)}">
                <span class="category-art">⌘</span>
                <span>${esc(category === 'all' ? 'Tất cả' : category)}</span>
              </button>
            `).join('')}
          </div>
        </section>

        <section class="feed">
          <div class="feed-head">
            <div>
              <div class="feed-kicker">MACKET MARKETPLACE</div>
              <h2>${state.tab === 'favorites' ? 'Tin đã lưu' : 'Tin đang được rao bán'}</h2>
            </div>
            <span class="count" id="feed-count"></span>
          </div>

          <div class="filter-row">
            <button class="chip ${state.sort === 'new' ? 'selected' : ''}"
              data-sort="new">Mới nhất</button>
            <button class="chip ${state.sort === 'price' ? 'selected' : ''}"
              data-sort="price">Giá thấp trước</button>
          </div>

          ${state.error
            ? `<p class="api-error">${esc(state.error)}</p>`
            : ''}

          <div class="listing-grid" id="listing-grid"></div>

          <button class="load-more" id="load-more" hidden>
            Tải thêm sản phẩm
          </button>
        </section>
      </main>

      <nav class="bottom-nav">
        <button class="nav-btn ${state.tab === 'home' ? 'active' : ''}"
          data-tab="home">${svg('home')}<span>Khám phá</span></button>
        <button class="nav-btn ${state.tab === 'favorites' ? 'active' : ''}"
          data-tab="favorites">${svg('heart')}<span>Đã lưu</span></button>
      </nav>
    </div>`;

  renderCards();
}

function renderDetail() {
  const post = state.detail;
  if (!post) return renderHome();

  const p = product(post);
  const images = post.images || [];
  const image = images[state.imageIndex];
  const facebookUrl = safeUrl(post.facebook_url);

  const specs = p.specifications || {};
  const specRows = Array.isArray(specs)
    ? specs
        .filter(item => item && typeof item === 'object')
        .map(item => [item.name ?? '', item.value ?? ''])
    : (typeof specs === 'object' && specs !== null
        ? Object.entries(specs)
        : []);

  app.innerHTML = `
    <div class="shell">
      <div class="detail-header">
        <button class="icon-btn" data-back aria-label="Quay lại">
          ${svg('back')}
        </button>
        <div class="logo">macket<span>.</span></div>
        <div></div>
      </div>

      <main class="detail-page">
        <div class="detail-photo">
          ${imageHtml(image?.url, titleOf(post))}
        </div>

        ${images.length > 1 ? `
          <div class="gallery">
            ${images.map((item, index) => `
              <button class="gallery-item ${state.imageIndex === index ? 'active' : ''}"
                data-image="${index}" aria-label="Ảnh ${index + 1}">
                ${imageHtml(item.url, `Ảnh ${index + 1}`)}
              </button>
            `).join('')}
          </div>
        ` : ''}

        <div class="detail-content">
          <div class="detail-category">${esc(categoryOf(post))}</div>
          <h1>${esc(titleOf(post))}</h1>
          <div class="detail-price">${money(priceOf(post))}</div>
          <p class="detail-meta">
            ${esc(post.location || 'Chưa rõ vị trí')}
            · ${esc(dateOf(post))}
          </p>

          ${p.condition ? `
            <div class="detail-section">
              <h2>Tình trạng</h2>
              <p>${esc(p.condition)}</p>
            </div>` : ''}

          ${specRows.length ? `
            <div class="detail-section">
              <h2>Thông số kỹ thuật</h2>
              <div class="spec-list">
                ${specRows.map(([key, value]) => `
                  <div class="spec-row">
                    <span>${esc(key)}</span>
                    <strong>${esc(
                      typeof value === 'object' ? JSON.stringify(value) : value
                    )}</strong>
                  </div>
                `).join('')}
              </div>
            </div>` : ''}

          <div class="detail-section">
            <h2>Nội dung bài đăng gốc</h2>
            <p class="post-content">${esc(post.content || 'Không có nội dung')}</p>
          </div>

          <div class="detail-section">
            <h2>Người đăng</h2>
            <p>${esc(post.author_name || 'Không rõ')}</p>
          </div>

          ${facebookUrl ? `
            <a class="facebook-link" href="${esc(facebookUrl)}"
              target="_blank" rel="noopener noreferrer">
              Xem bài đăng trên Facebook
            </a>` : ''}
        </div>
      </main>
    </div>`;
}

async function loadMore() {
  if (state.loading || (state.page && state.items.length >= state.total)) return;

  state.loading = true;
  try {
    const page = state.page + 1;
    const res = await fetch(`${API}?page=${page}&limit=${state.limit}`,
      { cache: 'no-store' });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json();
    state.items.push(...data.items);
    state.total = data.total;
    state.page = page;
    state.error = '';
  } catch {
    state.error = 'Không tải được dữ liệu sản phẩm. Vui lòng thử lại.';
  } finally {
    state.loading = false;
    renderHome();
  }
}

async function openDetail(id) {
  try {
    const res = await fetch(`${API}/${id}`, {cache: 'no-store'});
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    state.detail = await res.json();
    state.imageIndex = 0;
    history.pushState({product: id}, '', `#product-${id}`);
    renderDetail();
    window.scrollTo(0, 0);
  } catch {
    alert('Không thể tải thông tin sản phẩm.');
  }
}

document.addEventListener('click', event => {
  const favorite = event.target.closest('[data-favorite]');
  if (favorite) {
    event.stopPropagation();
    const id = Number(favorite.dataset.favorite);
    state.favorites.has(id)
      ? state.favorites.delete(id)
      : state.favorites.add(id);
    localStorage.setItem('macket-favorites',
      JSON.stringify([...state.favorites]));
    renderCards();
    return;
  }

  const open = event.target.closest('[data-open]');
  if (open) return void openDetail(Number(open.dataset.open));

  const category = event.target.closest('[data-category]');
  if (category) {
    state.category = category.dataset.category;
    renderHome();
    return;
  }

  const sort = event.target.closest('[data-sort]');
  if (sort) {
    state.sort = sort.dataset.sort;
    renderHome();
    return;
  }

  const tab = event.target.closest('[data-tab]');
  if (tab) {
    state.tab = tab.dataset.tab;
    state.category = 'all';
    renderHome();
    return;
  }

  const image = event.target.closest('[data-image]');
  if (image) {
    state.imageIndex = Number(image.dataset.image);
    renderDetail();
    return;
  }

  if (event.target.closest('[data-back]')) {
    history.back();
    return;
  }

  if (event.target.closest('#load-more')) loadMore();
});

document.addEventListener('keydown', event => {
  if (event.key !== 'Enter') return;
  const card = event.target.closest('[data-open]');
  if (card && event.target === card)
    openDetail(Number(card.dataset.open));
});

document.addEventListener('input', event => {
  if (event.target.id === 'search') {
    state.query = event.target.value;
    renderCards();
  }
});

window.addEventListener('popstate', async () => {
  const match = location.hash.match(/^#product-(\d+)$/);
  if (!match) {
    state.detail = null;
    renderHome();
    return;
  }

  try {
    const res = await fetch(`${API}/${match[1]}`, {cache: 'no-store'});
    if (!res.ok) throw new Error('Not found');
    state.detail = await res.json();
    state.imageIndex = 0;
    renderDetail();
  } catch {
    state.detail = null;
    renderHome();
  }
});

renderHome();
loadMore().then(() => {
  const match = location.hash.match(/^#product-(\d+)$/);
  if (match) {
    // Load an existing deep link without changing browser history.
    fetch(`${API}/${match[1]}`, {cache: 'no-store'})
      .then(res => {
        if (!res.ok) throw new Error('Not found');
        return res.json();
      })
      .then(data => {
        state.detail = data;
        state.imageIndex = 0;
        renderDetail();
      })
      .catch(() => {});
  }
});
