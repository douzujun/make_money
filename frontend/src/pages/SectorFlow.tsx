import { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { RefreshCw, TrendingUp, TrendingDown, Minus, ChevronDown, ChevronUp, Info, X } from 'lucide-react';
import { createChart, ColorType, LineSeries, LineType } from 'lightweight-charts';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

// 12 色定性色板，循环使用
const COLOR_PALETTE = [
  '#6366f1', '#f59e0b', '#06b6d4', '#10b981',
  '#f43f5e', '#a855f7', '#0ea5e9', '#f97316',
  '#84cc16', '#ec4899', '#14b8a6', '#8b5cf6',
];
const getColor = (idx: number) => COLOR_PALETTE[idx % COLOR_PALETTE.length];

// ── Types ────────────────────────────────────────────────────────────────────

interface FlowRecord {
  date: string;
  net_inflow_main: number | null;
  net_inflow_main_ratio: number | null;
  change_pct: number | null;
  net_inflow_super_large: number | null;
  net_inflow_large: number | null;
}

interface IndustryData {
  sectors: string[];
  dates: string[];
  data: Record<string, FlowRecord[]>;
  message?: string;
}

interface ConceptSector {
  name: string;
  change_pct: number | null;
  net_inflow_main: number | null;
  net_inflow_main_ratio: number | null;
}

interface SignalData {
  sector_name: string;
  latest_date: string;
  latest_change_pct: number | null;
  latest_net_inflow_main: number | null;
  score: number;
  direction: string;
  label: string;
  win_rate_hint: string;
  details: {
    fund_flow_score: number;
    price_momentum_score: number;
    global_risk_score: number;
    consecutive_inflow_days: number;
    avg_5d_ratio: number;
  };
}

type ViewMode = 'amount' | 'ratio' | 'change';
type DataSource = 'auto' | 'eastmoney' | 'ths';

// ── Helpers ──────────────────────────────────────────────────────────────────

const fmtYi = (v: number | null) => {
  if (v === null || v === undefined) return '—';
  const yi = v / 10000;
  return `${yi >= 0 ? '+' : ''}${yi.toFixed(2)}亿`;
};

const fmtPct = (v: number | null) => {
  if (v === null || v === undefined) return '—';
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
};

const inflowColor = (v: number | null) =>
  v === null ? '#6b7280' : v > 0 ? '#ef4444' : '#22c55e';

const signalColor = (d: string) =>
  d === 'bullish' ? '#ef4444' : d === 'bearish' ? '#22c55e' : '#6b7280';

const signalBg = (d: string) =>
  d === 'bullish' ? 'rgba(239,68,68,0.1)' : d === 'bearish' ? 'rgba(34,197,94,0.1)' : 'rgba(107,114,128,0.1)';

const SignalIcon = ({ direction }: { direction: string }) =>
  direction === 'bullish' ? <TrendingUp size={14} /> : direction === 'bearish' ? <TrendingDown size={14} /> : <Minus size={14} />;

// ── Heatmap cell ─────────────────────────────────────────────────────────────

function HeatCell({
  name, value, colorIdx, onClick,
}: {
  name: string; value: number | null; colorIdx: number; onClick: () => void;
}) {
  const isSelected = colorIdx >= 0;
  const lineColor = isSelected ? getColor(colorIdx) : undefined;
  const intensity = value === null ? 0 : Math.min(Math.abs(value) / 500000, 1);
  const bgAlpha = 0.05 + intensity * 0.25;
  const bg = isSelected
    ? `${lineColor}22`
    : value === null ? 'rgba(107,114,128,0.08)'
    : value > 0 ? `rgba(239,68,68,${bgAlpha})` : `rgba(34,197,94,${bgAlpha})`;

  return (
    <div
      onClick={onClick}
      style={{
        padding: '10px 12px', borderRadius: '10px', background: bg,
        border: isSelected ? `2px solid ${lineColor}` : '1px solid transparent',
        cursor: 'pointer', transition: 'all 0.2s', minWidth: '100px', position: 'relative',
      }}
      onMouseEnter={e => {
        if (!isSelected) (e.currentTarget as HTMLDivElement).style.border = '1px solid var(--border-color)';
      }}
      onMouseLeave={e => {
        if (!isSelected) (e.currentTarget as HTMLDivElement).style.border = '1px solid transparent';
      }}
    >
      {isSelected && (
        <div style={{
          position: 'absolute', top: 4, right: 6,
          width: 8, height: 8, borderRadius: '50%', background: lineColor,
        }} />
      )}
      <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>{name}</div>
      <div style={{ fontSize: '13px', fontWeight: 700, color: inflowColor(value) }}>{fmtYi(value)}</div>
    </div>
  );
}

// ── Multi-sector smooth chart ─────────────────────────────────────────────────

function MultiSectorChart({
  allData, selectedSectors, days, viewMode,
}: {
  allData: Record<string, FlowRecord[]>;
  selectedSectors: string[];
  days: number;
  viewMode: ViewMode;
}) {
  const chartRef = useRef<HTMLDivElement>(null);
  const key = selectedSectors.slice().sort().join('|') + '|' + viewMode + '|' + days;

  useEffect(() => {
    if (!chartRef.current || selectedSectors.length === 0) return;

    const chartH = Math.min(400, Math.max(300, 240 + selectedSectors.length * 8));

    const chart = createChart(chartRef.current, {
      width: chartRef.current.clientWidth,
      height: chartH,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#9ca3af',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(107,114,128,0.08)' },
        horzLines: { color: 'rgba(107,114,128,0.08)' },
      },
      rightPriceScale: {
        borderColor: 'rgba(107,114,128,0.2)',
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: 'rgba(107,114,128,0.2)',
        timeVisible: false,
        fixLeftEdge: true,
        fixRightEdge: true,
      },
      crosshair: { mode: 1 },
      handleScroll: true,
      handleScale: true,
    });

    const lineW = selectedSectors.length <= 4 ? 2.5 : selectedSectors.length <= 8 ? 2 : 1.5;

    selectedSectors.forEach((name, idx) => {
      const records = allData[name] || [];
      const series = chart.addSeries(LineSeries, {
        color: getColor(idx),
        lineWidth: lineW as any,
        lineType: LineType.Curved,
        title: name,
        priceLineVisible: false,
        lastValueVisible: selectedSectors.length <= 6,
        crosshairMarkerRadius: 4,
        crosshairMarkerBorderWidth: 1.5,
      });

      const data = records
        .filter(r => {
          if (viewMode === 'amount') return r.net_inflow_main !== null;
          if (viewMode === 'ratio') return r.net_inflow_main_ratio !== null;
          return r.change_pct !== null;
        })
        .map(r => ({
          time: r.date as any,
          value: viewMode === 'amount'
            ? parseFloat((r.net_inflow_main! / 10000).toFixed(3))
            : viewMode === 'ratio'
            ? parseFloat((r.net_inflow_main_ratio ?? 0).toFixed(3))
            : parseFloat((r.change_pct ?? 0).toFixed(2)),
        }))
        .sort((a, b) => (a.time > b.time ? 1 : -1));

      if (data.length) series.setData(data);
    });

    chart.timeScale().fitContent();

    const ro = new ResizeObserver(() => {
      if (chartRef.current) chart.resize(chartRef.current.clientWidth, chartH);
    });
    ro.observe(chartRef.current);

    return () => { chart.remove(); ro.disconnect(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return <div ref={chartRef} style={{ width: '100%' }} />;
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function SectorFlow() {
  const [industryData, setIndustryData] = useState<IndustryData | null>(null);
  const [conceptData, setConceptData] = useState<ConceptSector[]>([]);
  const [signals, setSignals] = useState<SignalData[]>([]);
  const [days, setDays] = useState(20);
  const [selectedSectors, setSelectedSectors] = useState<string[]>([]);
  const [viewMode, setViewMode] = useState<ViewMode>('change');
  const [dataSource, setDataSource] = useState<DataSource>('auto');
  const [lastSource, setLastSource] = useState('');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [autoBackfilling, setAutoBackfilling] = useState(false);
  const [showHint, setShowHint] = useState(false);
  const [lastUpdated, setLastUpdated] = useState('');
  const [backfilling, setBackfilling] = useState(false);
  const autoBackfillStarted = useRef(false);
  const daysRef = useRef(days);
  daysRef.current = days;

  const fetchAll = async (d = days) => {
    setLoading(true);
    try {
      const [indRes, conRes, sigRes] = await Promise.all([
        axios.get(`${API_BASE_URL}/api/v1/sector-flow/industry?days=${d}`),
        axios.get(`${API_BASE_URL}/api/v1/sector-flow/concept`),
        axios.get(`${API_BASE_URL}/api/v1/sector-flow/signals`),
      ]);
      setIndustryData(indRes.data);
      setConceptData(conRes.data.sectors || []);
      setSignals(sigRes.data.signals || []);
      setLastUpdated(new Date().toLocaleTimeString('zh-CN'));

      // Auto-backfill on first load when historical data is sparse
      const dates: string[] = indRes.data.dates || [];
      if (dates.length < 5 && !autoBackfillStarted.current) {
        autoBackfillStarted.current = true;
        setAutoBackfilling(true);
        axios.post(`${API_BASE_URL}/api/v1/sector-flow/backfill?days=20`).catch(() => {});
        // Poll at 15s / 30s, then final fetch + clear banner at 42s
        [15000, 30000].forEach(ms => setTimeout(() => fetchAll(d), ms));
        setTimeout(() => { fetchAll(d); setAutoBackfilling(false); }, 42000);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    const POST_OPTS = { timeout: 8000 };
    try {
      const [res] = await Promise.all([
        axios.post(`${API_BASE_URL}/api/v1/sector-flow/refresh?source=${dataSource}`, null, POST_OPTS),
        axios.post(`${API_BASE_URL}/api/v1/sector-flow/backfill?days=20`, null, POST_OPTS),
      ]);
      setLastSource(res.data?.source || dataSource);
    } catch {
      // backend is fire-and-forget; ignore errors, staggered polls still run
    } finally {
      setRefreshing(false);
    }
    // Re-fetch at 10s / 25s / 40s using latest days value via ref
    [10000, 25000, 40000].forEach(ms =>
      setTimeout(() => fetchAll(daysRef.current), ms)
    );
  };

  const handleBackfill = async () => {
    setBackfilling(true);
    try {
      await axios.post(`${API_BASE_URL}/api/v1/sector-flow/backfill?days=30`, null, { timeout: 8000 });
    } catch {
      // ignore
    } finally {
      setBackfilling(false);
    }
    [15000, 30000, 42000].forEach(ms =>
      setTimeout(() => fetchAll(daysRef.current), ms)
    );
  };

  useEffect(() => { fetchAll(); }, []);

  const handleDaysChange = (d: number) => { setDays(d); fetchAll(d); };

  const allSectors = industryData?.sectors ?? [];

  const toggleSector = (name: string) => {
    setSelectedSectors(prev =>
      prev.includes(name) ? prev.filter(s => s !== name) : [...prev, name]
    );
  };

  const handleSelectAll = () => {
    if (selectedSectors.length === allSectors.length) {
      setSelectedSectors([]);
    } else {
      setSelectedSectors([...allSectors]);
      // 全选时自动切到占比视图，避免绝对值差异悬殊
      setViewMode('ratio');
    }
  };

  // Latest inflow per sector (heatmap)
  const latestInflow: Record<string, number | null> = {};
  if (industryData) {
    for (const [name, records] of Object.entries(industryData.data)) {
      const sorted = [...records].sort((a, b) => b.date.localeCompare(a.date));
      latestInflow[name] = sorted[0]?.net_inflow_main ?? null;
    }
  }

  const hasData = industryData && allSectors.length > 0;
  const topSignals = signals.slice(0, 5);
  const bottomSignals = [...signals].reverse().slice(0, 5);
  const isAllSelected = allSectors.length > 0 && selectedSectors.length === allSectors.length;
  const showLegendCount = selectedSectors.length > 8;

  return (
    <div className="animate-fade-in">
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px' }}>
        <div>
          <h1 style={{ fontSize: '22px', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>板块资金流</h1>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)', margin: '4px 0 0' }}>
            A股行业资金轮动监控 · 数据来自东方财富 · 每个交易日16:05自动更新
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {lastUpdated && (
            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              更新于 {lastUpdated}
              {lastSource && (
                <span style={{
                  marginLeft: '6px', padding: '1px 6px', borderRadius: '8px', fontSize: '11px',
                  background: lastSource === 'ths' ? 'rgba(16,185,129,0.12)' : 'rgba(99,102,241,0.12)',
                  color: lastSource === 'ths' ? '#10b981' : '#6366f1',
                }}>
                  {lastSource === 'ths' ? '同花顺' : '东方财富'}
                </span>
              )}
            </span>
          )}
          {[10, 20, 60].map(d => (
            <button key={d} onClick={() => handleDaysChange(d)} style={{
              padding: '6px 14px', borderRadius: '8px', fontSize: '13px', fontWeight: 500,
              border: '1px solid var(--border-color)', cursor: 'pointer',
              background: days === d ? '#6366f1' : 'var(--bg-secondary)',
              color: days === d ? 'white' : 'var(--text-secondary)',
            }}>近{d}日</button>
          ))}
          {/* 数据源选择器 */}
          <div style={{ display: 'flex', borderRadius: '8px', overflow: 'hidden', border: '1px solid var(--border-color)' }}>
            {([
              { val: 'auto',       label: '自动' },
              { val: 'ths',        label: '同花顺' },
              { val: 'eastmoney',  label: '东方财富' },
            ] as { val: DataSource; label: string }[]).map(({ val, label }) => (
              <button key={val} onClick={() => setDataSource(val)} style={{
                padding: '6px 11px', fontSize: '12px', fontWeight: 500, border: 'none', cursor: 'pointer',
                background: dataSource === val ? '#6366f1' : 'var(--bg-secondary)',
                color: dataSource === val ? 'white' : 'var(--text-secondary)',
                borderRight: val !== 'eastmoney' ? '1px solid var(--border-color)' : 'none',
              }}>{label}</button>
            ))}
          </div>
          <button onClick={handleRefresh} disabled={refreshing} style={{
            display: 'flex', alignItems: 'center', gap: '6px',
            padding: '8px 16px', borderRadius: '10px', fontSize: '13px', fontWeight: 500,
            border: '1px solid var(--border-color)', background: 'var(--bg-secondary)',
            color: 'var(--text-secondary)', cursor: refreshing ? 'not-allowed' : 'pointer',
          }}>
            <RefreshCw size={14} style={{ animation: refreshing ? 'spin 1s linear infinite' : 'none' }} />
            {refreshing ? '拉取中…约40秒' : '刷新数据'}
          </button>
        </div>
      </div>

      {/* Auto-backfill banner */}
      {autoBackfilling && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: '10px',
          padding: '10px 16px', borderRadius: '10px', marginBottom: '16px',
          background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(99,102,241,0.2)',
          fontSize: '13px', color: '#6366f1', fontWeight: 500,
        }}>
          <RefreshCw size={14} style={{ animation: 'spin 1s linear infinite', flexShrink: 0 }} />
          正在自动拉取近20个交易日历史数据（约40秒），完成后自动刷新…
        </div>
      )}

      {/* Hint */}
      <div style={{
        background: 'var(--bg-primary)', border: '1px solid var(--border-color)',
        borderRadius: '14px', marginBottom: '20px', overflow: 'hidden',
      }}>
        <button onClick={() => setShowHint(!showHint)} style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '14px 20px', background: 'none', border: 'none', cursor: 'pointer',
          color: 'var(--text-secondary)', fontSize: '13px', fontWeight: 500,
        }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Info size={15} color="#6366f1" /> 如何解读数据
          </span>
          {showHint ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
        {showHint && (
          <div style={{ padding: '0 20px 16px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            {[
              ['主力净流入', '机构大资金（超大单+大单）的净买入额。持续流入 = 机构在建仓'],
              ['占比(%)视图', '净流入额占当日总成交额比例，全选时用此视图更易对比'],
              ['多板块对比', '点击热力格加入对比，「全选」自动切占比视图，线条平滑处理'],
              ['明日信号分', '资金流(40%) + 价格动量(40%) + 全局VIX风险(20%)合成。仅作参考'],
            ].map(([title, desc]) => (
              <div key={title} style={{
                padding: '10px 14px', borderRadius: '10px',
                background: 'rgba(99,102,241,0.06)', borderLeft: '3px solid #6366f1',
              }}>
                <div style={{ fontSize: '13px', fontWeight: 600, color: '#6366f1', marginBottom: '4px' }}>{title}</div>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{desc}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {!hasData ? (
        <div style={{
          background: 'var(--bg-primary)', border: '1px solid var(--border-color)',
          borderRadius: '20px', padding: '80px 40px', textAlign: 'center',
        }}>
          <div style={{ fontSize: '40px', marginBottom: '16px' }}>📊</div>
          <p style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-primary)', margin: '0 0 8px' }}>暂无板块资金数据</p>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)', margin: '0 0 24px' }}>
            请点击右上角「刷新数据」按钮抓取今日东方财富板块资金流数据
          </p>
          <button onClick={handleRefresh} disabled={refreshing} style={{
            padding: '10px 24px', borderRadius: '10px', background: '#6366f1',
            color: 'white', border: 'none', cursor: 'pointer', fontSize: '14px', fontWeight: 600,
          }}>
            {refreshing ? '抓取中…' : '立即抓取数据'}
          </button>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>

          {/* Row 1: Concept + Signals */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
            {/* Concept hot board */}
            <div style={{ background: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '16px', padding: '20px' }}>
              <h3 style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 16px' }}>
                概念热榜 · 今日主力净流入 Top
              </h3>
              {conceptData.length === 0 ? (
                <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>暂无概念数据</p>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {conceptData.slice(0, 10).map((c, i) => (
                    <div key={c.name} style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <span style={{
                        width: '20px', fontSize: '12px', fontWeight: 700, textAlign: 'center',
                        color: i < 3 ? '#ef4444' : 'var(--text-muted)',
                      }}>{i + 1}</span>
                      <span style={{ flex: 1, fontSize: '13px', fontWeight: 500, color: 'var(--text-primary)' }}>{c.name}</span>
                      <span style={{ fontSize: '13px', fontWeight: 600, color: inflowColor(c.net_inflow_main) }}>{fmtYi(c.net_inflow_main)}</span>
                      <span style={{ fontSize: '12px', color: inflowColor(c.change_pct), width: '52px', textAlign: 'right' }}>{fmtPct(c.change_pct)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Signal rankings */}
            <div style={{ background: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '16px', padding: '20px' }}>
              <h3 style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 16px' }}>
                明日信号 · 行业综合评分
              </h3>
              {signals.length === 0 ? (
                <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>暂无信号数据</p>
              ) : (
                <>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px', fontWeight: 600 }}>看多信号最强 TOP5</div>
                  {topSignals.map(s => (
                    <div key={s.sector_name} style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                      <span style={{
                        display: 'flex', alignItems: 'center', gap: '4px', fontSize: '12px',
                        padding: '2px 8px', borderRadius: '12px',
                        background: signalBg(s.direction), color: signalColor(s.direction), fontWeight: 600,
                      }}><SignalIcon direction={s.direction} /> {s.label}</span>
                      <span style={{ flex: 1, fontSize: '13px', color: 'var(--text-primary)' }}>{s.sector_name}</span>
                      <span style={{ fontSize: '12px', fontWeight: 700, color: signalColor(s.direction) }}>{s.score}</span>
                    </div>
                  ))}
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', margin: '12px 0 8px', fontWeight: 600 }}>看空信号最强 TOP5</div>
                  {bottomSignals.map(s => (
                    <div key={s.sector_name} style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                      <span style={{
                        display: 'flex', alignItems: 'center', gap: '4px', fontSize: '12px',
                        padding: '2px 8px', borderRadius: '12px',
                        background: signalBg(s.direction), color: signalColor(s.direction), fontWeight: 600,
                      }}><SignalIcon direction={s.direction} /> {s.label}</span>
                      <span style={{ flex: 1, fontSize: '13px', color: 'var(--text-primary)' }}>{s.sector_name}</span>
                      <span style={{ fontSize: '12px', fontWeight: 700, color: signalColor(s.direction) }}>{s.score}</span>
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>

          {/* Row 2: Heatmap */}
          <div style={{ background: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '16px', padding: '20px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
              <h3 style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>
                行业热力图 · 最新交易日主力净流入
              </h3>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                {selectedSectors.length > 0 && (
                  <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                    已选 {selectedSectors.length}/{allSectors.length}
                  </span>
                )}
                <button onClick={handleSelectAll} style={{
                  padding: '4px 12px', borderRadius: '8px', fontSize: '12px', fontWeight: 600,
                  border: '1px solid var(--border-color)', cursor: 'pointer',
                  background: isAllSelected ? '#6366f1' : 'var(--bg-secondary)',
                  color: isAllSelected ? 'white' : 'var(--text-secondary)',
                }}>
                  {isAllSelected ? '取消全选' : '全选'}
                </button>
                {selectedSectors.length > 0 && !isAllSelected && (
                  <button onClick={() => setSelectedSectors([])} style={{
                    display: 'flex', alignItems: 'center', gap: '4px',
                    padding: '4px 10px', borderRadius: '8px', fontSize: '12px',
                    border: '1px solid var(--border-color)', background: 'var(--bg-secondary)',
                    color: 'var(--text-secondary)', cursor: 'pointer',
                  }}>
                    <X size={12} /> 清空
                  </button>
                )}
              </div>
            </div>
            <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: '0 0 16px' }}>
              点击板块切换选中 · 全选自动切换为占比视图 · 红色=流入 绿色=流出（A股配色）
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
              {allSectors.map(name => (
                <HeatCell
                  key={name}
                  name={name}
                  value={latestInflow[name] ?? null}
                  colorIdx={selectedSectors.indexOf(name)}
                  onClick={() => toggleSector(name)}
                />
              ))}
            </div>
          </div>

          {/* Row 3: Comparison chart */}
          {selectedSectors.length > 0 && (
            <div style={{ background: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: '16px', padding: '20px' }}>
              {/* Chart toolbar */}
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '16px', gap: '16px' }}>
                <div style={{ flexShrink: 0 }}>
                  <h3 style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>
                    板块对比 · 主力净流入走势（近{days}日）
                  </h3>
                  <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: '4px 0 0' }}>
                    {viewMode === 'amount'
                      ? '单位：亿元，正值=流入，负值=流出（仅含有资金流记录的交易日）'
                      : viewMode === 'ratio'
                      ? '单位：占总成交额 %，正值=主力净买入（仅含有资金流记录的交易日）'
                      : '单位：涨跌幅 %，来自板块历史收盘价计算，覆盖完整历史区间'}
                  </p>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                  {/* 回填历史 */}
                  <button onClick={handleBackfill} disabled={backfilling} style={{
                    padding: '5px 12px', borderRadius: '8px', fontSize: '12px', fontWeight: 500,
                    border: '1px solid var(--border-color)', background: 'var(--bg-secondary)',
                    color: backfilling ? 'var(--text-muted)' : 'var(--text-secondary)',
                    cursor: backfilling ? 'not-allowed' : 'pointer',
                  }}>
                    {backfilling ? '回填中…约35秒' : '回填历史'}
                  </button>
                  {/* View mode toggle */}
                  <div style={{ display: 'flex', borderRadius: '8px', overflow: 'hidden', border: '1px solid var(--border-color)' }}>
                    {([
                      { val: 'amount', label: '净额(亿)' },
                      { val: 'ratio',  label: '占比(%)' },
                      { val: 'change', label: '涨跌幅' },
                    ] as { val: ViewMode; label: string }[]).map(({ val, label }) => (
                      <button key={val} onClick={() => setViewMode(val)} style={{
                        padding: '5px 10px', fontSize: '12px', fontWeight: 600, border: 'none', cursor: 'pointer',
                        background: viewMode === val ? '#6366f1' : 'var(--bg-secondary)',
                        color: viewMode === val ? 'white' : 'var(--text-secondary)',
                        borderRight: val !== 'change' ? '1px solid var(--border-color)' : 'none',
                      }}>{label}</button>
                    ))}
                  </div>
                </div>
              </div>

              {/* Legend */}
              {showLegendCount ? (
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '12px' }}>
                  已选 {selectedSectors.length} 个板块（颜色循环使用 12 色）·
                  <button onClick={() => setSelectedSectors([])} style={{
                    marginLeft: '8px', fontSize: '12px', color: '#6366f1', background: 'none',
                    border: 'none', cursor: 'pointer', padding: 0, fontWeight: 600,
                  }}>清空选择</button>
                </div>
              ) : (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '12px' }}>
                  {selectedSectors.map((name, idx) => (
                    <div key={name} onClick={() => toggleSector(name)} style={{
                      display: 'flex', alignItems: 'center', gap: '5px',
                      padding: '3px 9px', borderRadius: '20px', cursor: 'pointer',
                      background: `${getColor(idx)}18`, border: `1px solid ${getColor(idx)}55`,
                      fontSize: '12px', fontWeight: 600, color: getColor(idx),
                    }} title="点击移除">
                      <span style={{ width: 7, height: 7, borderRadius: '50%', background: getColor(idx), flexShrink: 0 }} />
                      {name}
                      <X size={9} />
                    </div>
                  ))}
                </div>
              )}

              <MultiSectorChart
                allData={industryData!.data}
                selectedSectors={selectedSectors}
                days={days}
                viewMode={viewMode}
              />

              {/* Signal mini-cards (max 6 shown) */}
              {selectedSectors.length <= 6 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginTop: '16px' }}>
                  {selectedSectors.map((name, idx) => {
                    const sig = signals.find(s => s.sector_name === name);
                    if (!sig) return null;
                    return (
                      <div key={name} style={{
                        flex: '1 1 160px', padding: '12px 14px', borderRadius: '12px',
                        background: 'var(--bg-secondary)', borderLeft: `3px solid ${getColor(idx)}`,
                      }}>
                        <div style={{ fontSize: '12px', fontWeight: 700, color: getColor(idx), marginBottom: '6px' }}>{name}</div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
                          <span style={{
                            display: 'flex', alignItems: 'center', gap: '3px', fontSize: '12px',
                            padding: '2px 7px', borderRadius: '10px',
                            background: signalBg(sig.direction), color: signalColor(sig.direction), fontWeight: 600,
                          }}><SignalIcon direction={sig.direction} /> {sig.label}</span>
                          <span style={{ fontSize: '13px', fontWeight: 700, color: signalColor(sig.direction) }}>{sig.score}/100</span>
                        </div>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>连续流入 {sig.details.consecutive_inflow_days} 天</div>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>5日均占比 {sig.details.avg_5d_ratio}%</div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
