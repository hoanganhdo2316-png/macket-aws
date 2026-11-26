# Macket Apify Collector v1.0 — Python SDK / Docker

Thu thập các bài đăng Group Facebook công khai thông qua Actor `dGw5RQgZjVug05E1h` (Monkey D. Scraping), **không** tự crawl Facebook.

## Cấu trúc

```text
D:\macket\
├── apify\
│   ├── app/collector.py        # Core SDK + chuẩn hóa + SQLite + logging
│   ├── collector.py            # Entry point
│   ├── config/groups.json      # 10 group và URL gốc (trích từ bảng Excel)
│   ├── config/settings.json    # Giới hạn bài / phí
│   ├── config/blocked_sellers.json  # Chỉ seller được gán rõ ràng
│   ├── data/                   # authors_seen.json, seen_posts.sqlite3, runs/ (tự tạo)
│   ├── logs/                   # collector.log (tự tạo)
│   ├── tests/
│   ├── .env.example
│   ├── .gitignore
│   ├── Dockerfile
│   ├── compose.yaml
│   └── requirements.txt
├── backend/                    # API web riêng (không nằm trong gói này)
└── frontend/                   # UI web riêng (không nằm trong gói này)
```

## Chạy trên Windows

Giải nén, chép thư mục `apify` vào `D:\macket\apify`, tránh ghi đè `.env` đang có. Tạo `.env` cùng cấp `collector.py`:

```dotenv
APIFY_TOKEN=apify_api_YOUR_REAL_TOKEN
```

Trong PowerShell:

```powershell
cd D:\macket\apify
py -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python collector.py --dry-run
python collector.py
python -m unittest discover -s tests -v
```

`--dry-run` không gọi Actor và không mất phí.

## Cấu hình mặc định

- 10 group có URL từ bản Top 10 / file Excel gốc, đã chép sẵn vào `config/groups.json` (không phải đọc Excel khi chạy Docker).
- `maxPostsPerGroup=3`: tối đa 3 bài cho mỗi Group từ phía Actor (không đảm bảo đủ 3 bài nếu không có bài phù hợp).
- `onlyPostsNewerThan='today'` và `timeZone='Asia/Ho_Chi_Minh'`, đồng thời **lọc ngày ở local** để bảo đảm bài nằm trong ngày Việt Nam.
- `onlyNewPosts=True`: cơ chế ghi nhớ bài cũ do Actor quản lý; chỉ những lần bật `True` mới ghi vào lịch sử phía Actor.
- SQLite chặn trùng `postId` ở local. Không dùng ngày đăng làm khóa chống trùng.
- `max_total_charge_usd=0.30` mỗi run, `max_items=30` qua Apify SDK. Đây là mức trần được yêu cầu, không phải dự báo hóa đơn thực tế.
- Toàn bộ dữ liệu gốc nằm trong trường `raw` của file JSON; ảnh lưu bằng URL, **không tải file ảnh**.

## Author và blacklist

`data/authors_seen.json` ghi nhận author ID, tên, URL, các mốc đã gặp, nhãn mặc định `unknown`. **Lịch sử tác giả không tự động chuyển thành blacklist.**

`config/blocked_sellers.json` chứa duy nhất tác giả đã xác nhận là shop. Ví dụ:

```json
{
  "sellers": [
    {"id": "100013286231548", "classification": "seller"},
    {"profile_url": "https://www.facebook.com/some-shop", "classification": "seller"}
  ]
}
```

Chỉ mục có `classification: "seller"` mới truyền vào `excludeAuthors` của Actor. Tên có thể trùng nên nên ưu tiên ID hoặc URL. Nhãn `seller` trong `authors_seen.json` một mình **không** kích hoạt blacklist; file `blocked_sellers.json` mới là nguồn điều khiển chính thức. Chưa có AI phân loại shop; sẽ tích hợp ở module riêng sau.

## Dữ liệu và logging

