# Phần 1: Metadata & Schemas OCR

Bộ tệp độc lập để đưa vào repository chính đang trống. Chép **nội dung bên
trong thư mục này** vào gốc repository chính; không cần code của repo mẫu.

Phạm vi: metadata trang, dòng sau segmentation, dòng sau OCR, liên kết truy
vết và validation. Chưa có xử lý ảnh, model OCR, reconstruction hoặc chấm bài.

## Chuẩn bị môi trường

Python 3.10 trở lên. Chạy các lệnh từ thư mục chứa README này:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Chỉ cần `requirements.txt` nếu không chạy pytest. Không cần NumPy, Pillow
hoặc PyTorch cho phần này.

## Kiểm tra dữ liệu mẫu

```bash
python -m src.contracts examples/segmented_pages.json
python -m src.contracts examples/recognized_lines.json
python -m pytest tests/ -q
```

Test cũng chạy được bằng thư viện chuẩn nếu môi trường chỉ có jsonschema:

```bash
python -m unittest discover -s tests -v
```

CLI in `Valid: ...` và trả mã 0 khi hợp lệ; in `Invalid: ...` và trả mã 1 khi không hợp lệ.
Kết quả hợp lệ chỉ xác nhận contract, không có nghĩa OCR thành công. Mẫu OCR
có một dòng lỗi có chủ đích để minh họa trạng thái `failed`.

## Sử dụng trong Python

```python
from src.contracts.io import read_json
from src.contracts.validators import validate_bundle

data = read_json("examples/recognized_lines.json")
validate_bundle(data)

pages = {page["page_id"]: page for page in data["pages"]}
ordered_lines = sorted(
    data["lines"],
    key=lambda line: (pages[line["page_id"]]["page_index"], line["reading_order"]),
)
```

`validate_bundle()` không sửa input; ném `MetadataValidationError` (kế thừa
`ValueError`) khi có vi phạm. `validate_structure()` chỉ kiểm tra một schema,
không thay thế validation quan hệ trong bundle.

Xem [contract đầy đủ](docs/metadata_contract.md). Các đường dẫn ảnh trong
examples chỉ minh họa, không có ảnh kèm theo. Validator không đọc pixel ảnh.

## Tiêu chí hoàn thành

- Producer/consumer dùng chung identity, hệ tọa độ, thứ tự và đường dẫn.
- Có schema cho trang, dòng segmentation, dòng OCR và wrapper của một run.
- Validator bắt lỗi cấu trúc, bounds, duplicates, thứ tự và reference.
- Hai fixture hợp lệ, gồm nhiều trang và trường hợp OCR lỗi có truy vết.
- Test bao phủ mẫu đúng và các vi phạm chính.

Khi tích hợp với xử lý ảnh, bổ sung kiểm tra ảnh tồn tại, kích thước/pixel crop
và checksum thực tế. Phần này chỉ kiểm tra định dạng hash được khai báo.
