# disk-cleaner

Công cụ dọn dẹp ổ đĩa Windows, hỗ trợ cả CLI và GUI, dùng chung một lõi xử lý.

## Mục tiêu

Tự động hóa việc quét dung lượng, phân loại mục tiêu dọn dẹp, và thực thi các hành động an toàn — thay vì phải gõ lệnh PowerShell thủ công rồi kiểm tra từng bước.

## Nguyên tắc an toàn

Tool này chạm vào hệ thống tệp, nên mọi hành động đều tuân theo các quy tắc cứng:

1. **Ba mức safety**: `safe` (cache/tạm, xóa được), `caution` (cần xem xét, chỉ gợi ý), `dangerous` (không bao giờ động vào).
2. **`dangerous` bị chặn ở tầng code**, không chỉ dựa vào config. Kể cả khi ai đó sửa `targets.json`, tool vẫn từ chối xử lý.
3. **Dry-run mặc định**: mọi hành động xóa đều hiển thị trước những gì sẽ xóa, chỉ thực thi khi người dùng xác nhận.
4. **Kiểm tra symlink/junction**: từ chối xóa nếu đường dẫn là symlink hoặc junction, tránh xóa nhầm thư mục đích.
5. **Bảo vệ thư mục gốc**: `C:\Windows`, `C:\Program Files`, `C:\ProgramData`, `C:\Users` không bao giờ bị xóa, kể cả khi được khai báo trong config.
6. **Log mọi hành động**: ghi vào `logs/YYYY-MM-DD.log` trước và sau khi xóa.
7. **Không xóa thư mục gốc**: `delete_contents` chỉ xóa nội dung bên trong, giữ thư mục. `delete_folder` chỉ xóa thư mục cụ thể, không xóa cha.

## Kiến trúc

```
disk-cleaner/
├── core/ # Lõi xử lý, dùng chung cho CLI và GUI
│ ├── models.py # Dataclass Target, enum Safety/Action, hàm kiểm tra an toàn
│ ├── config.py # Đọc và gộp targets.default.json + targets.local.json
│ ├── scanner.py # Quét dung lượng thư mục (chưa viết)
│ ├── actions.py # Thực thi hành động xóa (chưa viết)
│ └── logger.py # Ghi log (chưa viết)
├── cli/
│ └── main.py # Giao diện dòng lệnh (chưa viết)
├── gui/
│ └── main.py # Giao diện đồ họa Tkinter (chưa viết)
├── config/
│ ├── targets.default.json # Bản chung, public cho mọi người
│ └── targets.local.json # Bản cá nhân, không public (.gitignore)
├── logs/ # Log tự động
└── README.md
```

## Cấu hình

Tool đọc hai file JSON:

- `config/targets.default.json`: bản chung, chứa các mục phổ quát (temp, browser cache, WinSxS, các thư mục dangerous). File này được public.
- `config/targets.local.json`: bản cá nhân, chứa các mục đặc thù máy bạn (CapCut, Docker, Android SDK, VS Code cpptools...). File này **không public**, thêm vào `.gitignore`.

Hai file được gộp theo `id`: nếu trùng `id`, bản local ghi đè bản default. Điều này cho phép tùy chỉnh một mục có sẵn mà không cần sửa bản chung.

### Cấu trúc một target

```json
{
  "id": "chrome_cache",
  "path": "%LOCALAPPDATA%\\Google\\Chrome\\User Data\\Default\\Cache",
  "category": "browser_cache",
  "safety": "safe",
  "action": "delete_contents",
  "note": "Cache Chrome, tự tạo lại"
}
```

- id: định danh duy nhất.
- path: đường dẫn, hỗ trợ biến môi trường (%TEMP%, %LOCALAPPDATA%...).
- category: nhóm (temp, browser_cache, dev_cache, system...).
- safety: safe | caution | dangerous.
- action: delete_contents | delete_folder | dism_cleanup | manual_review | never_touch.
- note: ghi chú hiển thị cho người dùng.

## Cài đặt

Yêu cầu: Python 3.10+ (do dùng cú pháp X | None và from **future** import annotations).

```powershell
python --version
```

## Sử dụng

### CLI (chưa hoàn thiện)

```powershell
python -m cli.main scan            # Quét và hiển thị dung lượng
python -m cli.main scan --verbose  # Hiển thị cả mục bị skip và lý do
python -m cli.main clean --dry-run # Xem trước sẽ xóa gì
python -m cli.main clean           # Xóa thật (có xác nhận)
```

### GUI (chưa hoàn thiện)

```powershell
python -m gui.main
```

## Phát triển

Chạy kiểm tra cú pháp

```powershell
python -c "from core.config import load_targets; v, s = load_targets(only_valid=False); print(f'valid={len(v)}, skipped={len(s)}')"
```

Thêm mục tiêu mới

1. Mở config/targets.local.json (hoặc targets.default.json nếu là mục phổ quát).
2. Thêm object mới vào mảng targets, đảm bảo đủ trường bắt buộc.
3. Chạy lại lệnh kiểm tra để xác nhận target được nhận diện.

## Quy ước code

- Không có lệnh xóa nào trong models.py và config.py. Mọi hành động xóa tập trung ở actions.py, và phải gọi validate_target() trước khi thực thi.
- Mọi hàm public có docstring.
- Dùng pathlib.Path thay vì chuỗi đường dẫn.
- Xử lý lỗi quyền truy cập bằng cách bỏ qua, không crash.

## Giấy phép

MIT License.
