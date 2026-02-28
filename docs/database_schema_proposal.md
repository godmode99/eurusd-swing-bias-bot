# Database Schema Proposal (ไฟล์ -> Database)

เอกสารนี้ออกแบบจากพฤติกรรมปัจจุบันที่ pipeline เขียนข้อมูลลงไฟล์ JSON/CSV หลายจุด เช่น
- `calendar` เขียน `latest_select_events.json`, `events*.json`, `risk_windows.json`.
- `fred` เขียน snapshot รายโหมด + manifest.
- `mt5` เขียน OHLC/features + manifest.

> Recommendation: ใช้ **PostgreSQL + TimescaleDB (optional)** เพื่อรองรับ time-series query และ retention policy ได้ง่าย

---

## 1) Design Principles

1. แยก `raw` และ `curated` ชัดเจน
2. ทุก record มี `ingestion_run_id` เพื่อ trace กลับไปยังรอบ fetch
3. ใช้ natural key + unique index เพื่อ upsert ได้
4. เก็บเวลาเป็น `timestamptz` เสมอ
5. สร้าง view/materialized view สำหรับงาน dashboard/telegram

---

## 2) Core Tables

### 2.1 ingestion_runs
ใช้แทนไฟล์ manifest/error report

```sql
create table ingestion_runs (
  id bigserial primary key,
  pipeline_name text not null,            -- calendar | fred | mt5 | cme_fedwatch
  mode text null,                         -- daily/weekly/monthly หรือ null
  run_tag text null,
  started_at timestamptz not null default now(),
  finished_at timestamptz null,
  status text not null check (status in ('running','ok','warn','error')),
  notes text null,
  metadata jsonb not null default '{}'::jsonb
);

create index idx_ingestion_runs_pipeline_started
  on ingestion_runs (pipeline_name, started_at desc);
```

### 2.2 source_status
ใช้แทนส่วน `sources`, `stale_sources` ใน manifest

```sql
create table source_status (
  id bigserial primary key,
  ingestion_run_id bigint not null references ingestion_runs(id) on delete cascade,
  source_code text not null,              -- เช่น FRED_CPIAUCSL, EURUSD_D1
  ok boolean not null,
  rows_count integer not null default 0,
  latest_at timestamptz null,
  used_cache boolean not null default false,
  error_message text null,
  extra jsonb not null default '{}'::jsonb,
  unique (ingestion_run_id, source_code)
);

create index idx_source_status_source_latest
  on source_status (source_code, latest_at desc);
```

---

## 3) Calendar Domain

### 3.1 calendar_events_raw
แทนไฟล์ event snapshots ก่อนคัดเลือก/merge

```sql
create table calendar_events_raw (
  id bigserial primary key,
  ingestion_run_id bigint not null references ingestion_runs(id) on delete cascade,
  provider text not null default 'forexfactory',
  event_key text not null,                -- deterministic hash: provider+currency+name+datetime_utc
  event_time_utc timestamptz not null,
  event_time_bkk timestamptz generated always as (event_time_utc at time zone 'Asia/Bangkok') stored,
  currency char(3) not null,
  impact text null,
  event_name text not null,
  actual_value text null,
  forecast_value text null,
  previous_value text null,
  unit text null,
  raw_payload jsonb not null,
  created_at timestamptz not null default now(),
  unique (provider, event_key)
);

create index idx_calendar_events_raw_time on calendar_events_raw (event_time_utc desc);
create index idx_calendar_events_raw_currency_time on calendar_events_raw (currency, event_time_utc desc);
```

### 3.2 calendar_events_selected
แทน `latest_select_events.json`

```sql
create table calendar_events_selected (
  id bigserial primary key,
  ingestion_run_id bigint not null references ingestion_runs(id) on delete cascade,
  calendar_event_id bigint not null references calendar_events_raw(id) on delete cascade,
  selection_reason text null,
  unique (ingestion_run_id, calendar_event_id)
);
```

### 3.3 calendar_risk_windows
แทน `risk_windows.json`

```sql
create table calendar_risk_windows (
  id bigserial primary key,
  ingestion_run_id bigint not null references ingestion_runs(id) on delete cascade,
  calendar_event_id bigint not null references calendar_events_raw(id) on delete cascade,
  window_start_utc timestamptz not null,
  window_end_utc timestamptz not null,
  severity text not null,
  strategy_hint text null,
  unique (calendar_event_id, window_start_utc, window_end_utc)
);

create index idx_calendar_risk_windows_range
  on calendar_risk_windows (window_start_utc, window_end_utc);
```

### 3.4 calendar_surprise_scores
แทนผลจาก step compute surprise

```sql
create table calendar_surprise_scores (
  id bigserial primary key,
  ingestion_run_id bigint not null references ingestion_runs(id) on delete cascade,
  calendar_event_id bigint not null references calendar_events_raw(id) on delete cascade,
  surprise_value numeric(20,8) null,
  surprise_zscore numeric(20,8) null,
  direction text null,
  unique (calendar_event_id, ingestion_run_id)
);
```

---

