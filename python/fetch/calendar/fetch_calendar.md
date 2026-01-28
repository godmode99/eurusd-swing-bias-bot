01_save_session.py

หน้าที่: สร้าง/บันทึก session ของ Playwright เป็น ff_storage.json (cookies + origins) เพื่อให้เข้าเว็บได้เหมือน user (ผ่าน Cloudflare/Turnstile)

Input: ไม่มี (แค่เปิด browser)
Output: ff_storage.json (หรือ path ที่มึงตั้ง)

Best practice

รันแบบ headful ให้มึงแก้ challenge/กดผ่านได้ แล้วค่อย context.storage_state(path=...)

อย่า commit ff_storage.json ลง git (.gitignore)

ถ้าเริ่ม 403/Just a moment… ให้สร้างใหม่ (session หมดอายุ/โดน flag)

02_capture_document_html.py

หน้าที่: เปิดหน้า https://www.forexfactory.com/calendar โดยใช้ ff_storage.json แล้ว “แคป document HTML” ออกมาเป็น snapshot

Input: ff_storage.json
Output:

artifacts/ff/calendar_document.html (HTML ดิบ)

artifacts/ff/document_debug.png (รูปไว้เช็คว่าโดน challenge ไหม)

artifacts/ff/calendar_document.meta.json (เวลา/สถานะ/URL/Title ฯลฯ)

Best practice

ใช้ wait_until="domcontentloaded" ไม่ต้อง networkidle (หน้า FF มี request background เยอะ จะไม่ idle)

เซฟ screenshot ทุกครั้ง (ดีบั๊กง่ายมาก)

เก็บ meta เพื่อเทียบรันต่อรันว่ามันเปลี่ยนอะไรบ้าง

03_extract_from_document.py

หน้าที่: อ่าน calendar_document.html แล้วดึง data ที่ฝังใน <script> (เช่น window.calendarComponentStates[1] = {...}) แปลงจาก JS object literal → JSON แล้ว normalize เป็นรายการ event

Input: artifacts/ff/calendar_document.html
Output:

artifacts/ff/events.json (event list ที่ใช้ต่อได้)

artifacts/ff/events.csv (optional)

artifacts/ff/events.meta.json

Best practice

ทำ dedupe ด้วย (event_id, dateline_epoch) กัน event ซ้ำ

เก็บทั้ง dateline_epoch (ไว้ sort/คำนวณ) และ datetime_bkk (ไว้คนอ่าน)

ขั้นนี้ทำแค่ “extract + clean” อย่าเพิ่งทำ logic เทรด

20_make_risk_windows.py

หน้าที่: เอา events.json มาสร้าง “ช่วงเวลาเสี่ยง” รอบข่าว (no-trade windows) ให้ strategy/EA ใช้หลบ

Input: artifacts/ff/events.json
Output:

artifacts/ff/no_trade_windows.json

artifacts/ff/no_trade_windows.meta.json

Logic ที่ทำ

filter currencies ตาม pair (EURUSD → EUR, USD)

map impact → เวลา pre/post เช่น

high: -60m ถึง +30m

medium: -30m ถึง +15m

low: ignore (หรือทำก็ได้)

Best practice

ทำ output เป็น window ที่ “เครื่องอ่านง่าย”: start/end epoch + iso

ถ้ามีหลาย event ชนกัน ให้ merge overlap (กัน no-trade windows แตกเป็นชิ้นเล็ก ๆ)

30_refresh_actuals.py

หน้าที่: ข่าวมันมี 2 ช่วง — ก่อนประกาศ (actual ว่าง) และหลังประกาศ (actual มา)
ไฟล์นี้จะ “รัน 02+03 ใหม่” เพื่อได้ events ล่าสุด แล้ว merge เติม actual/revision/forecast ที่เปลี่ยนเข้า events เดิม พร้อมเก็บ history ก่อน-หลัง

Input:

artifacts/ff/events.json (ก่อนรีเฟรช)

ff_storage.json (อ้อม ๆ ผ่าน step02)

Output:

artifacts/ff/events_merged.json (หลัง merge)

artifacts/ff/history/<timestamp>/events_before.json

artifacts/ff/history/<timestamp>/events_after.json

artifacts/ff/events_refresh.meta.json

Best practice

อย่าทับของเดิมแบบไม่เก็บหลักฐาน: เก็บ before/after ทุกครั้ง

merge แบบปลอดภัย: update เฉพาะฟิลด์ที่สนใจ (actual/forecast/previous/revision/...)

มี option --overwrite-events เพื่อให้ events.json กลายเป็นฉบับล่าสุดเลย

40_compute_surprise.py

หน้าที่: คำนวณ “เซอร์ไพรส์” ของตัวเลขข่าว: surprise = actual - forecast และ %surprise
พร้อม parse ค่า "3.2%", "250K", "1.2M" ให้กลายเป็นตัวเลขก่อนคำนวณ

Input: events.json หรือ events_merged.json
Output:

artifacts/ff/event_surprises.json

artifacts/ff/event_surprises.meta.json

Best practice

เก็บทั้ง raw string (actual_raw) และ parsed (actual) เพื่อ audit

filter ขั้นต่ำ impact (เช่น --min-impact medium) กัน noise

เอา output นี้ไป feed ให้ bias bot ได้เลย (มันมี “ตัวเลขที่แปลแล้ว”)

calendar_pipeline.py

หน้าที่: ตัวรันรวม (orchestrator) ให้มึงกดทีเดียวแล้วมันทำเป็นลำดับ:

02 capture HTML

03 extract events

20 make risk windows
(แล้วแต่เวอร์ชัน อาจ archive outputs ด้วย)

Input: config/args + ไฟล์ session
Output: artifacts ทั้งชุด + meta ของการรัน

Best practice

รองรับ args เช่น --pair EURUSD --archive

เก็บ run log/meta เพื่อ debug

ถ้าไฟล์ขึ้นต้นด้วยเลข import ยาก ให้ pipeline ใช้ subprocess เรียกไฟล์แทน (ชัวร์สุด)
