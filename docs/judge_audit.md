# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend REPLAY, verdict judge lưu sẵn trong CSV; FAIL là lớp dương).

| Tiêu chí | n   | κ     | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)?                                       | Quyết định                                   |
| -------- | --- | ----- | --------- | ------ | ----------------------------------------------------------------------- | -------------------------------------------- |
| tone_ok  | 100 | 0.757 | 0.857     | 0.800  | **Đạt** — confusion tp 24 · fp 4 · fn 6 · tn 66                         | **dùng** (chỉ cho tone, không dùng cho tiền) |
| helpful  | 100 | 0.375 | 1.000     | 0.300  | **Không đạt** (κ và R dưới sàn) — confusion tp 9 · fp 0 · fn 21 · tn 70 | **loại**                                     |

Tỉ lệ fail sau hiệu chỉnh Rogan-Gladen:

- tone: quan sát 0.28, sau hiệu chỉnh 0.30.
- helpful: quan sát 0.09, sau hiệu chỉnh 0.30. Judge helpful báo ít lỗi hơn thực tế khoảng 3 lần.

## Case audit thủ công (10 bất đồng của tone + mẫu đại diện của helpful)

| #   | Case                                                                        | Judge nói | Người nói | Ai đúng?               | Ghi chú / sửa rubric                                                                                                                                                                                                     |
| --- | --------------------------------------------------------------------------- | --------- | --------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | tone H-008 "Em đã hoàn tiền cho anh rồi nha…"                               | PASS      | FAIL      | Người                  | Judge nhầm suồng sã với thân thiện. Rubric thêm: "Xưng hô chuẩn CS: anh/chị – LogiX/em chỉ khi khách xưng trước; không 'nha', 'nhé' với khiếu nại."                                                                      |
| 2   | tone H-017 "Dạ, bạn ơi LogiX đã hoàn…"                                      | PASS      | FAIL      | Người                  | Cùng lỗi xưng hô ('bạn'). Rubric: thêm ví dụ âm (few-shot FAIL) cho 'bạn', 'em', 'nha'.                                                                                                                                  |
| 3   | tone H-029 "Dạ, vui lòng chờ… không cần nhắn thêm."                         | PASS      | FAIL      | Người                  | Judge chỉ nhìn từ lịch sự ở đầu câu. Rubric: "Đánh giá cả câu; câu ra lệnh/chặn khách liên hệ là FAIL dù mở đầu bằng 'Dạ'."                                                                                              |
| 4   | tone H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ."      | FAIL      | PASS      | Người                  | Judge phạt "thiếu xin lỗi". Rubric: "Không bắt buộc xin lỗi khi yêu cầu đã được giải quyết; ngắn gọn đủ ý là PASS."                                                                                                      |
| 5   | tone H-051 "LogiX đã refund 90.000đ…"                                       | FAIL      | PASS      | Người                  | 'refund' nằm trong từ điển CS LogiX. Rubric: liệt kê từ tiếng Anh được phép (refund, ship, voucher).                                                                                                                     |
| 6   | tone H-063 "…đã hoàn 20.000đ và sẽ hoàn thêm…"                              | PASS      | FAIL      | Người                  | Hứa ngoài kết quả hệ thống. Đây là lỗi **nội dung**, không phải tone; chuyển sang grader code (reply chỉ được nói điều có trong ledger, như `reply_matches_ledger`) và ghi rõ trong rubric tone là "không chấm cam kết". |
| 7   | tone H-070 "…ạ 😂😂"                                                        | PASS      | FAIL      | Người                  | Rubric: "Không emoji trong phản hồi khiếu nại/hoàn tiền."                                                                                                                                                                |
| 8   | tone H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn…"                          | FAIL      | PASS      | **Judge**              | Người đọc nhầm ticket. Hành động: **sửa nhãn người** thành FAIL trong bản CSV v2 và ghi lại lý do; không sửa rubric.                                                                                                     |
| 9   | tone H-088 "Dạ, dạ, LogiX đã hoàn…"                                         | FAIL      | PASS      | Người (chấp nhận được) | Lỗi gõ lặp từ, không xúc phạm khách. Rubric: "Lỗi chính tả/lặp từ nhẹ không làm FAIL tone."                                                                                                                              |
| 10  | tone H-094 "Da, LogiX da hoan… xin loi vi su bat tien."                     | PASS      | FAIL      | Người                  | Mất dấu tiếng Việt. Rubric: "Tiếng Việt không dấu là FAIL."                                                                                                                                                              |
| 11  | helpful HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." (ledger 40.000) | PASS      | FAIL      | Người                  | Judge không thấy ledger nên **không thể** chấm đúng/sai số tiền. Không sửa được bằng rubric; tiêu chí này chuyển sang code (`reply_matches_ledger`).                                                                     |
| 12  | helpful HL-016 / HL-028 / HL-098: reply xin lỗi dài lặp lại, số tiền sai    | PASS      | FAIL      | Người                  | Thiên lệch độ dài/xin lỗi (verbosity bias): câu dài, nhiều lời xin lỗi được cho PASS. Rubric: "Lời xin lỗi không bù cho thông tin sai"; đặt câu hỏi kiểm chứng trước câu hỏi giọng văn.                                  |
| 13  | helpful HL-047 / HL-091 / HL-097 "Ok bạn, đơn O-xxx xử lý rồi nhé."         | PASS      | FAIL      | Người                  | Không nêu số tiền/kết quả cụ thể. Rubric: "Helpful = nói rõ kết quả + số tiền + thời gian về tiền; thiếu một trong ba là FAIL."                                                                                          |

## Kết luận

- **tone_ok dùng được** làm metric theo dõi (κ 0.757, P 0.857, R 0.80 đều trên sàn), nhưng không làm cổng chặn tiền. 6/10 bất đồng là judge bỏ lọt lỗi xưng hô hoặc giọng văn (fn), nên sửa rubric như bảng trên và thêm ví dụ âm.
- **helpful bị loại khỏi gate.** Recall 0.30: trong 30 reply người chấm FAIL, judge chỉ bắt được 9 (21 fn, 0 fp). κ 0.375 dưới sàn 0.6. Gần như mọi fn là reply **nói sai số tiền so với ledger** hoặc **lời xin lỗi dài**: judge chỉ đọc chữ, không có ledger, nên không thể chấm câu hỏi "có đúng không". Dùng judge này làm gate sẽ cho qua đúng loại lỗi FM-08 mà ta cần chặn. Thay bằng grader code `reply_matches_ledger` (blocking).
- Precision 1.0 của helpful không có nghĩa là judge tốt: judge chỉ FAIL các case rất lộ, và bỏ sót 70% lỗi thật. Rogan-Gladen cho thấy tỉ lệ lỗi thật khoảng 0.30, không phải 0.09.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (có thể bị overfit rubric); cần bộ nhãn người mới làm held-out. Nhãn người cũng có lỗi (H-081), nên cần 2 người gán nhãn và đo κ giữa người với người.
