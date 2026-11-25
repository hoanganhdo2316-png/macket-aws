import { renderClassificationLogs } from './admin-classification-logs.js';
import { renderPrompts } from './admin-prompts.js';
import { renderCredentials } from './admin-credentials.js';
import { renderScheduler } from './admin-scheduler.js';
import { renderCrawler } from './admin-crawler.js';
import { renderAuthors } from './admin-authors.js';
import { renderGroups } from './admin-groups.js';
import { renderProducts } from './admin-products.js';
import './admin.css';

const root = document.querySelector('#admin-root');

const sections = [
  ['layout-dashboard', 'Dashboard'],
  ['package', 'Quản lý sản phẩm'],
  ['users', 'Facebook Groups'],
  ['user-x', 'Author Skip List'],
  ['clock', 'Scheduler'],
  ['settings', 'Crawler Settings'],
  ['history', 'AI Classification Logs'],
  ['key', 'API Credentials'],
  ['bot', 'AI System Prompt']
];

let adminToken = null;

async function api(path, options = {}) {
  if (!adminToken) throw new Error('Chưa đăng nhập');

  const response = await fetch(`/api/admin${path}`, {
    ...options,
    headers: {
      'X-Admin-Token': adminToken,
      'Content-Type': 'application/json',
      ...options.headers
    },
    cache: 'no-store'
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const data = await response.json();
      if (typeof data.detail === 'string') detail = data.detail;
      else if (data.detail) detail += ': ' + JSON.stringify(data.detail);
    } catch {}
    throw new Error(detail);
  }

  return response.json();
}

function renderLogin() {
  root.innerHTML = `
    <main class="login-page">
      <form id="login-form" class="login-card">
        <div class="brand">macket<span>.</span></div>
        <div class="eyebrow">ADMINISTRATION</div>
        <h1>Đăng nhập quản trị</h1>
        <p>Nhập Admin API Token để truy cập hệ thống.</p>
        <label for="token">Admin API Token</label>
        <input id="token" type="password"
               autocomplete="off" required
               placeholder="Nhập token quản trị">
        <button type="submit">Đăng nhập</button>
        <p id="login-error" class="error"></p>
      </form>
    </main>
  `;

  document.querySelector('#login-form').onsubmit = async event => {
    event.preventDefault();

    const token = document.querySelector('#token').value;
    adminToken = token;

    try {
      await api('/groups');
      renderDashboard();
    } catch (error) {
      adminToken = null;
      document.querySelector('#login-error').textContent =
        'Không thể xác thực: ' + error.message;
    }
  };
}

function renderDashboard() {
  root.innerHTML = `
    <div class="admin-layout">
      <aside class="sidebar">
        <div class="brand">macket<span>.</span>
          <small>ADMIN</small>
        </div>
        <nav>
          ${sections.map(([icon, name], i) => `
            <button class="nav-item ${i === 0 ? 'active' : ''}"
                    data-section="${name}">
              <span class="nav-marker"></span>${name}
            </button>
          `).join('')}
        </nav>
        <button id="logout" class="logout">Đăng xuất</button>
      </aside>
      <main class="workspace">
        <header class="workspace-header">
          <div>
            <div class="eyebrow">MACKET CONTROL CENTER</div>
            <h1 id="page-title">Dashboard</h1>
          </div>
          <div class="admin-avatar">A</div>
        </header>
        <section id="page-content">
          <p>Đang tải dữ liệu...</p>
        </section>
      </main>
    </div>
  `;

  document.querySelector('#logout').onclick = () => {
    adminToken = null;
    renderLogin();
  };

  document.querySelectorAll('[data-section]').forEach(button => {
    button.onclick = () => {
      document.querySelectorAll('.nav-item').forEach(item =>
        item.classList.remove('active')
      );

      button.classList.add('active');
      const name = button.dataset.section;

      document.querySelector('#page-title').textContent = name;
      const content = document.querySelector('#page-content');

      if (name === 'Quản lý sản phẩm') {
        renderProducts(content, api);
      } else if (name === 'Facebook Groups') {
        renderGroups(content, api);
      } else if (name === 'Author Skip List') {
        renderAuthors(content, api);
      } else if (name === 'API Credentials') {
        renderCredentials(content, api);
      } else if (name === 'Scheduler') {
        renderScheduler(content, api);
      } else if (name === 'Crawler Settings') {
        renderCrawler(content, api);
      } else if (name === 'AI Classification Logs') {
        renderClassificationLogs(content, api);
      } else if (name === 'AI System Prompt') {
        renderPrompts(content, api);
      } else if (name === 'Dashboard') {
        loadDashboard();
      } else {
        content.innerHTML = `
          <div class="panel">
            <h2>${name}</h2>
            <p>Module đang được kết nối với API quản trị.</p>
          </div>
        `;
      }
    };
  });

  loadDashboard();
}

async function loadDashboard() {
  const container = document.querySelector('#page-content');

  try {
    const [groups, scheduler, crawler] = await Promise.all([
      api('/groups'),
      api('/scheduler'),
      api('/crawler-settings')
    ]);

    const groupList = Array.isArray(groups)
      ? groups
      : (groups.items || groups.groups || []);

    container.innerHTML = `
      <div class="stat-grid">
        <article class="stat-card">
          <span>Facebook Groups</span>
          <strong>${groupList.length}</strong>
          <small>Nhóm đã đăng ký</small>
        </article>
        <article class="stat-card">
          <span>Scheduler</span>
          <strong>${scheduler.enabled ? 'ON' : 'OFF'}</strong>
          <small>${scheduler.interval_minutes} phút/lượt</small>
        </article>
        <article class="stat-card">
          <span>Crawler Limit</span>
          <strong>${crawler.max_posts_per_group}</strong>
          <small>Bài đăng / nhóm</small>
        </article>
      </div>
      <div class="panel">
        <h2>System overview</h2>
        <p>Dữ liệu được đọc trực tiếp từ FastAPI và PostgreSQL RDS.</p>
      </div>
    `;
  } catch (error) {
    container.textContent = 'Lỗi tải Dashboard: ' + error.message;
  }
}

renderLogin();
