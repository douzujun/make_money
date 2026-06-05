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

type SignalHorizon = 'n1' | 'n2' | 'weekly';

interface SignalHorizonData {
  score: number;
  direction: string;
  label: string;
  summary: string;
  details: Record<string, number | string | null | undefined>;
}

type DisplaySignalData = Omit<SignalHorizonData, 'details'> & {
  details?: SignalHorizonData['details'];
};

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
  horizons?: Record<SignalHorizon, SignalHorizonData>;
  signal_action?: {
    action: 'accumulate' | 'hold' | 'reduce' | 'reduce_watch' | 'observe';
    label: string;
    strength: string;
    reason: string;
    horizon: SignalHorizon;
    score: number;
    flow_coverage_rate: number | null;
  };
  display_signal?: DisplaySignalData;
}

interface BacktestStat {
  samples: number;
  hit_rate: number | null;
  excess_hit_rate?: number | null;
  avg_return: number | null;
  benchmark_avg_return?: number | null;
  excess_avg_return?: number | null;
  flow_coverage_samples?: number;
  flow_coverage_rate?: number | null;
}

interface BacktestThreshold extends BacktestStat {
  threshold: number;
}

interface SignalBacktest {
  horizon: SignalHorizon;
  label: string;
  forward_days: number;
  bullish: BacktestStat;
  bearish: BacktestStat;
  thresholds: BacktestThreshold[];
  best_threshold: BacktestThreshold;
  top_sectors: Array<{
    sector_name: string;
    samples: number;
    hit_rate: number | null;
    avg_return: number | null;
  }>;
}

type ViewMode = 'amount' | 'ratio' | 'change';
type DataSource = 'auto' | 'eastmoney' | 'ths';
type HeatmapSortMode = 'default' | 'inflow' | 'signal';

const HORIZON_TABS: { key: SignalHorizon; label: string; short: string }[] = [
  { key: 'n1', label: 'N+1 明日', short: 'N+1' },
  { key: 'n2', label: 'N+2 延续', short: 'N+2' },
  { key: 'weekly', label: '周级趋势', short: '周级' },
];
const SIGNAL_STRONG_THRESHOLD = 65;

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

const fmtRate = (v: number | null | undefined) => {
  if (v === null || v === undefined) return '—';
  return `${v.toFixed(1)}%`;
};

const getHorizonSignal = (s: SignalData, horizon: SignalHorizon): SignalHorizonData => {
  const fallback: SignalHorizonData = {
    score: s.score,
    direction: s.direction,
    label: s.label,
    summary: s.win_rate_hint,
    details: s.details,
  };
  return s.horizons?.[horizon] ?? fallback;
};

const getDisplaySignal = (s: SignalData, fallback: SignalHorizonData): DisplaySignalData =>
  s.display_signal ?? fallback;

const isRiskAction = (action?: string) => action === 'reduce' || action === 'reduce_watch';

const riskActionRank = (action?: string) => action === 'reduce' ? 2 : action === 'reduce_watch' ? 1 : 0;

const inflowColor = (v: number | null) =>
  v === null ? '#6b7280' : v > 0 ? '#ef4444' : '#22c55e';

const signalColor = (d: string) =>
  d === 'bullish' ? '#ef4444' : d === 'bearish' ? '#22c55e' : '#6b7280';

const signalBg = (d: string) =>
  d === 'bullish' ? 'rgba(239,68,68,0.1)' : d === 'bearish' ? 'rgba(34,197,94,0.1)' : 'rgba(107,114,128,0.1)';

const actionColor = (action?: string) =>
  action === 'accumulate' ? '#ef4444' : action === 'reduce' || action === 'reduce_watch' ? '#22c55e' : action === 'observe' ? '#f59e0b' : '#6b7280';

const actionBg = (action?: string) =>
  action === 'accumulate' ? 'rgba(239,68,68,0.1)' : action === 'reduce' || action === 'reduce_watch' ? 'rgba(34,197,94,0.1)' : action === 'observe' ? 'rgba(245,158,11,0.12)' : 'rgba(107,114,128,0.1)';

const SignalIcon = ({ direction }: { direction: string }) =>
  direction === 'bullish' ? <TrendingUp size={14} /> : direction === 'bearish' ? <TrendingDown size={14} /> : <Minus size={14} />;

