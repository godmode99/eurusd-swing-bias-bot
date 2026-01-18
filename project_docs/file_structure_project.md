นี่คือ file structure แบบ best practice สำหรับ repo ที่มีทั้ง Python Bias Engine + MQL5 EA + Docs/Backtest/CI (โฟกัสทำงานจริง + maintain ง่าย + ให้ Codex เดินตามได้)

eurusd-swing-bias-bot/
├─ README.md
├─ LICENSE
├─ .gitignore
├─ .gitattributes
├─ .editorconfig
├─ pyproject.toml
├─ uv.lock # (ถ้าใช้ uv) หรือ poetry.lock/pip-tools
├─ .env.example
├─ Makefile # หรือ justfile (ตัวช่วยรันคำสั่ง)
├─ scripts/
│ ├─ run_bias_once.ps1 # Windows: รัน Python แล้ว copy ไป MT5 Files
│ ├─ run_bias_once.sh # \*nix
│ ├─ locate_mt5_data_dir.md # วิธีหา MT5 Data Folder
│ └─ sanity_check.py # เช็ค path/permission/ไฟล์ output
│
├─ docs/
│ ├─ PROJECT_SPEC_FOR_CODEX.md
│ ├─ ARCHITECTURE.md
│ ├─ RULES.md # direction/strength/setup/anti-chase/SL-TP
│ ├─ DATA_SOURCES.md # FRED, MT5 price, event flag
│ ├─ OPERATIONS.md # วิธีรันรายวัน + fail-safe + troubleshooting
│ └─ CHANGELOG.md
│
├─ config/
│ ├─ config.example.yaml
│ ├─ config.local.yaml # ไม่ commit (ใส่ใน .gitignore)
│ └─ thresholds.yaml # น้ำหนักคะแนน/threshold แยกไฟล์เพื่อ tune ง่าย
│
├─ python/
│ ├─ README.md
│ ├─ src/
│ │ └─ biasbot/
│ │ ├─ **init**.py
│ │ ├─ main.py # entrypoint: run once, write JSON
│ │ ├─ settings.py # โหลด config/env + validate
│ │ ├─ io/
│ │ │ ├─ bias_writer.py # write JSON atomically
│ │ │ ├─ history_store.py # bias_history.csv
│ │ │ └─ trade_log_reader.py # read trade_log.csv
│ │ ├─ data/
│ │ │ ├─ fred.py # US2Y (DGS2)
│ │ │ ├─ mt5_prices.py # EURUSD OHLC via MetaTrader5 pkg
│ │ │ └─ schemas.py # dataclasses/pydantic for types
│ │ ├─ features/
│ │ │ ├─ yields.py # delta/zscore
│ │ │ ├─ trend.py # D1 alignment
│ │ │ └─ utils.py
│ │ ├─ engine/
│ │ │ ├─ scorer.py # strength 0-10
│ │ │ ├─ state.py # bias_trend + warning
│ │ │ └─ decision.py # permission + risk budget mapping
│ │ ├─ analysis/
│ │ │ ├─ tagging.py # root-cause tagging
│ │ │ ├─ fuse.py # daily -2R / weekly -4R
│ │ │ └─ report.py # weekly summary (optional)
│ │ └─ utils/
│ │ ├─ time.py # utc helpers
│ │ ├─ log.py # logging setup
│ │ └─ math.py
│ │
│ ├─ tests/
│ │ ├─ test_scorer.py
│ │ ├─ test_state.py
│ │ ├─ test_decision.py
│ │ └─ test_io_atomic_write.py
│ └─ notebooks/
│ └─ explore_bias_scoring.ipynb # ใช้ tune ได้ (optional)
│
├─ mql5/
│ ├─ README.md
│ ├─ Experts/
│ │ └─ EURUSD_SwingEA.mq5
│ ├─ Include/
│ │ ├─ BiasJson.mqh # อ่าน/parse JSON แบบง่าย
│ │ ├─ NewBar.mqh # detect H4 close
│ │ ├─ FractalSwing.mqh # fractal 2-2 + fallback
│ │ ├─ ATR.mqh
│ │ ├─ SetupDetector.mqh # Setup A/B
│ │ ├─ RiskSizing.mqh
│ │ ├─ TradeManager.mqh # TP1 partial + BE + TP2
│ │ └─ CsvLogger.mqh
│ ├─ Files/ # (ตัวอย่างไฟล์) ไม่ใช่ของ MT5 จริง
│ │ ├─ bias_eurusd.sample.json
│ │ └─ trade_log.sample.csv
│ └─ Profiles/
│ └─ set_files_path.md # วิธีทดสอบใน MT5
│
├─ data/
│ ├─ samples/
│ │ ├─ bias_history.sample.csv
│ │ ├─ trade_log.sample.csv
│ │ └─ eurusd_d1.sample.csv
│ └─ .gitkeep
│
├─ .github/
│ └─ workflows/
│ ├─ python-ci.yml # lint/test
│ └─ release.yml # tag/release (optional)
│
└─ tools/
├─ pre-commit-config.yaml # (optional) format/lint
└─ devcontainer.json # (optional) ถ้าจะใช้ devcontainer

แนวคิดสำคัญที่โครงนี้แก้ปัญหาให้มึง

แยก Python / MQL5 ชัด ไม่ให้โค้ดปนกันจนเละ

Python อยู่แบบ package (src/biasbot) → test ง่าย, import สะอาด

MQL5 แยก logic เป็น .mqh เล็ก ๆ → แก้ทีละส่วน ไม่พังทั้งไฟล์

config/thresholds.yaml ทำให้ “ปรับกฎ/ค่าน้ำหนัก” โดยไม่แก้โค้ดบ่อย

docs/PROJECT_SPEC_FOR_CODEX.md คือไฟล์หลักที่ Codex อ่านแล้วแตกงานได้ตรง

ไฟล์ที่ “ควรมี” เพิ่ม (เพื่อให้ repo ดูเป็นมืออาชีพ)
.env.example

ใส่ตัวอย่างเช่น:

FRED_API_KEY=...

MT5_FILES_DIR=C:\...\MQL5\Files

config.example.yaml

เก็บค่าตั้งต้น เช่น:

path ของ MT5 Files

threshold strength

fuse (-2R/-4R)

windows timezone (ถ้าจำเป็น)

README.md (หัวข้อที่ควรมี)

What it does

How to run Python once

How to install EA + where to place bias file

Safety rules (one position, H4 close only)

Troubleshooting (ไฟล์ไม่เจอ / timestamp เก่า)

.gitignore (ของจำเป็น)

ใส่พวกนี้:

config/config.local.yaml

.env

data/\* (ยกเว้น samples)

python/.venv/

\*.log

**pycache**/

\*.ex5 (ไฟล์คอมไพล์ MT5)

MQL5/Files/_.json MQL5/Files/_.csv (ของจริงบนเครื่องไม่ควร commit)