## 4) FRED Domain

### 4.1 fred_series

```sql
create table fred_series (
  id bigserial primary key,
  series_id text not null unique,
  title text null,
  frequency text null,
  units text null,
  metadata jsonb not null default '{}'::jsonb
);
```

### 4.2 fred_observations
แทนไฟล์ snapshot ที่มี `series -> records[]`

```sql
create table fred_observations (
  id bigserial primary key,
  series_id text not null references fred_series(series_id),
  observation_date date not null,
  value numeric(20,8) null,
  ingestion_run_id bigint not null references ingestion_runs(id) on delete cascade,
  created_at timestamptz not null default now(),
  unique (series_id, observation_date)
);

create index idx_fred_observations_date on fred_observations (observation_date desc);
```

---

## 5) CME FedWatch Domain

### 5.1 fedwatch_contracts

```sql
create table fedwatch_contracts (
  id bigserial primary key,
  symbol text not null unique,
  contract_month date not null,
  metadata jsonb not null default '{}'::jsonb
);
```

### 5.2 fedwatch_probabilities

```sql
create table fedwatch_probabilities (
  id bigserial primary key,
  ingestion_run_id bigint not null references ingestion_runs(id) on delete cascade,
  meeting_date date not null,
  target_rate_low numeric(6,3) not null,
  target_rate_high numeric(6,3) not null,
  probability numeric(6,5) not null check (probability >= 0 and probability <= 1),
  source_contract text null references fedwatch_contracts(symbol),
  unique (meeting_date, target_rate_low, target_rate_high, ingestion_run_id)
);

create index idx_fedwatch_prob_meeting on fedwatch_probabilities (meeting_date);
```

---

## 6) MT5 Market Data Domain

### 6.1 market_symbols

```sql
create table market_symbols (
  id bigserial primary key,
  symbol text not null unique,            -- EURUSD
  asset_class text not null default 'fx',
  quote_ccy text null,
  base_ccy text null,
  metadata jsonb not null default '{}'::jsonb
);
```

### 6.2 mt5_bars
แทน output OHLC ต่อ timeframe

```sql
create table mt5_bars (
  id bigserial primary key,
  symbol text not null references market_symbols(symbol),
  timeframe text not null,                -- M5/H1/H4/D1/W1/MN1
  bar_time_utc timestamptz not null,
  open numeric(20,8) not null,
  high numeric(20,8) not null,
  low numeric(20,8) not null,
  close numeric(20,8) not null,
  tick_volume bigint null,
  ingestion_run_id bigint not null references ingestion_runs(id) on delete cascade,
  unique (symbol, timeframe, bar_time_utc)
);

create index idx_mt5_bars_symbol_tf_time
  on mt5_bars (symbol, timeframe, bar_time_utc desc);
```

### 6.3 mt5_features
แทนไฟล์ feature output

```sql
create table mt5_features (
  id bigserial primary key,
  symbol text not null references market_symbols(symbol),
  timeframe text not null,
  bar_time_utc timestamptz not null,
  atr14 numeric(20,8) null,
  ema20 numeric(20,8) null,
  ema50 numeric(20,8) null,
  structure_event text null,
  sweep_prev_high smallint null,
  sweep_prev_low smallint null,
  payload jsonb not null default '{}'::jsonb,
  ingestion_run_id bigint not null references ingestion_runs(id) on delete cascade,
  unique (symbol, timeframe, bar_time_utc)
);

create index idx_mt5_features_symbol_tf_time
  on mt5_features (symbol, timeframe, bar_time_utc desc);
```

---

## 7) Suggested Views (สำหรับใช้งานแทนไฟล์ latest)

```sql
create view v_latest_calendar_selected as
select r.*
from calendar_events_raw r
join calendar_events_selected s on s.calendar_event_id = r.id
join (
  select max(ingestion_run_id) as latest_run
  from calendar_events_selected
) x on s.ingestion_run_id = x.latest_run;

create view v_latest_mt5_feature as
select distinct on (symbol, timeframe)
  symbol, timeframe, bar_time_utc, atr14, ema20, ema50, structure_event
from mt5_features
order by symbol, timeframe, bar_time_utc desc;
```

---

## 8) Migration Plan (Incremental, low-risk)

1. Phase 1: เพิ่ม DB writer แบบ dual-write (ยังเขียนไฟล์เดิมด้วย)
2. Phase 2: เพิ่ม read path จาก DB สำหรับ telegram/report
3. Phase 3: เปลี่ยน scheduler ให้ใช้ DB เป็น source of truth
4. Phase 4: ลดไฟล์ output เหลือเฉพาะ backup/export

---

## 9) Minimal API Contract for Pipelines

ทุก pipeline ควรเรียก flow เดียวกัน:
1. `start_run(pipeline_name, mode)` -> `ingestion_run_id`
2. upsert data domain tables
3. upsert `source_status`
4. `finish_run(ingestion_run_id, status, notes, metadata)`

ทำให้แทนที่ไฟล์ manifest ได้ครบ และ trace/debug ง่ายขึ้นมาก
