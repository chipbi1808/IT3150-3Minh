# Contract metadata OCR

## 1. Phạm vi và luồng dữ liệu

Contract dùng để trao đổi dữ liệu giữa preprocessing, segmentation, OCR và
reconstruction. Phần này định nghĩa dữ liệu và kiểm tra tính hợp lệ; không
triển khai các thuật toán xử lý ảnh hoặc model.

```text
Preprocessing -> pages[]
Segmentation -> pages[] + lines[] (stage=segmentation)
OCR          -> pages[] + lines[] có text/status/issues (stage=ocr)
Reconstruction đọc stage=ocr và giữ refs tới dòng nguồn
```

Một file JSON chứa một bundle của một bài thi trong một lần chạy. Một bundle
chỉ chứa một loại line record, được xác định bởi `stage`. Không trộn các dòng
đã OCR và chưa OCR trong cùng bundle.

## 2. Wrapper của bundle

| Trường | Kiểu | Quy tắc |
| --- | --- | --- |
| `schema_version` | integer | Chính xác là 1. |
| `exam_id` | string | Định danh bài thi/bài nộp cụ thể; không dùng chung cho hai bài nộp khác nhau. |
| `run_id` | string | Định danh lần chạy; caller tạo mới khi chạy lại hoặc sinh artifact mới. |
| `stage` | string | `segmentation` hoặc `ocr`. |
| `pages` | array | Ít nhất một page record. |
| `lines` | array | Line records tương ứng với stage; có thể rỗng nếu không có trang `ok`. |
| `metadata` | object | Thông tin mở rộng như cấu hình, model, ghi chú hoặc đường dẫn sidecar. |

Tất cả trường trong bảng đều bắt buộc. Các ID phải là chuỗi có ít nhất một
ký tự không phải khoảng trắng, phân biệt hoa/thường và được so sánh nguyên
trạng. Validator không trim ID hoặc tự đổi kiểu số thành chuỗi.

Records từ chối trường chưa được khai báo. Chỉ object `metadata` ở wrapper
cho phép mở rộng; nó vẫn phải chứa giá trị JSON hợp lệ.

## 3. Page record

| Trường | Kiểu | Ý nghĩa |
| --- | --- | --- |
| `schema_version` | integer | 1. |
| `exam_id` | string | Phải khớp bundle. |
| `page_id` | string | Duy nhất trong bundle; là định danh, không phải thứ tự. |
| `page_index` | integer | Thứ tự trang, bắt đầu 1, duy nhất và liên tiếp. |
| `original_image_path` | string | Đường dẫn tương đối tới ảnh gốc. |
| `processed_image_path` | string | Đường dẫn tương đối tới ảnh đã xử lý. |
| `original_size` | object | `{ "width": ..., "height": ... }`, số nguyên dương. |
| `processed_size` | object | Cùng cấu trúc, đo trên ảnh đã xử lý. |
| `original_to_processed` | array 3x3 | Ma trận affine từ ảnh gốc sang ảnh đã xử lý. |
| `preprocessing_sha256` | string | 64 ký tự hex thường, fingerprint cấu hình preprocessing. |
| `original_sha256` | string | 64 ký tự hex thường, SHA-256 của bytes file ảnh gốc. |
| `status` | string | `ok`, `blank`, `review_required`, `failed`. |
| `issues` | array | Danh sách vấn đề; dùng `[]` nếu không có. |

Tất cả trường trên đều bắt buộc. Quy tắc trạng thái:

- `ok`: segmentation đã tìm được ít nhất một dòng.
- `blank`: trang được xác nhận trắng; không được có dòng.
- `review_required`: cần kiểm tra, ví dụ không tìm được dòng nhưng trang có mực.
- `failed`: xử lý trang thất bại; có thể giữ các dòng của kết quả một phần.
- `review_required` và `failed` phải có ít nhất một issue `severity=error`.

Page status phản ánh xử lý trang/segmentation. Page `ok` vẫn có thể chứa dòng
OCR `failed`; consumer phải đọc cả hai mức trạng thái. Nếu không xác định được
kích thước ảnh do decode thất bại, không dựng page record giả với kích thước 0.
Ghi lỗi decode ở báo cáo chạy riêng; báo cáo lỗi đó nằm ngoài contract này.

## 4. Hệ tọa độ và biến đổi

