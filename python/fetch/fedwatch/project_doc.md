เอกสารโครงการ: FedWatch Data Pipeline (Browser Automation – Method 5)

1. เป้าหมายโครงการ

สร้างระบบดึงข้อมูล FedWatch เพื่อใช้ทำ macro bias และ risk management สำหรับการเทรด (เช่น EURUSD) โดย:

ทำงานแบบอัตโนมัติได้มากที่สุด

ถ้าเจอหน้า challenge/บล็อก ให้ “หยุด + เก็บหลักฐาน + แจ้งเตือน” เพื่อให้คนรีเฟรช session

บันทึกข้อมูลเป็น snapshot เพื่อ audit/ย้อนดูได้

หลักการ: “ทำเหมือน user ปกติ” ไม่พยายามฝ่า/แก้ challenge อัตโนมัติ

2. ขอบเขต (Scope)
   In-scope

Browser automation เปิดหน้า FedWatch ด้วย session ที่สร้างไว้

ตรวจสถานะหน้า: OK / CHALLENGE / BLOCKED

Capture HTML + screenshot + meta ทุกครั้ง

Extract ข้อมูลจาก DOM หรือจาก data ที่ฝังในหน้า (ถ้ามี)

Normalize เป็น schema มาตรฐาน

Compute delta: เทียบกับ snapshot ก่อนหน้า

สรุป digest สำหรับ bias bot (ข้อความ/JSON สั้น)

Out-of-scope

การ bypass/แก้ anti-bot, solving Turnstile/Cloudflare อัตโนมัติ

Reverse engineer private endpoints

High-frequency scraping

3. ข้อมูลที่ต้องการ (Data Requirements)
   ข้อมูลขั้นต่ำ (Minimum viable)

asof_date/time

ตาราง “meeting date → probability distribution ของ target rate / rate range”

derived metrics:

expected_rate (ค่าเฉลี่ยถ่วงน้ำหนัก)

prob_cut, prob_hold, prob_hike (รวมกลุ่มตามนิยาม)

top_scenario (สถานการณ์ที่ probability สูงสุด)

ข้อมูลเสริม (Optional)

ความเปลี่ยนแปลง day-over-day / week-over-week

สรุป “shift” ของ distribution (เช่น mass ย้ายจาก hold ไป hike)

4. สถาปัตยกรรมระบบ (Architecture)
   4.1 ภาพรวม Flow

Session Setup (Manual)

เปิดเว็บแบบ headful → user ผ่านตามปกติ → save storage_state

Scheduled Run

เปิดเว็บด้วย storage_state

ตรวจสถานะหน้า (OK/CHALLENGE)

ถ้า OK → capture html/screenshot → extract → normalize → delta → digest

ถ้า CHALLENGE/BLOCKED → capture หลักฐาน → mark run failed → แจ้งเตือน

4.2 โครงโฟลเดอร์ที่แนะนำ
fedwatch/
app/
fedwatch_pipeline.py
fetch/
01_save_session.py
02_capture_document_html.py
03_extract_from_document.py
transform/
20_normalize.py
30_compute_delta.py
40_make_digest.py
artifacts/
fedwatch/
latest/
page.html
screenshot.png
meta.json
raw.json
normalized.json
delta.json
digest.json
runs/
2026-01-28T13-20-00/
...
history/
...
secrets/
fedwatch_storage.json (gitignored)

5. รายละเอียดโมดูล/ไฟล์ (Responsibilities)
   A) fetch/01_save_session.py

วัตถุประสงค์: สร้าง secrets/fedwatch_storage.json
วิธีทำงาน:

เปิด browser headful

ไปหน้าเป้าหมาย

user ทำขั้นตอนตามปกติ (ถ้ามี)

บันทึก context.storage_state(path=...)

Output:

secrets/fedwatch_storage.json

Exit Codes:

0 success

1 fail (ไฟล์ไม่ถูกสร้าง)

B) fetch/02_capture_document_html.py

วัตถุประสงค์: แคป HTML “document” + screenshot + meta
Logic หลัก:

ใช้ storage_state

goto(wait_until="domcontentloaded")

ตรวจ page.title() + keyword ใน body

ถ้าเจอคำ/รูปแบบที่บ่งบอก challenge → status=CHALLENGE

Outputs (per run):

artifacts/fedwatch/runs/<ts>/page.html

.../screenshot.png

.../meta.json (url, title, status, timestamps)

Exit Codes:

0 OK (page content ready)

2 CHALLENGE/BLOCKED (ต้องรีเฟรช session)

1 error

B2) fetch/02b_capture_iframe_html.py

วัตถุประสงค์: เรียกดู/ดึง HTML จากหน้า iframe (QuikStrike FedWatch Tool)
Logic หลัก:

เปิดหน้า FedWatch หลัก → หา iframe src (หรือกำหนด --iframe-url ตรง ๆ)

เปิดหน้า iframe และบันทึก HTML + screenshot + meta

