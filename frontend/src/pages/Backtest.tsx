import { useState, useEffect, useRef, useCallback } from 'react';
import {
  createChart, IChartApi, ISeriesApi, LineData, Time, LineSeries,
} from 'lightweight-charts';
import { RefreshCw, Play, Info, ChevronDown, ChevronUp } from 'lucide-react';

const API = '/api/v1';

// ── Types ──────────────────────────────────────────────────────────────────

interface Asset {
  symbol: string;
  name: string;
  category: string;
  since: string;
}

interface Preset {
  id: string;
  name: string;
  description: string;
  weights: Record<string, number>;
}

interface Metrics {
  annual_return: number;
  max_drawdown: number;
  sharpe_ratio: number;
}

interface NavPoint { date: string; nav: number; }

interface PortfolioResult {
  nav_curve: NavPoint[];
  metrics: Metrics;
  error?: string;
}

interface BearPeriod { start: string; end: string; }

interface BacktestResponse {
  portfolio_a: PortfolioResult;
  portfolio_b: PortfolioResult | null;
  bear_periods: BearPeriod[];
  rebalance: string;
  start_date: string;
  end_date: string;
}

interface PriceStatus {
  [symbol: string]: { name: string; cached_rows: number };
}

// ── Palette ────────────────────────────────────────────────────────────────

const COLOR_A = '#6366f1';
const COLOR_B = '#f59e0b';
const COLOR_UP = '#10b981';
const COLOR_DOWN = '#ef4444';

const ASSET_COLORS: Record<string, string> = {
  '510300': '#6366f1',
  '510050': '#8b5cf6',
  '510500': '#0ea5e9',
  '159915': '#06b6d4',
  '513100': '#a855f7',
  '511010': '#10b981',
  '518880': '#f59e0b',
  CASH: '#64748b',
};

// ── Hint tooltip ───────────────────────────────────────────────────────────

function Hint({ text }: { text: string }) {
  const [show, setShow] = useState(false);
  return (
    <span style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}>
      <span
        onMouseEnter={() => setShow(true)}
        onMouseLeave={() => setShow(false)}
        style={{ cursor: 'help', color: 'var(--text-muted)', fontSize: 11, marginLeft: 4, lineHeight: 1 }}
      >
        <Info size={12} />
      </span>
      {show && (
        <div style={{
          position: 'absolute', bottom: 'calc(100% + 6px)', left: '50%',
          transform: 'translateX(-50%)',
          background: '#1e293b', color: '#cbd5e1',
          padding: '10px 14px', borderRadius: 10, fontSize: 12,
          width: 260, zIndex: 200,
          boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
          lineHeight: 1.6, pointerEvents: 'none',
          border: '1px solid #334155',
        }}>
          {text}
        </div>
      )}
    </span>
  );
}

// ── Metric hints ───────────────────────────────────────────────────────────

const HINTS: Record<string, string> = {
  annual_return:
    '将整段时期的总收益换算为"每年平均赚多少"。例如 3 年总涨 33%，年化约 10%。数值越高越好。',
  max_drawdown:
    '回测期间账户从最高点跌至最低点的最大幅度。例如 -20% 表示最坏情况你的账户曾亏损 20%。数值越接近 0 越好。',
  sharpe_ratio:
    '每承受 1 单位风险能换来多少收益。大于 1 = 良好，大于 2 = 优秀。比较两个组合时，夏普更高的那个"性价比"更好。',
  bear_zone:
    '红色背景区间 = 沪深 300 指数低于 200 日均线（过去 200 个交易日的平均价格）的时段。这通常意味着市场整体处于下行趋势。在这些时段观察你的组合是否抗跌，有助于判断其防御能力。',
  ma200:
    '200 日均线（MA200）= 过去 200 个交易日的收盘价平均值。价格在均线上方 → 市场处于上升趋势（牛市）；低于均线 → 下降趋势（熊市）。是专业投资者判断市场大方向最常用的参考线之一。',
};

