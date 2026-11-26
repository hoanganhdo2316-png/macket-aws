const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
})[char]);
const number = value => Number(value || 0).toLocaleString('vi-VN');

export async function renderScanHistory(container, api) {
  container.innerHTML = '<div class="panel">Đang tải lịch sử quét...</div>';
  try {
    const data = await api('/scan-history?limit=50');
    const rows = data.items.map(run => `<tr>
      <td>${escapeHtml(run.started_at ? new Date(run.started_at).toLocaleString('vi-VN') : '-')}</td>
      <td>${run.source === 'manual' ? 'Thủ công' : run.source === 'scheduler' ? 'Lịch tự động' : 'Chưa liên kết'}</td>
      <td><code>${escapeHtml(run.apify_run_id)}</code><br><small>${escapeHtml(run.status)}</small></td>
      <td>${number(run.total_posts)} / ${number(run.inserted_posts)} / ${number(run.duplicate_posts)}<br><small>Tổng / mới / trùng · Bỏ qua ${number(run.skipped_posts)}</small></td>
      <td>${number(run.classified_posts)} hoàn tất<br><small>Chờ ${number(run.classification_pending)} · Đang xử lý ${number(run.classification_processing)}</small><br><small>Cá nhân ${number(run.individual_posts)} · Cửa hàng ${number(run.seller_posts)}</small></td>
      <td>${number(run.extraction_completed)} hoàn tất<br><small>Chờ/lỗi ${number(run.extraction_pending)} · Đang xử lý ${number(run.extraction_processing)}</small></td>
      <td>${number(run.media_completed_posts)} / ${number(run.media_eligible_posts)} media<br><small>${number(run.client_eligible_posts)} hiển thị</small></td>
      <td>$${Number(run.classification_cost_usd || 0).toFixed(6)}<br><small>+ $${Number(run.extraction_cost_usd || 0).toFixed(6)}</small></td>
      <td>${escapeHtml(run.error_message || '-')}</td></tr>`).join('');
    container.innerHTML = `<div class="groups-toolbar"><div><h2>Scan History</h2><p>${number(data.total)} lượt ingestion. Các lượt trước migration chưa có tiến độ AI theo scan.</p></div></div>
      <section class="panel table-wrap"><table class="scan-history-table"><thead><tr><th>Thời gian</th><th>Nguồn</th><th>Run</th><th>Thu thập</th><th>Phân loại</th><th>Trích xuất</th><th>Hiển thị</th><th>Chi phí AI</th><th>Lỗi</th></tr></thead><tbody>${rows || '<tr><td colspan="9">Chưa có lượt quét.</td></tr>'}</tbody></table></section>`;
  } catch (error) {
    container.textContent = 'Không thể tải Scan History: ' + error.message;
  }
}
