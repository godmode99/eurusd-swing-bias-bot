นี่คือสิ่งที่ ควรมีใน config/config.example.yaml สำหรับโปรเจกต์นี้ (ให้ Codex อ่านแล้วเอาไปใช้ได้เลย) — ครอบคลุม path, data sources, thresholds, scoring, fuse, และ EA contract

project:
name: eurusd-swing-bias-bot
timezone: Asia/Bangkok
run_window_local: "07:30-09:00"
symbol: EURUSD
entry_timeframe: H4
bias_update_frequency: daily

paths:

# IMPORTANT: set this to your MT5 data folder path:

# Example (Windows):

# C:\Users\<you>\AppData\Roaming\MetaQuotes\Terminal\<hash>\MQL5\Files

mt5_files_dir: "C:/REPLACE/MT5/MQL5/Files"

# Output files (written by Python)

bias_json_filename: "bias_eurusd.json"
bias_history_csv: "bias_history.csv"

# Input file (written by EA)

trade_log_csv: "trade_log.csv"

data_sources:
fred:
api_key_env: FRED_API_KEY
series_id_us2y: DGS2 # optional tuning
request_timeout_sec: 15
max_retries: 3

prices:
provider: mt5 # options: mt5 | csv
mt5: # used by MetaTrader5 python package
terminal_path: "" # optional; leave blank to use default installation
login: "" # optional; if required
password: "" # optional
server: "" # optional
csv:
eurusd_d1_csv: "data/samples/eurusd_d1.sample.csv"
eurusd_h4_csv: "data/samples/eurusd_h4.sample.csv"

events: # v0: keep it manual / always LOW
mode: manual # manual | calendar (v1)
default_event_risk: LOW # LOW | HIGH

bias_engine:
ttl_days_default: 3

yields:
zscore_window_days: 60 # 60 or 252 (trading days) are typical
delta_5d_days: 5
delta_20d_days: 20

    # direction triggers (v0)
    zscore_threshold: 1.0
    require_delta_20d_sign: true

trend_alignment:
method: ma_slope # ma_slope | structure (future)
ma_period: 20
slope_lookback_days: 5
flat_slope_epsilon: 0.0 # set >0 if you want a deadzone

scoring:

# strength score = us2y_shock(0-4) + d1_alignment(0-3) + confirm(0-2) + event_penalty(0..-3)

clamp_min: 0
clamp_max: 10

us2y_shock_buckets: # abs(zscore) ranges -> score - { min_abs_z: 0.0, max_abs_z: 0.5, score: 0 } - { min_abs_z: 0.5, max_abs_z: 1.0, score: 1 } - { min_abs_z: 1.0, max_abs_z: 1.5, score: 2 } - { min_abs_z: 1.5, max_abs_z: 2.0, score: 3 } - { min_abs_z: 2.0, max_abs_z: 99.0, score: 4 }

d1_alignment_scores:
aligned: 3
mixed: 1
opposite: 0
neutral_direction: 0

confirm_score:
enabled: false
score: 0 # v0: keep 0 # future: add DXY or other confirm signals

event_penalty:
LOW: 0
HIGH: -3

state_machine:
bias_trend_delta3_threshold: 1 # delta3 >= +1 strengthening, <= -1 weakening
early_reversal:
strength_drop_2d: 3 # warning if strength drops >= 3 within 2 days
flip_lookback_days: 2 # warning if direction flips within 2 days
history_days_to_keep: 90

decision:
trade_permission:
min_strength: 6
reject_if_bias_trend: WEAKENING
reject_if_warning: true
reject_if_event_risk: HIGH

risk_budget_mapping:
weak: { min_strength: 0, max_strength: 3, risk_per_trade_pct: 0.0 }
med: { min_strength: 4, max_strength: 6, risk_per_trade_pct: 0.5 }
strong: { min_strength: 7, max_strength: 10, risk_per_trade_pct: 1.0 }

overrides:
if_warning_then_risk_pct: 0.0
if_event_risk_high_then_risk_pct: 0.0

fuse:

# Safety fuse uses pnl in R units from trade_log.csv

enabled: true
daily_max_loss_r: -2.0
weekly_max_loss_r: -4.0

# timezone for "day/week" grouping:

timezone: Asia/Bangkok

ea_contract:

# EA expects these exact values and will reject otherwise

freshness_max_hours: 30
allowed_directions: [LONG, SHORT, NEUTRAL]
allowed_event_risk: [LOW, HIGH]
allowed_bias_trend: [STRENGTHENING, WEAKENING, STABLE]
allowed_trade_permission: [YES, NO]

logging:
level: INFO
json_pretty: true
write_debug_files: false

สรุปว่าต้องมี “ขั้นต่ำ” อะไรบ้าง (ถ้ามึงอยากลดให้สั้น)

paths.mt5_files_dir

data_sources.fred.series_id_us2y + api_key_env

data_sources.prices.provider

bias_engine (zscore window, thresholds)

decision.risk_budget_mapping + trade_permission.min_strength

fuse (-2R/-4R)

ea_contract.freshness_max_hours