Outputs (per run):

artifacts/fedwatch/runs/<ts>/iframe.html

.../iframe_screenshot.png

.../iframe_meta.json

Exit Codes:

0 OK (iframe content ready)

2 CHALLENGE/BLOCKED (ต้องรีเฟรช session)

1 error

C) fetch/03_extract_from_document.py

วัตถุประสงค์: แตก data จาก HTML
กลยุทธ์:

DOM parsing (เช่น BeautifulSoup/lxml) หรือ regex ที่ “อ่านเฉพาะส่วนที่จำเป็น”

หา “ตาราง distribution” แล้วแปลงเป็น raw structure

เก็บ raw แบบไม่ทิ้งข้อมูล

Output:

raw.json (ยังไม่ normalize)

D) transform/20_normalize.py

วัตถุประสงค์: แปลง raw → schema กลางมาตรฐาน

Normalized Schema (ตัวอย่าง)

{
"asof_utc": "2026-01-28T06:00:00Z",
"source": "fedwatch",
"meetings": [
{
"meeting_date": "2026-03-18",
"distribution": [
{"rate_range": "4.75-5.00", "prob": 0.12},
{"rate_range": "5.00-5.25", "prob": 0.61}
],
"expected_rate_mid": 5.12,
"top_scenario": {"rate_range": "5.00-5.25", "prob": 0.61}
}
]
}

E) transform/30_compute_delta.py

วัตถุประสงค์: เทียบ normalized ล่าสุดกับของก่อนหน้า
Output:

delta.json (changes by meeting)

delta example

{
"meeting_date": "2026-03-18",
"top_scenario_change": {"from": "4.75-5.00", "to": "5.00-5.25"},
"expected_rate_mid_change": 0.08,
"prob_shift": [
{"rate_range": "4.75-5.00", "delta": -0.10},
{"rate_range": "5.00-5.25", "delta": +0.10}
]
}

F) transform/40_make_digest.py

วัตถุประสงค์: ทำสรุปสั้น ๆ ให้ bias bot ใช้ (หรือส่ง Telegram)
Output:

digest.json หรือ digest.txt

Digest example

“Next meeting 2026-03-18: Top scenario 5.00-5.25 @ 61% (+10pp DoD). Expected rate +0.08.”

G) app/fedwatch_pipeline.py

วัตถุประสงค์: orchestration ทั้งหมด

รัน 02 → 03 → normalize → delta → digest

จัด latest/ symlink/สำเนา

เขียน run meta + exit code ที่ชัดเจน

6. กติกาคุณภาพ (Quality & Reliability)
   6.1 Data Quality

เก็บทั้ง “raw” และ “normalized”

Validate:

sum(probabilities) ใกล้ 1.0 (±0.02)

meeting_date parse ได้

ถ้า validation fail → mark run FAIL + เก็บหลักฐาน

6.2 Observability

เก็บ meta.json ทุก run:

status: OK/CHALLENGE/ERROR

title, url

timestamps

เก็บ screenshot ทุก run (สำคัญสุดสำหรับ anti-bot)

6.3 Rate limiting

ไม่รันถี่เกินจำเป็น (วันละ 1 ครั้งแบบ EOD หรือ 2-3 ครั้ง/วันพอ)

ถี่เกิน = โอกาสโดน challenge สูงขึ้น

7. ความปลอดภัย (Security)

secrets/fedwatch_storage.json และ key ใด ๆ ต้องอยู่ใน .gitignore

หลีกเลี่ยงการ log cookie/token ออก console

เก็บ artifacts เฉพาะที่จำเป็น

8. แผนการทดสอบ (Test Plan)
   Test 1: Session works

รัน 02 แล้ว title/selector ของ content เจอ → OK

Test 2: Challenge detection

ลบ/ใช้ session หมดอายุ → 02 ต้องออก status=CHALLENGE + มี screenshot

Test 3: Extract correctness

03 แปลงตารางได้ครบ N rows

probabilities parse เป็น float

Test 4: Normalize validation

sum(prob) ใกล้ 1

expected_rate_mid คำนวณได้

Test 5: Delta stability

เทียบวันต่อวันแล้ว delta ไม่เพี้ยน (meeting เดิม)

9. Roadmap
   Phase 0 (1 วัน)

ทำ 01/02 ให้เสถียร + status detect + artifacts

Phase 1 (1–2 วัน)

ทำ 03 extract + 20 normalize + schema มาตรฐาน

Phase 2 (1 วัน)

ทำ delta + digest + pipeline runner

Phase 3

รวมเข้ากับ bias bot หลัก (FF + FedWatch + macro data อื่น)

10. เกณฑ์สำเร็จ (Success Criteria)

รันอัตโนมัติได้ ≥ 80% ของวันโดยไม่ต้องแตะ

ถ้า fail ต้องมี “หลักฐาน” (screenshot/html/meta) ครบ

Output normalized.json + delta.json + digest ใช้ feed GPT ได้จริง