Gốc `(0, 0)` ở góc trên trái; x tăng sang phải, y tăng xuống dưới. Frame gốc
là raster vừa decode trước áp EXIF. `original_to_processed` bao gồm toàn bộ
EXIF orientation, rotation, resize và các affine khác đã áp dụng.

Quy ước vector cột:

```text
[x_processed, y_processed, 1]^T = M @ [x_original, y_original, 1]^T
```

M phải chứa số hữu hạn, khả nghịch, hàng cuối `[0, 0, 1]`. Identity matrix được
dùng khi không biến đổi hình học. Chỉ hỗ trợ affine trong v1; perspective
transform cần phiên bản contract mới. Validator kiểm tra hình dạng và tính
khả nghịch, không chứng minh rằng M khớp thuật toán xử lý ảnh đã chạy.

Để fingerprint cấu hình, producer nên dùng một quy tắc serialize JSON ổn định:
UTF-8, key được sort, không khoảng trắng phụ, không NaN/Infinity, sau đó SHA-256.
Validator hiện chỉ kiểm định dạng hash, không tính lại hash hoặc đọc ảnh.

## 5. Line record sau segmentation

| Trường | Kiểu | Quy tắc |
| --- | --- | --- |
| `schema_version` | integer | 1. |
| `exam_id` | string | Khớp bundle. |
| `page_id` | string | Trang đã tồn tại trong `pages`. |
| `line_id` | string | Duy nhất trong trang. |
| `bbox` | array 4 integers | `[x0, y0, x1, y1]` trên processed page. |
| `reading_order` | integer | Từ 1, duy nhất và liên tiếp trong mỗi trang. |
| `image_path` | string | Đường dẫn crop tương đối, duy nhất trong bundle. |
| `source_detection_id` | string, tùy chọn | Liên kết detection trung gian; duy nhất trong trang nếu được cung cấp. |

Mọi trường trừ `source_detection_id` đều bắt buộc. Chưa được thêm `text`,
`status` hoặc `issues` vào line segmentation.

Khóa đầy đủ của dòng là `(exam_id, page_id, line_id)`. Ví dụ `p01/line_0001`
và `p02/line_0001` là hai dòng khác nhau. Khóa này có phạm vi một run; khi lưu
registry nhiều run, dùng thêm `run_id` từ wrapper để tránh nhầm phiên bản.

BBox có biên phải/dưới exclusive:

```text
0 <= x0 < x1 <= processed_width
0 <= y0 < y1 <= processed_height
crop_width  = x1 - x0
crop_height = y1 - y0
```

Ví dụ `[10, 20, 210, 70]` có kích thước 200x50. BBox không phải `[x, y, w, h]`.
Resize crop để đưa vào model không làm thay đổi bbox trên processed page.

Trong Python, `bool` và `float` như `1.0` không được chấp nhận thay số nguyên.
JSON Schema tiêu chuẩn có thể coi `1.0` là integer; validator Python ở đây
chủ động kiểm tra chặt hơn để producer không ghi kiểu thiếu nhất quán.

## 6. Line record sau OCR

Giữ nguyên các trường segmentation và thêm ba trường bắt buộc:

| Trường | Kiểu | Quy tắc |
| --- | --- | --- |
| `text` | string | Text nhận dạng, giữ tiếng Việt; không sửa chính tả trong validator. |
| `status` | string | `ok`, `empty_prediction`, `failed`. |
| `issues` | array | Danh sách issue, có thể rỗng khi thành công. |

- `ok`: text phải có ít nhất một ký tự không phải khoảng trắng.
- `empty_prediction`: model chạy nhưng trả chuỗi rỗng, `text` phải chính xác `""`.
- `failed`: inference thất bại hoặc kết quả không đáng tin. Có thể giữ text
  dở dang để debug; consumer không được dùng nó như kết quả đã xác nhận.
- `empty_prediction` và `failed` phải có issue `severity=error`.

Text rỗng/lỗi OCR không có nghĩa học sinh không làm bài. Việc xác nhận không
làm bài là quyết định của bước reconstruction/review sau này.

Metadata model có thể đặt trong wrapper, ví dụ:

```json
{"recognizer": "crnn", "checkpoint": "models/ocr_v1.pt"}
```

## 7. Issue và liên kết truy vết

Mọi issue có đúng năm trường bắt buộc:

| Trường | Kiểu | Ý nghĩa |
| --- | --- | --- |
| `code` | string | Mã lỗi ổn định, ví dụ `OCRInferenceFailed`. |
| `stage` | string | Bước phát sinh như `preprocessing`, `segmentation`, `ocr`. |
| `severity` | string | `warning` hoặc `error`. |
| `message` | string | Mô tả để người đọc hiểu. |
| `refs` | array | Các line reference liên quan, không trùng và phải tồn tại trong bundle. |