const FinalSignalIcon = ({ signal, action }: { signal: DisplaySignalData; action?: string }) =>
  action === 'accumulate' || signal.direction === 'bullish' ? <TrendingUp size={14} />
    : action === 'reduce' || action === 'reduce_watch' || signal.direction === 'bearish' ? <TrendingDown size={14} />
      : <Minus size={14} />;

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

function SignalRankRow({ signal, horizon }: { signal: SignalData; horizon: SignalHorizon }) {
  const hs = getHorizonSignal(signal, horizon);
  const display = getDisplaySignal(signal, hs);
  const displayAction = signal.signal_action?.action;
  const displayColor = displayAction ? actionColor(displayAction) : signalColor(display.direction);
  const displayBg = displayAction ? actionBg(displayAction) : signalBg(display.direction);

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
      <span style={{
        display: 'flex', alignItems: 'center', gap: '4px', fontSize: '12px',
        padding: '2px 8px', borderRadius: '12px',
        background: displayBg, color: displayColor, fontWeight: 600,
      }} title={display.summary}>
        <FinalSignalIcon signal={display} action={displayAction} /> {display.label}
      </span>
      <span style={{ flex: 1, fontSize: '13px', color: 'var(--text-primary)' }}>{signal.sector_name}</span>
      <span title={hs.summary} style={{
        fontSize: '11px', fontWeight: 700, padding: '2px 7px', borderRadius: '10px',
        color: signalColor(hs.direction), background: signalBg(hs.direction),
      }}>
        {HORIZON_TABS.find(h => h.key === horizon)?.short}
      </span>
      <span style={{ fontSize: '12px', fontWeight: 700, color: signalColor(hs.direction) }}>{hs.score}</span>
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
  const [signalBacktests, setSignalBacktests] = useState<Partial<Record<SignalHorizon, SignalBacktest>>>({});
  const [signalHorizon, setSignalHorizon] = useState<SignalHorizon>('n1');
  const [days, setDays] = useState(20);
  const [selectedSectors, setSelectedSectors] = useState<string[]>([]);
  const [viewMode, setViewMode] = useState<ViewMode>('change');
  const [heatmapSort, setHeatmapSort] = useState<HeatmapSortMode>('inflow');
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
      setSignalBacktests(sigRes.data.backtests || {});
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
      await axios.post(`${API_BASE_URL}/api/v1/sector-flow/backfill?days=365`, null, { timeout: 8000 });
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
  const signalScore = new Map(signals.map(s => [s.sector_name, getHorizonSignal(s, signalHorizon).score]));
  const sortedHeatmapSectors = [...allSectors].sort((a, b) => {
    if (heatmapSort === 'signal') {
      return (signalScore.get(b) ?? -Infinity) - (signalScore.get(a) ?? -Infinity);
    }
    if (heatmapSort === 'inflow') {
      return (latestInflow[b] ?? -Infinity) - (latestInflow[a] ?? -Infinity);
    }
    return a.localeCompare(b, 'zh-CN');
  });

  const hasData = industryData && allSectors.length > 0;
  const rankedSignals = [...signals].sort((a, b) => getHorizonSignal(b, signalHorizon).score - getHorizonSignal(a, signalHorizon).score);
  const horizonStrongSignals = rankedSignals.filter(s => getHorizonSignal(s, signalHorizon).score >= SIGNAL_STRONG_THRESHOLD);
  const blockedStrongSignals = horizonStrongSignals.filter(s => isRiskAction(s.signal_action?.action));
  const topSignals = horizonStrongSignals
    .filter(s => !isRiskAction(s.signal_action?.action))
    .slice(0, 5);
  const riskSignals = [...signals]
    .filter(s => isRiskAction(s.signal_action?.action))
    .sort((a, b) => {
      const actionRank = riskActionRank(b.signal_action?.action) - riskActionRank(a.signal_action?.action);
      if (actionRank !== 0) return actionRank;
      return (a.signal_action?.score ?? getHorizonSignal(a, signalHorizon).score) - (b.signal_action?.score ?? getHorizonSignal(b, signalHorizon).score);
    })
    .slice(0, 5);
  const bottomSignals = [...rankedSignals].reverse().slice(0, 5);
  const activeBacktest = signalBacktests[signalHorizon];
  const activeHorizonLabel = HORIZON_TABS.find(h => h.key === signalHorizon)?.label ?? signalHorizon;
  const activeHorizonShort = HORIZON_TABS.find(h => h.key === signalHorizon)?.short ?? signalHorizon;
  const topEmptyText = horizonStrongSignals.length === 0
    ? `${activeHorizonLabel}暂无 ${SIGNAL_STRONG_THRESHOLD}+ 强信号`
    : `${blockedStrongSignals.length} 个${activeHorizonShort}强信号被减仓/风控拦截，暂无通过风控的看多候选`;
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
              ['多周期信号', 'N+1/N+2/周级分别按资金、价格、风险合成，并用历史未来收益做回测验证'],
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
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', marginBottom: '14px' }}>
                <h3 style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>
                  多周期信号 · 行业综合评分
                </h3>
                <div style={{ display: 'flex', borderRadius: '8px', overflow: 'hidden', border: '1px solid var(--border-color)', flexShrink: 0 }}>
                  {HORIZON_TABS.map(({ key, short, label }) => (
                    <button key={key} onClick={() => setSignalHorizon(key)} title={label} style={{
                      padding: '4px 9px', fontSize: '12px', fontWeight: 700, border: 'none', cursor: 'pointer',
                      background: signalHorizon === key ? '#6366f1' : 'var(--bg-secondary)',
                      color: signalHorizon === key ? 'white' : 'var(--text-secondary)',
                      borderRight: key !== 'weekly' ? '1px solid var(--border-color)' : 'none',
                    }}>
                      {short}
                    </button>
                  ))}
                </div>
              </div>
              {signals.length === 0 ? (
                <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>暂无信号数据</p>
              ) : (
                <>
                  <div style={{
                    display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: '8px',
                    marginBottom: '12px',
                  }}>
                    {([
                      ['看多样本', activeBacktest?.bullish.samples ?? 0],
                      ['超额命中', fmtRate(activeBacktest?.bullish.excess_hit_rate ?? activeBacktest?.bullish.hit_rate)],
                      ['超额收益', fmtPct(activeBacktest?.bullish.excess_avg_return ?? null)],
                      ['最佳阈值', activeBacktest?.best_threshold?.samples ? `${activeBacktest.best_threshold.threshold}+` : '—'],
                    ] as [string, string | number][]).map(([label, value]) => (
                      <div key={label} style={{
                        padding: '8px 9px', borderRadius: '8px',
                        background: 'rgba(99,102,241,0.06)', border: '1px solid rgba(99,102,241,0.14)',
                      }}>
                        <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 700, marginBottom: '3px' }}>{label}</div>
                        <div style={{ fontSize: '13px', color: 'var(--text-primary)', fontWeight: 800 }}>{value}</div>
                      </div>
                    ))}
                  </div>
                  <div style={{
                    display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '8px',
                    margin: '-4px 0 12px',
                  }}>
                    {([
                      ['绝对', fmtPct(activeBacktest?.bullish.avg_return ?? null)],
                      ['基准', fmtPct(activeBacktest?.bullish.benchmark_avg_return ?? null)],
                      ['资金覆盖', `${activeBacktest?.bullish.flow_coverage_samples ?? 0}/${activeBacktest?.bullish.samples ?? 0} · ${fmtRate(activeBacktest?.bullish.flow_coverage_rate)}`],
                    ] as [string, string][]).map(([label, value]) => (
                      <div key={label} style={{
                        padding: '6px 8px', borderRadius: '8px',
                        background: 'var(--bg-secondary)', color: 'var(--text-muted)', fontSize: '11px',
                      }}>
                        <span style={{ fontWeight: 700, marginRight: '4px' }}>{label}</span>{value}
                      </div>
                    ))}
                  </div>
                  {activeBacktest?.thresholds?.length ? (
                    <div style={{ display: 'flex', alignItems: 'flex-end', gap: '6px', height: '42px', marginBottom: '12px' }}>
                      {activeBacktest.thresholds.map(t => {
                        const h = Math.max(6, Math.min(36, (t.excess_hit_rate ?? t.hit_rate ?? 0) * 0.36));
                        return (
                          <div key={t.threshold} title={`${t.threshold}+ 样本${t.samples} 超额命中${fmtRate(t.excess_hit_rate ?? t.hit_rate)} 超额${fmtPct(t.excess_avg_return ?? null)} 绝对${fmtPct(t.avg_return)}`} style={{ flex: 1, minWidth: 0 }}>
                            <div style={{
                              height: `${h}px`, borderRadius: '5px 5px 2px 2px',
                              background: t.samples ? 'linear-gradient(180deg, #ef4444, rgba(239,68,68,0.28))' : 'rgba(107,114,128,0.18)',
                            }} />
                            <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '3px', textAlign: 'center' }}>{t.threshold}+</div>
                          </div>
                        );
                      })}
                    </div>
                  ) : null}
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px', fontWeight: 700 }}>
                    看多候选 TOP5 · 强信号且未触发风控 · {activeHorizonLabel}
                  </div>
                  {topSignals.length === 0 ? (
                    <div style={{
                      fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px',
                      padding: '7px 9px', borderRadius: '8px', background: 'var(--bg-secondary)',
                    }}>
                      {topEmptyText}
                    </div>
                  ) : topSignals.map(s => (
                    <SignalRankRow key={s.sector_name} signal={s} horizon={signalHorizon} />
                  ))}
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', margin: '12px 0 8px', fontWeight: 700 }}>
                    减仓/风控观察 TOP5 · 最终动作优先
                  </div>
                  {riskSignals.length === 0 ? (
                    <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px' }}>暂无减仓风控触发</div>
                  ) : riskSignals.map(s => (
                    <SignalRankRow key={s.sector_name} signal={s} horizon={signalHorizon} />
                  ))}
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', margin: '12px 0 8px', fontWeight: 700 }}>
                    低分/看空 TOP5 · 看空样本 {activeBacktest?.bearish.samples ?? 0} · 命中 {fmtRate(activeBacktest?.bearish.hit_rate)}
                  </div>
                  {bottomSignals.map(s => (
                    <SignalRankRow key={s.sector_name} signal={s} horizon={signalHorizon} />
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
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                <div style={{ display: 'flex', borderRadius: '8px', overflow: 'hidden', border: '1px solid var(--border-color)' }}>
                  {([
                    { val: 'inflow', label: '按流入' },
                    { val: 'signal', label: '按看多' },
                    { val: 'default', label: '默认' },
                  ] as { val: HeatmapSortMode; label: string }[]).map(({ val, label }) => (
                    <button key={val} onClick={() => setHeatmapSort(val)} style={{
                      padding: '4px 10px', fontSize: '12px', fontWeight: 600, border: 'none', cursor: 'pointer',
                      background: heatmapSort === val ? '#6366f1' : 'var(--bg-secondary)',
                      color: heatmapSort === val ? 'white' : 'var(--text-secondary)',
                      borderRight: val !== 'default' ? '1px solid var(--border-color)' : 'none',
                    }}>
                      {label}
                    </button>
                  ))}
                </div>
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
              点击板块切换选中 · 当前排序：{heatmapSort === 'signal' ? `${HORIZON_TABS.find(h => h.key === signalHorizon)?.label}看多分由高到低` : heatmapSort === 'inflow' ? '主力净流入由高到低' : '行业名称'} · 红色=流入 绿色=流出（A股配色）
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
              {sortedHeatmapSectors.map(name => (
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
                    {backfilling ? '回填中…约1-3分钟' : '回填一年价格'}
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
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px' }}>
                          <div style={{ flex: 1, fontSize: '12px', fontWeight: 700, color: getColor(idx) }}>{name}</div>
                          <span title={sig.signal_action?.reason} style={{
                            fontSize: '11px', fontWeight: 800, padding: '2px 7px', borderRadius: '10px',
                            color: actionColor(sig.signal_action?.action), background: actionBg(sig.signal_action?.action),
                          }}>{sig.signal_action?.label ?? '观察'}</span>
                        </div>
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '6px', marginBottom: '8px' }}>
                          {HORIZON_TABS.map(({ key, short }) => {
                            const hs = getHorizonSignal(sig, key);
                            return (
                              <div key={key} title={hs.summary} style={{
                                padding: '6px 7px', borderRadius: '8px',
                                background: signalBg(hs.direction),
                                border: `1px solid ${signalColor(hs.direction)}22`,
                              }}>
                                <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 700, marginBottom: '2px' }}>{short}</div>
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '3px' }}>
                                  <span style={{ color: signalColor(hs.direction), display: 'flex', alignItems: 'center' }}>
                                    <SignalIcon direction={hs.direction} />
                                  </span>
                                  <span style={{ fontSize: '12px', fontWeight: 800, color: signalColor(hs.direction) }}>{hs.score}</span>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>连续流入 {sig.details.consecutive_inflow_days ?? 0} 天</div>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>5日均占比 {sig.details.avg_5d_ratio ?? 0}%</div>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>资金覆盖 {fmtRate(sig.signal_action?.flow_coverage_rate)}</div>
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
