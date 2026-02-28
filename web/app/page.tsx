const sections = [
  {
    title: "1) Ingestion Control",
    description:
      "ศูนย์กลางสำหรับติดตามรอบการรัน pipeline และสถานะแหล่งข้อมูล แทน manifest เดิม",
    tables: ["ingestion_runs", "source_status"],
    widgets: [
      "Run Timeline: แสดงสถานะ running/ok/warn/error ตามเวลา",
      "Pipeline Filter: calendar | fred | mt5 | cme_fedwatch",
      "Source Health Table: source_code, latest_at, used_cache, error_message",
    ],
  },
  {
    title: "2) Calendar Domain",
    description:
      "รองรับ raw event, selected event, risk windows และ surprise score สำหรับการตัดสินใจเทรด",
    tables: [
      "calendar_events_raw",
      "calendar_events_selected",
      "calendar_risk_windows",
      "calendar_surprise_scores",
    ],
    widgets: [
      "Economic Calendar Grid: event_time_utc/bkk, currency, impact, event_name",
      "Risk Window Timeline: ช่วงเวลาความเสี่ยงพร้อม severity",
      "Surprise Monitor: surprise_value / zscore / direction",
    ],
  },
  {
    title: "3) FRED Domain",
    description:
      "แสดงข้อมูล time-series จาก fred_series และ fred_observations สำหรับ macro context",
    tables: ["fred_series", "fred_observations"],
    widgets: [
      "Series Selector: เลือก CPI, GDP, Yield ฯลฯ",
      "Observation Chart: value ตาม observation_date",
      "Metadata Panel: frequency, units, notes",
    ],
  },
  {
    title: "4) CME FedWatch Domain",
    description:
      "มุมมองความน่าจะเป็นการเปลี่ยนดอกเบี้ยจาก fedwatch_probabilities",
    tables: ["fedwatch_contracts", "fedwatch_probabilities"],
    widgets: [
      "Meeting Probability Table: meeting_date, target range, probability",
      "Rate Distribution Chart: stacked probability by meeting",
      "Contract Mapping: source_contract -> contract_month",
    ],
  },
  {
    title: "5) MT5 Market Data Domain",
    description:
      "รองรับข้อมูลแท่งราคาและ feature สำหรับ signal dashboard",
    tables: ["market_symbols", "mt5_bars", "mt5_features"],
    widgets: [
      "Multi-timeframe Price Panel: H4 / D1 / W1",
      "Feature Snapshot: atr14, ema20, ema50, structure_event",
      "Symbol Health: latency, latest bar_time_utc, missing bars",
    ],
  },
  {
    title: "6) Derived Views & API Contract",
    description:
      "ผูกกับ v_latest_calendar_selected / v_latest_mt5_feature และ flow start_run -> finish_run",
    tables: ["v_latest_calendar_selected", "v_latest_mt5_feature"],
    widgets: [
      "Latest Snapshot Cards: ข้อมูลล่าสุดต่อโดเมน",
      "Trace Panel: ผูกทุก widget กลับ ingestion_run_id",
      "Ops Checklist: start_run, upsert data, upsert source_status, finish_run",
    ],
  },
];

export default function Home() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <main className="mx-auto flex w-full max-w-7xl flex-col gap-8 px-6 py-10 lg:px-10">
        <header className="rounded-2xl border border-slate-800 bg-slate-900/70 p-6 shadow-lg shadow-slate-950/60">
          <p className="text-xs uppercase tracking-[0.2em] text-cyan-300">
            EURUSD Swing Bias Bot
          </p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight text-white md:text-4xl">
            Database-driven UI Structure
          </h1>
          <p className="mt-3 max-w-4xl text-sm text-slate-300 md:text-base">
            โครงสร้าง UI นี้ออกแบบให้รองรับ schema ใน
            <code className="mx-1 rounded bg-slate-800 px-2 py-1 text-cyan-200">
              docs/database_schema_proposal.md
            </code>
            โดยแยกส่วนการทำงานตาม domain และผูกทุกหน้ากับ
            <span className="font-semibold text-cyan-200"> ingestion_run_id </span>
            เพื่อ trace และ debug ได้ครบตั้งแต่ ingestion ถึง dashboard.
          </p>
        </header>

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {sections.map((section) => (
            <article
              key={section.title}
              className="flex h-full flex-col gap-4 rounded-2xl border border-slate-800 bg-slate-900 p-5"
            >
              <div>
                <h2 className="text-lg font-semibold text-white">{section.title}</h2>
                <p className="mt-2 text-sm leading-6 text-slate-300">{section.description}</p>
              </div>

              <div className="space-y-2">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-cyan-300">
                  Tables / Views
                </p>
                <ul className="flex flex-wrap gap-2 text-xs text-slate-200">
                  {section.tables.map((table) => (
                    <li
                      key={table}
                      className="rounded-full border border-slate-700 bg-slate-800 px-3 py-1"
                    >
                      {table}
                    </li>
                  ))}
                </ul>
              </div>

              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-cyan-300">
                  Suggested Widgets
                </p>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-300">
                  {section.widgets.map((widget) => (
                    <li key={widget}>{widget}</li>
                  ))}
                </ul>
              </div>
            </article>
          ))}
        </section>
      </main>
    </div>
  );
}