Line reference là object, không phải chuỗi ghép hoặc số dòng JSON:

```json
{"exam_id": "exam_demo", "page_id": "p02", "line_id": "line_0001"}
```

Issue áp dụng toàn trang có thể dùng `refs: []`; page chứa issue đã xác định
ngữ cảnh trang. Các bước reconstruction sau này nên giữ reference này khi
gom nhiều dòng thành một answer.

## 8. Đường dẫn và thứ tự

Tất cả đường dẫn ảnh dùng POSIX `/`, tương đối với **artifact root do caller
cung cấp**. Với examples, artifact root mặc định để minh họa là `examples/`.
Không suy root từ working directory. Khi đọc ảnh thật, gọi
`resolve_path(artifact_root, record["image_path"])`.

Từ chối absolute path, `..`, backslash, dấu `:`, ký tự điều khiển và đường dẫn
chưa chuẩn hóa như `a//b.png`, `./a.png`. `resolve_path()` kiểm thêm symlink
thoát root tại thời điểm resolve. `validate_bundle()` chỉ kiểm chuỗi path,
không yêu cầu file tồn tại và không truy cập các path ảnh đó.

Không suy thứ tự từ tên file hoặc ID. Mảng pages/lines không cần được lưu theo
thứ tự; consumer phải sort theo `(page_index, reading_order)`. Validator chỉ
kiểm tập giá trị order có liên tiếp, không thay đổi thứ tự input.

## 9. Các lớp validation và lỗi

1. `read_json()`: từ chối duplicate keys, UTF-8/Unicode lỗi, NaN, Infinity,
   float overflow và JSON không hợp lệ.
2. `validate_structure()`: dùng JSON Schema để kiểm required/type/enum/version
   và trường lạ. Mỗi entry schema trỏ tới definitions dùng chung; Python nạp
   definitions cục bộ, không tải schema từ Internet.
3. `validate_bundle()`: thêm bounds, identity, unique/contiguous order, path,
   affine transform, trạng thái và foreign keys của refs.

Validation dừng ở vi phạm đầu tiên. `MetadataValidationError` kế thừa
`ValueError`; thông báo chứa vị trí bản ghi/trường hoặc định danh liên quan.
Đây là lỗi kiểm tra input; không tự chèn lỗi này vào `issues` của dữ liệu.
Các issue trong dữ liệu là vấn đề nghiệp vụ được producer ghi lại.

## 10. Dữ liệu mẫu, nghiệm thu và giới hạn

- `examples/segmented_pages.json`: ba trang, trong đó một trang trắng; ba dòng.
- `examples/recognized_lines.json`: cùng hình học, thêm text tiếng Việt và một
  lỗi OCR giả lập có reference hợp lệ.
- Hash gồm 64 ký tự `0` là placeholder đúng định dạng. Đường dẫn ảnh không có
  file thật. Không dùng examples để báo cáo chất lượng OCR hoặc ảnh crop.
- Chạy `python -m unittest discover -s tests -v` hoặc `python -m pytest tests/ -q`.
- Tests kiểm dữ liệu đúng và các vi phạm contract, không gọi model/LLM.

Chưa có kiểm pixel, hash ảnh thực tế, độ khớp bbox với chữ, chất lượng reading
order theo nội dung, hay tính đúng đắn của OCR. Các phần đó cần ảnh/nhãn chuẩn
và thuộc bước tích hợp sau. Contract chỉ yêu cầu order tường minh; thuật toán
sinh order cho nhiều cột là trách nhiệm segmentation.

## 11. Phiên bản và tích hợp

Không tự chuyển trường `page` cũ thành `page_id`; dữ liệu cũ phải được chuyển
đổi tường minh. Khi thay đổi ý nghĩa bbox, frame, trạng thái hoặc required
fields, cập nhật schema version, docs, fixtures và tests cùng nhau.

Bộ khởi đầu này tham khảo metadata OCR của repo mẫu nhưng bổ sung `stage`
ở wrapper, schema wrapper và quy tắc issue cho trạng thái lỗi. Vì vậy không
coi nó là bản thay thế tương thích trực tiếp với toàn bộ pipeline repo mẫu.
Khi các module mới được viết trong repo chính, dùng contract này ngay từ đầu.
