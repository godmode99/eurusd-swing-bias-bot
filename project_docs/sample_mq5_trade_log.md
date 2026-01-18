“ไฟล์ตัวอย่าง (sample)” เอาไว้ให้ Codex/มึง/คนอ่าน repo เข้าใจสัญญา (contract) ระหว่าง Python ↔ EA และใช้เทสได้ทันที โดย ไม่ใช่ไฟล์จริงที่ MT5 ใช้งานบนเครื่องตอนรันจริง (ของจริงอยู่ใน MT5 Data Folder)

พูดง่าย ๆ:

mql5/Files/bias_eurusd.sample.json = ตัวอย่างว่า Python ต้องเขียน JSON หน้าตาแบบไหน

mql5/Files/trade_log.sample.csv = ตัวอย่างว่า EA ต้อง log CSV หน้าตาแบบไหน

ไว้เพื่อ:

เป็นเอกสาร/สเปกที่จับต้องได้ (ไม่ต้องอ่านอธิบายยาวก็รู้ format)

ใช้ทำ unit test / sanity check (เช่น Python เขียนตาม schema, EA parse ได้)

เอาไปให้ Codex ดูเป็น “input/output ตัวอย่าง” แล้วมันจะโค้ดถูก

ของจริงตอนรัน:

Python จะเขียนไป ...\MetaQuotes\Terminal\<hash>\MQL5\Files\bias_eurusd.json

EA จะเขียนไป ...\MetaQuotes\Terminal\<hash>\MQL5\Files\trade_log.csv

repo เราเก็บแค่ “sample” เพื่อไม่ commit ข้อมูลเทรดจริง/ข้อมูลส่วนตัว

ตัวอย่างไฟล์ 1: mql5/Files/bias_eurusd.sample.json
{
"symbol": "EURUSD",
"asof_utc": "2026-01-18T01:30:00Z",

"direction": "LONG",
"strength": 8,
"label": "STRONG",
"bias_trend": "STABLE",
"early_reversal_warning": false,

"event_risk": "LOW",
"ttl_days": 3,

"trade_permission": "YES",
"risk_per_trade_pct": 1.0,

"notes": "US2Y down; D1 aligned; no high-impact events next 48h"
}

เอาไว้เช็คว่า:

ฟิลด์ครบไหม

ค่า enum ถูกไหม

EA parse ได้ไหม

ตัวอย่างไฟล์ 2: mql5/Files/trade_log.sample.csv

ไฟล์นี้ควรมีอย่างน้อย 2–3 บรรทัด (header + ตัวอย่างแถว) เช่น:

run_id,ticket,symbol,side,entry_time_utc,exit_time_utc,entry_price,sl_price,tp1_price,tp2_price,exit_price,equity_at_entry,risk_per_trade_pct,r_money,r_pips,lots,pnl_money,pnl_r,spread_points_entry,slippage_points_entry,rule_ok_setup,rule_ok_chase,rule_ok_rr,rule_ok_sl,bias_asof_utc,bias_direction,bias_strength,bias_label,bias_trend,early_reversal_warning,event_risk,ttl_days,root_cause_tag,notes
20260118-0001,12345678,EURUSD,BUY,2026-01-18T08:00:00Z,2026-01-18T14:00:00Z,1.09500,1.09350,1.09650,1.09800,1.09650,20000,1.0,200,15,0.10,100,0.5,12,0,1,1,1,1,2026-01-18T01:30:00Z,LONG,8,STRONG,STABLE,0,LOW,3,,TP1 partial close
20260118-0001,12345678,EURUSD,BUY,2026-01-18T08:00:00Z,2026-01-19T04:00:00Z,1.09500,1.09500,1.09650,1.09800,1.09800,20000,1.0,200,15,0.10,300,1.5,12,0,1,1,1,1,2026-01-18T01:30:00Z,LONG,8,STRONG,STABLE,0,LOW,3,,Final close TP2

จุดสังเกต:

แถวแรก = ปิดบางส่วนที่ TP1 (pnl_r ~ 0.5 เพราะปิด 50% ที่ 1R)

แถวสอง = ปิดส่วนที่เหลือที่ TP2 (รวม ๆ แล้วจะได้มากกว่า)

root_cause_tag ปล่อยว่างได้ ให้ Python มาเติมทีหลัง

ทำไมต้องอยู่ใต้ mql5/Files/ ใน repo ทั้งที่ MT5 ก็มี Files ของมัน?

เพราะมัน “สื่อเจตนา” กับ Codex/คนอ่านว่า:

ไฟล์นี้คือ ไฟล์สัญญา I/O ที่ EA ใช้

แต่เป็น ตัวอย่าง ไม่ใช่ข้อมูลจริง

(และเราจะใส่ .gitignore กันไม่ให้ commit ไฟล์จริงใน MT5 Data Folder)