- `data/runs/posts_YYYYMMDD_HHMMSS_microseconds.json` — danh sách bài mới đã chuẩn hóa + dữ liệu gốc.
- `data/runs/summary_...json` — số bản ghi, ID run Apify, các lý do bỏ qua.
- `data/seen_posts.sqlite3` — chống trùng local.
- `data/authors_seen.json` — lịch sử tác giả.
- `logs/collector.log` — log start, status, số bài, đầy đủ caption, từng URL ảnh, author, lỗi. File log có thể có số điện thoại/URL do người đăng công khai; bảo vệ file này.

Nếu chạy lần đầu với `onlyNewPosts=True`, dữ liệu của những lần chạy Actor trước đó với `False` có thể vẫn xuất hiện. Chỉ nên chạy một instance của collector mỗi lần để tránh xung đột file dữ liệu/SQLite.

## Docker

Chạy từ `D:\macket\apify` hoặc thư mục tương đương trên Linux:

```bash
docker compose build
docker compose run --rm collector python collector.py --dry-run
docker compose run --rm collector
```

Hai thư mục `data` và `logs` được bind mount nên tồn tại khi container bị xóa. Với Linux EC2, user container UID 10001 cần quyền ghi vào thư mục mount; trước khi chạy có thể dùng `sudo chown -R 10001:10001 data logs` (chỉ với hai thư mục này). Không mount hay commit `.env` vào image: Compose chỉ đưa token vào biến môi trường khi chạy.

## Lưu ý

Actor có thể trả kết quả thiếu trường hoặc không đủ 3 bài/Group. Bài thiếu thời gian hoặc ID được bỏ qua để tránh đưa dữ liệu không xác minh được vào Macket; chi tiết ở summary. Không cam kết crawl đủ 30 bài trong mọi lần chạy. Quyền thu thập và tái sử dụng nội dung phải tuân thủ điều khoản nền tảng và quyền riêng tư của người đăng.

## Quét ngay trong Admin

Admin → **Crawler Settings** dùng `POST /api/scan/trigger` và `GET /api/scan/status` với `X-Admin-Token`. FastAPI gửi `InvocationType=Event` tới Lambda `macket-apify-trigger` ở Singapore. Lambda dùng cùng bước nhận quyền chạy cho cả yêu cầu thủ công và Scheduler. Bước này dùng bảng một dòng `collector_scan` trên PostgreSQL hiện có. Lambda kiểm tra các lượt Apify còn hoạt động trước khi khởi động Actor. Phần đọc trạng thái dùng ID run Apify và bảng `crawl_runs` để phân biệt đã quét xong với đã nhập dữ liệu.

Thứ tự phát hành cần phê duyệt riêng

1. Áp dụng [migration](../backend/migrations/001_collector_scan.sql) trong một transaction rồi cập nhật Backend. Giữ `MACKET_MANUAL_SCAN_ENABLED` chưa đặt trong lúc chuyển đổi.
2. Cập nhật image của Lambda hiện có để cả hai nguồn cùng nhận quyền chạy qua Backend. Giữ nguyên cấu hình Scheduler và webhook. Chờ mọi invocation dùng image cũ kết thúc trước khi bật quét thủ công.
3. Đặt `MACKET_MANUAL_SCAN_ENABLED=true` trong runtime env của Backend. Kiểm tra Admin và trạng thái trước khi gửi lượt quét đầu tiên.

Yêu cầu thủ công đang chờ Lambda hết hạn sau 5 phút. Lambda đến muộn không thể nhận lại yêu cầu đã hết hạn. Khi kết quả khởi động Apify chưa xác minh được, pipeline giữ trạng thái `UNKNOWN` và khóa cả hai đường khởi động lượt mới. Người vận hành cần đối chiếu log Lambda và run của Actor trước khi gỡ khóa. Khi đã xác nhận invocation kết thúc, cập nhật chính dòng có `scan_id` tương ứng, tăng `revision` và cập nhật `updated_at`. Nếu tìm được run đã khởi động, lưu `apify_run_id` và chuyển trạng thái sang `RUNNING` để tiếp tục theo dõi. Chỉ chuyển sang `FAILED` khi đã xác nhận Apify không nhận lượt khởi động đó.