// ── Helpers ────────────────────────────────────────────────────────────────

function pct(v: number) { return `${(v * 100).toFixed(2)}%`; }
function sign(v: number) { return v >= 0 ? '+' : ''; }
function metricColor(label: string, v: number) {
  if (label === 'max_drawdown') return v > -0.1 ? COLOR_UP : v > -0.25 ? COLOR_B : COLOR_DOWN;
  return v >= 0 ? COLOR_UP : COLOR_DOWN;
}

// ── MetricCard ─────────────────────────────────────────────────────────────

function MetricCard({ label, a, b }: { label: string; a: number; b?: number }) {
  const labels: Record<string, string> = {
    annual_return: '年化收益率',
    max_drawdown: '最大回撤',
    sharpe_ratio: '夏普比率',
  };
  const isRatio = label === 'sharpe_ratio';
  const fmt = (v: number) => isRatio ? v.toFixed(2) : `${sign(v)}${pct(v)}`;

  return (
    <div style={{
      background: 'var(--bg-primary)', border: '1px solid var(--border-color)',
      borderRadius: 12, padding: '14px 18px', flex: 1, minWidth: 130,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>
        {labels[label]}
        <Hint text={HINTS[label]} />
      </div>
      <div style={{ display: 'flex', gap: 16, alignItems: 'baseline' }}>
        <span style={{ fontSize: 20, fontWeight: 700, color: metricColor(label, a) }}>
          {fmt(a)}
        </span>
        {b !== undefined && (
          <span style={{ fontSize: 16, fontWeight: 600, color: metricColor(label, b), opacity: 0.85 }}>
            {fmt(b)}
          </span>
        )}
      </div>
      {b !== undefined && (
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
          <span style={{ color: COLOR_A }}>■</span> 组合A &nbsp;
          <span style={{ color: COLOR_B }}>■</span> 组合B
        </div>
      )}
    </div>
  );
}

// ── WeightEditor ───────────────────────────────────────────────────────────

function WeightEditor({
  assets, weights, onChange,
}: {
  assets: Asset[];
  weights: Record<string, number>;
  onChange: (w: Record<string, number>) => void;
}) {
  const total = Object.values(weights).reduce((s, v) => s + v, 0);
  const valid = Math.abs(total - 1) < 0.005;

  const set = (sym: string, val: number) =>
    onChange({ ...weights, [sym]: Math.max(0, Math.min(1, val)) });

  return (
    <div>
      {assets.map(a => {
        const w = weights[a.symbol] ?? 0;
        return (
          <div key={a.symbol} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <div style={{
              width: 10, height: 10, borderRadius: '50%', flexShrink: 0,
              background: ASSET_COLORS[a.symbol],
            }} />
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', width: 88, flexShrink: 0 }}>
              {a.name}
            </div>
            <input
              type="range" min={0} max={100} step={5}
              value={Math.round(w * 100)}
              onChange={e => set(a.symbol, Number(e.target.value) / 100)}
              style={{ flex: 1, accentColor: ASSET_COLORS[a.symbol] }}
            />
            <div style={{
              fontSize: 13, fontWeight: 600, width: 40, textAlign: 'right',
              color: w > 0 ? 'var(--text-primary)' : 'var(--text-muted)',
            }}>
              {Math.round(w * 100)}%
            </div>
          </div>
        );
      })}
      <div style={{
        fontSize: 12, textAlign: 'right', marginTop: 4,
        color: valid ? COLOR_UP : COLOR_DOWN, fontWeight: 600,
      }}>
        合计：{Math.round(total * 100)}% {valid ? '✓' : '（需调整至 100%）'}
      </div>
    </div>
  );
}

// ── PortfolioPanel ─────────────────────────────────────────────────────────

type PConfig = { preset: string | null; weights: Record<string, number>; customMode: boolean };

function PortfolioPanel({
  label, color, assets, presets, config, onChange,
}: {
  label: string; color: string;
  assets: Asset[]; presets: Preset[];
  config: PConfig; onChange: (c: PConfig) => void;
}) {
  const [showDesc, setShowDesc] = useState(false);
  const selectedPreset = presets.find(p => p.id === config.preset);

  const applyPreset = (id: string) => {
    const p = presets.find(x => x.id === id);
    if (p) onChange({ preset: id, weights: { ...EMPTY_WEIGHTS(), ...p.weights }, customMode: false });
  };

  return (
    <div style={{
      background: 'var(--bg-primary)', border: `1px solid ${color}33`,
      borderRadius: 14, padding: 20, flex: 1, minWidth: 300,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <div style={{ width: 12, height: 12, borderRadius: 3, background: color }} />
        <span style={{ fontSize: 14, fontWeight: 700 }}>{label}</span>
      </div>

      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>预设场景</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {presets.map(p => (
            <button key={p.id} onClick={() => applyPreset(p.id)} style={{
              padding: '4px 10px', borderRadius: 8, fontSize: 12,
              border: `1px solid ${config.preset === p.id ? color : 'var(--border-color)'}`,
              background: config.preset === p.id ? `${color}18` : 'var(--bg-secondary)',
              color: config.preset === p.id ? color : 'var(--text-secondary)',
              cursor: 'pointer', fontWeight: config.preset === p.id ? 600 : 400,
            }}>
              {p.name}
            </button>
          ))}
          <button
            onClick={() => onChange({ ...config, preset: null, customMode: true })}
            style={{
              padding: '4px 10px', borderRadius: 8, fontSize: 12,
              border: `1px solid ${config.customMode ? color : 'var(--border-color)'}`,
              background: config.customMode ? `${color}18` : 'var(--bg-secondary)',
              color: config.customMode ? color : 'var(--text-secondary)',
              cursor: 'pointer', fontWeight: config.customMode ? 600 : 400,
            }}
          >
            自定义
          </button>
        </div>
      </div>

      {selectedPreset && !config.customMode && (
        <div style={{ marginBottom: 12 }}>
          <button
            onClick={() => setShowDesc(v => !v)}
            style={{
              display: 'flex', alignItems: 'center', gap: 4,
              background: 'none', border: 'none', cursor: 'pointer',
              fontSize: 11, color: 'var(--text-muted)', padding: 0,
            }}
          >
            <Info size={12} />场景说明
            {showDesc ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
          {showDesc && (
            <div style={{
              marginTop: 6, padding: '8px 10px', borderRadius: 8,
              background: 'var(--bg-secondary)', fontSize: 12,
              color: 'var(--text-secondary)', lineHeight: 1.6,
            }}>
              {selectedPreset.description}
            </div>
          )}
        </div>
      )}

      <WeightEditor assets={assets} weights={config.weights} onChange={w => onChange({ ...config, weights: w })} />
    </div>
  );
}

// ── NavChart ───────────────────────────────────────────────────────────────

function NavChart({
  resultA, resultB, bearPeriods, labelA, labelB, hasB,
}: {
  resultA: PortfolioResult | null;
  resultB: PortfolioResult | null;
  bearPeriods: BearPeriod[];
  labelA: string;
  labelB: string;
  hasB: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesARef = useRef<ISeriesApi<'Line'> | null>(null);
  const seriesBRef = useRef<ISeriesApi<'Line'> | null>(null);
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const bearRef = useRef<BearPeriod[]>([]);

  const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

  // Keep bear periods in a ref so the subscription callback stays stable
  useEffect(() => { bearRef.current = bearPeriods; }, [bearPeriods]);

  const drawShading = useCallback(() => {
    const overlay = overlayRef.current;
    const chart = chartRef.current;
    const container = containerRef.current;
    if (!overlay || !chart || !container) return;

    overlay.innerHTML = '';
    const ts = chart.timeScale();
    const W = container.clientWidth;

    bearRef.current.forEach(({ start, end }) => {
      const x1raw = ts.timeToCoordinate(start as Time);
      const x2raw = ts.timeToCoordinate(end as Time);

      // Skip if completely outside the visible area
      if (x1raw === null && x2raw === null) return;

      const x1 = Math.max(0, x1raw ?? 0);
      const x2 = Math.min(W, x2raw ?? W);
      if (x2 <= x1) return;

      const div = document.createElement('div');
      div.style.cssText = [
        `position:absolute`,
        `left:${x1}px`,
        `width:${x2 - x1}px`,
        `top:0`,
        `bottom:28px`,            // leave room for time axis
        `background:rgba(239,68,68,0.09)`,
        `border-left:1px solid rgba(239,68,68,0.18)`,
        `border-right:1px solid rgba(239,68,68,0.18)`,
      ].join(';');
      overlay.appendChild(div);
    });
  }, []);

  // Create chart once
  useEffect(() => {
    if (!containerRef.current) return;
    containerRef.current.style.position = 'relative';

    const chart = createChart(containerRef.current, {
      height: 340,
      layout: {
        background: { color: 'transparent' },
        textColor: isDark ? '#94a3b8' : '#64748b',
      },
      grid: {
        vertLines: { color: isDark ? '#1e293b' : '#f1f5f9' },
        horzLines: { color: isDark ? '#1e293b' : '#f1f5f9' },
      },
      rightPriceScale: { borderColor: isDark ? '#334155' : '#e2e8f0' },
      timeScale: { borderColor: isDark ? '#334155' : '#e2e8f0', timeVisible: true },
    });
    chartRef.current = chart;

    seriesARef.current = chart.addSeries(LineSeries, {
      color: COLOR_A, lineWidth: 2, title: labelA,
    });
    seriesBRef.current = chart.addSeries(LineSeries, {
      color: COLOR_B, lineWidth: 2, title: labelB, lineStyle: 1,
    });

    // Overlay goes on top of the canvas
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:absolute;inset:0;pointer-events:none;overflow:hidden;z-index:2;';
    containerRef.current.appendChild(overlay);
    overlayRef.current = overlay;

    chart.timeScale().subscribeVisibleLogicalRangeChange(drawShading);

    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(drawShading);
      overlay.remove();
      chart.remove();
      chartRef.current = null;
    };
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  // Update data + shading whenever results or bear periods change
  useEffect(() => {
    const seriesA = seriesARef.current;
    const seriesB = seriesBRef.current;
    const chart = chartRef.current;
    if (!seriesA || !seriesB || !chart) return;

    const toLD = (pts: NavPoint[]): LineData[] =>
      pts.map(p => ({ time: p.date as Time, value: p.nav }));

    seriesA.setData(resultA?.nav_curve?.length ? toLD(resultA.nav_curve) : []);
    seriesB.setData(resultB?.nav_curve?.length ? toLD(resultB.nav_curve) : []);

    if (resultA?.nav_curve?.length || resultB?.nav_curve?.length) {
      chart.timeScale().fitContent();
    }

    // Redraw shading after chart has rendered (fitContent changes the visible range)
    const t = setTimeout(drawShading, 80);
    return () => clearTimeout(t);
  }, [resultA, resultB, bearPeriods, drawShading]);

  return <div ref={containerRef} style={{ width: '100%' }} />;
}

// ── Helpers ────────────────────────────────────────────────────────────────

const EMPTY_WEIGHTS = (): Record<string, number> =>
  ({ '510300': 0, '510050': 0, '510500': 0, '159915': 0, '513100': 0, '511010': 0, '518880': 0, CASH: 0 });

const defaultConfig = (presets: Preset[], id: string): PConfig => {
  const p = presets.find(x => x.id === id);
  return p
    ? { preset: id, weights: { ...EMPTY_WEIGHTS(), ...p.weights }, customMode: false }
    : { preset: null, weights: EMPTY_WEIGHTS(), customMode: true };
};

// ── Main page ───────────────────────────────────────────────────────────────

export default function Backtest() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [priceStatus, setPriceStatus] = useState<PriceStatus>({});
  const [fetching, setFetching] = useState(false);
  const [running, setRunning] = useState(false);

  const [configA, setConfigA] = useState<PConfig>({ preset: null, weights: EMPTY_WEIGHTS(), customMode: false });
  const [configB, setConfigB] = useState<PConfig>({ preset: null, weights: EMPTY_WEIGHTS(), customMode: false });
  const [enableB, setEnableB] = useState(false);
  const [rebalance, setRebalance] = useState<'1M' | '1Q'>('1Q');
  const [startDate, setStartDate] = useState('2013-01-01');

  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [error, setError] = useState('');

  const hasData = Object.entries(priceStatus).some(([sym, v]) => sym !== 'CASH' && v.cached_rows > 0);

  const loadMeta = useCallback(async () => {
    const token = localStorage.getItem('token');
    const h = { Authorization: `Bearer ${token}` };
    const [a, p, s] = await Promise.all([
      fetch(`${API}/backtest/assets`, { headers: h }).then(r => r.json()),
      fetch(`${API}/backtest/presets`, { headers: h }).then(r => r.json()),
      fetch(`${API}/backtest/price-status`, { headers: h }).then(r => r.json()),
    ]);
    setAssets(a.assets ?? []);
    setPresets(p.presets ?? []);
    setPriceStatus(s);
    if (p.presets?.length) {
      setConfigA(defaultConfig(p.presets, 'balanced'));
      setConfigB(defaultConfig(p.presets, 'all_weather'));
    }
  }, []);

  useEffect(() => { loadMeta(); }, [loadMeta]);

  const handleFetchPrices = async () => {
    setFetching(true);
    const token = localStorage.getItem('token');
    await fetch(`${API}/backtest/fetch-prices`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    let checks = 0;
    const poll = setInterval(async () => {
      checks++;
      const s = await fetch(`${API}/backtest/price-status`, {
        headers: { Authorization: `Bearer ${token}` },
      }).then(r => r.json());
      setPriceStatus(s);
      const done = Object.values(s as PriceStatus).every(v => v.cached_rows > 100);
      if (done || checks > 30) { clearInterval(poll); setFetching(false); }
    }, 10000);
  };

  const handleRun = async () => {
    setError('');
    setRunning(true);
    try {
      const token = localStorage.getItem('token');
      const body = {
        portfolio_a: { weights: configA.weights, label: '组合A' },
        portfolio_b: enableB ? { weights: configB.weights, label: '组合B' } : null,
        rebalance,
        start_date: startDate,
        end_date: '2026-12-31',
      };
      const res = await fetch(`${API}/backtest/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      });
      if (!res.ok) { setError((await res.json()).detail ?? '回测失败'); return; }
      setResult(await res.json());
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  };

  const weightsValid = (w: Record<string, number>) =>
    Math.abs(Object.values(w).reduce((s, v) => s + v, 0) - 1) < 0.005;

  const canRun = hasData && weightsValid(configA.weights) && (!enableB || weightsValid(configB.weights));

  return (
    <div style={{ color: 'var(--text-primary)' }}>

      {/* ── Header ── */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>大类资产组合回测</h1>
        <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '4px 0 0' }}>
          中国资产 · 定期再平衡 · 历史净值对比
        </p>
      </div>

      {/* ── Data status ── */}
      <div style={{
        background: 'var(--bg-primary)', border: '1px solid var(--border-color)',
        borderRadius: 12, padding: '14px 18px', marginBottom: 20,
        display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap',
      }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)', flexShrink: 0 }}>
          价格数据：
        </span>
        {Object.entries(priceStatus).map(([sym, info]) => (
          <div key={sym} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <div style={{
              width: 8, height: 8, borderRadius: '50%',
              background: info.cached_rows > 100 ? COLOR_UP : COLOR_DOWN,
            }} />
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
              {sym} <span style={{ color: 'var(--text-muted)' }}>({info.cached_rows} 条)</span>
            </span>
          </div>
        ))}
        <div style={{ flex: 1 }} />
        {!hasData && (
          <span style={{ fontSize: 12, color: COLOR_DOWN }}>⚠️ 尚无价格数据，请先抓取</span>
        )}
        <button
          onClick={handleFetchPrices}
          disabled={fetching}
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '6px 14px', borderRadius: 8, fontSize: 13,
            background: fetching ? 'var(--bg-secondary)' : '#6366f118',
            border: '1px solid #6366f144', color: '#6366f1',
            cursor: fetching ? 'not-allowed' : 'pointer', fontWeight: 600,
          }}
        >
          <RefreshCw size={14} />
          {fetching ? '抓取中…' : '抓取历史净值'}
        </button>
      </div>

      {/* ── Configuration ── */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 16 }}>
        <PortfolioPanel label="组合 A" color={COLOR_A} assets={assets} presets={presets} config={configA} onChange={setConfigA} />
        {enableB && (
          <PortfolioPanel label="组合 B" color={COLOR_B} assets={assets} presets={presets} config={configB} onChange={setConfigB} />
        )}
      </div>

      {/* ── Controls row ── */}
      <div style={{
        background: 'var(--bg-primary)', border: '1px solid var(--border-color)',
        borderRadius: 12, padding: '14px 18px', marginBottom: 20,
        display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap',
      }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13 }}>
          <input type="checkbox" checked={enableB} onChange={e => setEnableB(e.target.checked)}
            style={{ accentColor: COLOR_B, width: 16, height: 16 }} />
          <span style={{ color: 'var(--text-secondary)' }}>启用组合B对比</span>
        </label>

        <div style={{ width: 1, height: 20, background: 'var(--border-color)' }} />

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>调仓频率</span>
          {(['1Q', '1M'] as const).map(f => (
            <button key={f} onClick={() => setRebalance(f)} style={{
              padding: '4px 12px', borderRadius: 8, fontSize: 13,
              border: `1px solid ${rebalance === f ? '#6366f1' : 'var(--border-color)'}`,
              background: rebalance === f ? '#6366f118' : 'var(--bg-secondary)',
              color: rebalance === f ? '#6366f1' : 'var(--text-secondary)',
              cursor: 'pointer', fontWeight: rebalance === f ? 600 : 400,
            }}>
              {f === '1Q' ? '季度' : '月度'}
            </button>
          ))}
        </div>

        <div style={{ width: 1, height: 20, background: 'var(--border-color)' }} />

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>起始日期</span>
          <select
            value={startDate}
            onChange={e => setStartDate(e.target.value)}
            style={{
              padding: '4px 10px', borderRadius: 8, fontSize: 13,
              border: '1px solid var(--border-color)',
              background: 'var(--bg-secondary)', color: 'var(--text-primary)', cursor: 'pointer',
            }}
          >
            {['2013-01-01', '2015-01-01', '2018-01-01', '2020-01-01'].map(d => (
              <option key={d} value={d}>{d.slice(0, 4)} 年起</option>
            ))}
          </select>
        </div>

        <div style={{ flex: 1 }} />

        <button
          onClick={handleRun}
          disabled={!canRun || running}
          style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '8px 20px', borderRadius: 10, fontSize: 14, fontWeight: 700,
            background: canRun && !running
              ? 'linear-gradient(135deg, #6366f1, #8b5cf6)'
              : 'var(--bg-secondary)',
            color: canRun && !running ? 'white' : 'var(--text-muted)',
            border: 'none', cursor: canRun && !running ? 'pointer' : 'not-allowed',
            boxShadow: canRun && !running ? '0 4px 14px #6366f133' : 'none',
          }}
        >
          <Play size={15} fill="currentColor" />
          {running ? '计算中…' : '运行回测'}
        </button>
      </div>

      {error && (
        <div style={{
          padding: '10px 16px', borderRadius: 10, marginBottom: 16,
          background: '#ef444418', border: '1px solid #ef444433',
          fontSize: 13, color: COLOR_DOWN,
        }}>
          {error}
        </div>
      )}

      {/* ── Results ── */}
      {result && (
        <div>
          {/* Metric cards */}
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 20 }}>
            {(['annual_return', 'max_drawdown', 'sharpe_ratio'] as const).map(k => (
              <MetricCard
                key={k} label={k}
                a={result.portfolio_a.metrics[k]}
                b={result.portfolio_b ? result.portfolio_b.metrics[k] : undefined}
              />
            ))}
          </div>

          {/* NAV Chart */}
          <div style={{
            background: 'var(--bg-primary)', border: '1px solid var(--border-color)',
            borderRadius: 14, padding: '20px 20px 14px',
          }}>
            {/* Chart header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
              <span style={{ fontSize: 14, fontWeight: 700 }}>累计净值曲线</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: 12, color: 'var(--text-muted)', flexWrap: 'wrap' }}>
                <span><span style={{ color: COLOR_A }}>——</span> 组合A</span>
                {result.portfolio_b && <span><span style={{ color: COLOR_B }}>- - -</span> 组合B</span>}
                <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{
                    display: 'inline-block', width: 14, height: 10,
                    background: 'rgba(239,68,68,0.2)',
                    border: '1px solid rgba(239,68,68,0.4)',
                    borderRadius: 2,
                  }} />
                  市场下行区间
                  <Hint text={HINTS.bear_zone} />
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                  基于沪深300 MA200
                  <Hint text={HINTS.ma200} />
                </span>
              </div>
            </div>

            <NavChart
              resultA={result.portfolio_a}
              resultB={result.portfolio_b}
              bearPeriods={result.bear_periods}
              labelA="组合A"
              labelB="组合B"
              hasB={!!result.portfolio_b}
            />

            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 10 }}>
              调仓方式：{result.rebalance === '1Q' ? '季度末' : '月末'}再平衡 ·
              起始：{result.start_date} ·
              数据来源：AkShare（天天基金）·
              红色背景 = 沪深300在200日均线下方
            </div>
          </div>

          {/* Weight breakdown */}
          <div style={{ display: 'flex', gap: 16, marginTop: 16, flexWrap: 'wrap' }}>
            {[
              { label: '组合A', color: COLOR_A, weights: configA.weights },
              ...(result.portfolio_b ? [{ label: '组合B', color: COLOR_B, weights: configB.weights }] : []),
            ].map(({ label, color, weights }) => (
              <div key={label} style={{
                background: 'var(--bg-primary)', border: `1px solid ${color}33`,
                borderRadius: 12, padding: '14px 18px', flex: 1, minWidth: 220,
              }}>
                <div style={{ fontSize: 13, fontWeight: 600, color, marginBottom: 10 }}>{label} 权重</div>
                {assets.map(a => {
                  const w = weights[a.symbol] ?? 0;
                  if (!w) return null;
                  return (
                    <div key={a.symbol} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                      <div style={{ width: 8, height: 8, borderRadius: '50%', background: ASSET_COLORS[a.symbol], flexShrink: 0 }} />
                      <span style={{ fontSize: 12, color: 'var(--text-secondary)', flex: 1 }}>{a.name}</span>
                      <div style={{
                        height: 6, borderRadius: 3, background: ASSET_COLORS[a.symbol],
                        width: `${Math.round(w * 100)}%`, minWidth: 4,
                      }} />
                      <span style={{ fontSize: 12, fontWeight: 600, width: 36, textAlign: 'right' }}>
                        {Math.round(w * 100)}%
                      </span>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Empty state */}
      {!result && !running && (
        <div style={{ textAlign: 'center', padding: '60px 20px', color: 'var(--text-muted)', fontSize: 14 }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>📊</div>
          {hasData
            ? '配置好组合权重后，点击「运行回测」查看历史表现'
            : '请先点击「抓取历史净值」加载价格数据（首次约 3–5 分钟）'}
        </div>
      )}
    </div>
  );
}
