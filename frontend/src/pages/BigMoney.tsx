import { useEffect, useRef, useState, useCallback } from 'react';
import axios from 'axios';
import { Activity, Database, Info, RefreshCw, ShieldCheck, TrendingDown, TrendingUp } from 'lucide-react';
import { createChart, ColorType, HistogramSeries, LineSeries, LineType, createSeriesMarkers } from 'lightweight-charts';

const API = import.meta.env.VITE_API_URL || '';
const POST_OPTS = { timeout: 8000 };

// ── Types ────────────────────────────────────────────────────────────────────

interface NorthboundRow {
  date: string;
  net_buy_amount: number | null;
  hs300_close: number | null;
  hs300_change_pct: number | null;
}
interface HuijinEvent { date: string; label: string; }
interface NorthboundResp { data: NorthboundRow[]; huijin_events: HuijinEvent[]; message?: string; }
interface EtfRow { date: string; total_share: number | null; name: string; }
interface EtfResp { symbols: string[]; data: Record<string, EtfRow[]>; huijin_events: HuijinEvent[]; message?: string; }
interface TodayResp {
  northbound: { date: string | null; channels: { channel: string; net_buy_amount: number | null; hs300_change_pct: number | null }[] };
  etf_shares: { date: string | null; items: { symbol: string; name: string; total_share: number | null }[] };
}
interface IntradayRow { time: string; sh_hk: number | null; sz_hk: number | null; total: number | null; }
interface IntradayResp { date: string | null; data: IntradayRow[]; source_broken?: boolean; message?: string; }
interface RefreshDetail {
  key: string;
  label: string;
  status: 'success' | 'warning' | 'error';
  latest_date: string | null;
  message: string;
  signal_label?: string | null;
  watch_label?: string | null;
}
interface RefreshResp {
  status: 'success' | 'partial' | 'error';
  message: string;
  target_date: string;
  latest_dates: Record<string, string | null>;
  details: RefreshDetail[];
}
interface SignalEtfEvidence {
  symbol: string;
  name: string;
  total_share: number | null;
  previous_share?: number | null;
  delta_share: number | null;
  nav?: number | null;
  estimated_amount: number | null;
  status: string;
}
interface BigMoneySignalRow {
  date: string;
  signal: 'accumulate' | 'reduce' | 'support_fading' | 'neutral' | string;
  signal_label: string;
  watch_signal: string;
  watch_label: string;
  confidence: 'high' | 'medium' | 'low' | string;
  basket_delta_share: number | null;
  estimated_amount: number | null;
  z_score: number | null;
  market_daily_change: number | null;
  market_drawdown_20: number | null;
  positive_etf_count: number;
  negative_etf_count: number;
  data_quality: string;
  evidence?: {
    core_etfs?: SignalEtfEvidence[];
    explanation?: string;
    baseline_count?: number;
  };
}
interface BigMoneySignalResp {
  data: BigMoneySignalRow[];
  latest: BigMoneySignalRow | null;
  message?: string;
}
interface Bei50RiskRow {
  date: string;
  bei50_close: number | null;
  hs300_close: number | null;
  bei50_return_1d: number | null;
  hs300_return_1d: number | null;
  bei50_return_5d: number | null;
  hs300_return_5d: number | null;
  relative_return_5d: number | null;
  volume_z_score: number | null;
  drawdown_20d: number | null;
  signal: string;
  label: string;
  summary: string;
}
interface Bei50RiskResp {
  data: Bei50RiskRow[];
  latest: Bei50RiskRow | null;
  message?: string;
}

// ── Time range ───────────────────────────────────────────────────────────────

type Range = '1M' | '3M' | '1Y' | '3Y' | 'ALL';
const RANGES: Range[] = ['1M', '3M', '1Y', '3Y', 'ALL'];
const RANGE_LABEL: Record<Range, string> = { '1M': '1个月', '3M': '3个月', '1Y': '1年', '3Y': '3年', 'ALL': '全部' };

function filterByRange<T extends { date: string }>(data: T[], range: Range): T[] {
  if (range === 'ALL') return data;
  const now = new Date();
  const cutoff = new Date(now);
  if (range === '1M') cutoff.setMonth(now.getMonth() - 1);
  else if (range === '3M') cutoff.setMonth(now.getMonth() - 3);
  else if (range === '1Y') cutoff.setFullYear(now.getFullYear() - 1);
  else if (range === '3Y') cutoff.setFullYear(now.getFullYear() - 3);
  const cutoffStr = cutoff.toISOString().slice(0, 10);
  return data.filter(r => r.date >= cutoffStr);
}

function RangeButtons({ value, onChange }: { value: Range; onChange: (r: Range) => void }) {
  return (
    <div style={{ display: 'flex', gap: 4 }}>
      {RANGES.map(r => (
        <button
          key={r}
          onClick={() => onChange(r)}
          style={{
            padding: '4px 10px', borderRadius: 6, fontSize: 11, cursor: 'pointer',
            border: `1px solid ${value === r ? '#6366f1' : 'var(--border-color)'}`,
            background: value === r ? 'rgba(99,102,241,0.12)' : 'transparent',
            color: value === r ? '#6366f1' : 'var(--text-muted)',
            fontWeight: value === r ? 600 : 400,
            transition: 'all 0.15s',
          }}
        >
          {RANGE_LABEL[r]}
        </button>
      ))}
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const fmtYi = (v: number | null) => v === null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}亿`;
const fmtYiFen = (v: number | null) => v === null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}亿份`;
const fmtPct = (v: number | null) => v === null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
const fmtSigma = (v: number | null) => v === null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}σ`;
const flowColor = (v: number | null) => v === null ? '#6b7280' : v > 0 ? '#ef4444' : '#22c55e';
const signalColor = (signal: string, watch?: string) => {
  if (signal === 'accumulate' || watch === 'watch_accumulate') return '#ef4444';
  if (signal === 'reduce' || signal === 'support_fading' || watch === 'watch_reduce') return '#22c55e';
  return '#9ca3af';
};
const signalBg = (signal: string, watch?: string) => {
  if (signal === 'accumulate' || watch === 'watch_accumulate') return 'rgba(239,68,68,0.10)';
  if (signal === 'reduce' || signal === 'support_fading' || watch === 'watch_reduce') return 'rgba(34,197,94,0.10)';
  return 'rgba(107,114,128,0.10)';
};
const confidenceLabel = (v: string) => v === 'high' ? '高' : v === 'medium' ? '中' : '低';
const dataQualityLabel = (v: string) => ({
  complete: '数据完整',
  partial: '数据不完整',
  insufficient_baseline: '基线不足',
  partial_insufficient_baseline: '数据/基线不足',
  unknown: '未知',
}[v] || v);
const refreshStatusStyle = (status: RefreshResp['status']): React.CSSProperties => {
  if (status === 'success') return { background: 'rgba(16,185,129,0.10)', border: '1px solid rgba(16,185,129,0.28)', color: '#10b981' };
  if (status === 'error') return { background: 'rgba(239,68,68,0.10)', border: '1px solid rgba(239,68,68,0.30)', color: '#ef4444' };
  return { background: 'rgba(245,158,11,0.10)', border: '1px solid rgba(245,158,11,0.30)', color: '#f59e0b' };
};

const ETF_COLORS: Record<string, string> = {
  '510050': '#6366f1', '510300': '#f59e0b', '510500': '#06b6d4',
};

const ETF_GUIDE: Record<string, {
  shortName: string;
  index: string;
  exposure: string;
  role: string;
  increaseAction: string;
  decreaseAction: string;
}> = {
  '510050': {
    shortName: '上证50ETF',
    index: '上证50',
    exposure: '超大盘蓝筹，金融、央国企和沪市权重更集中',
    role: '观察权重股是否被托住；它强不代表全市场都强。',
    increaseAction: '偏向稳住权重股，可提高上证50/红利蓝筹关注，谨慎看作大盘托底。',
    decreaseAction: '权重托底减弱，若大盘同步走弱，降低追高和重仓蓝筹暴露。',
  },
  '510300': {
    shortName: '沪深300ETF',
    index: '沪深300',
    exposure: 'A股核心大盘，跨沪深两市，最接近“大盘中枢”',
    role: '本模块的主参考。510300 放量增份额通常比单只 ETF 更能说明托底大盘。',
    increaseAction: '大盘核心托底信号增强，可优先考虑沪深300/宽基仓位的持有或低吸观察。',
    decreaseAction: '核心宽基支撑变弱，若连续减少或异常度为负，偏向减仓/降低贝塔。',
  },
  '510500': {
    shortName: '中证500ETF',
    index: '中证500',
    exposure: '中盘股和二线成长，弹性高于上证50/沪深300',
    role: '观察托底是否从权重扩散到中盘。它单独增加更像风险偏好修复。',
    increaseAction: '中盘修复概率提升，可观察中证500/成长板块，但需确认 510300 是否同步改善。',
    decreaseAction: '中盘风险偏好下降，成长/中盘仓位要更谨慎，避免只看大盘权重掩盖分化。',
  },
};

// ── Chart components ──────────────────────────────────────────────────────────

const DATA_GAP_DATE = '2024-08-16';  // East Money API stopped providing data after this date

function NorthboundChart({ data, huijinEvents }: { data: NorthboundRow[]; huijinEvents: HuijinEvent[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const hasGap = data.some(r => r.date <= DATA_GAP_DATE);

  useEffect(() => {
    if (!containerRef.current || data.length === 0) return;
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth, height: 260,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#9ca3af' },
      grid: { vertLines: { color: 'rgba(255,255,255,0.05)' }, horzLines: { color: 'rgba(255,255,255,0.05)' } },
      timeScale: { borderColor: 'rgba(255,255,255,0.1)' },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
      crosshair: { mode: 1 },
    });
    const series = chart.addSeries(LineSeries, {
      color: '#6366f1', lineWidth: 2, lineType: LineType.Curved,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 }, title: '净买额(亿)',
    });
    series.setData(
      data.filter(r => r.net_buy_amount !== null)
          .map(r => ({ time: r.date as any, value: r.net_buy_amount as number }))
    );
    // Zero baseline
    series.createPriceLine({ price: 0, color: 'rgba(255,255,255,0.15)', lineWidth: 1, lineStyle: 0, axisLabelVisible: false, title: '' });

    // Data gap marker at 2024-08-16
    let markers: ReturnType<typeof createSeriesMarkers> | null = null;
    if (hasGap) {
      markers = createSeriesMarkers(series, [
        {
          time: DATA_GAP_DATE as any,
          position: 'aboveBar',
          color: '#f59e0b',
          shape: 'arrowDown',
          text: '数据断档',
          size: 1,
        },
      ]);
    }

    chart.timeScale().fitContent();
    const ro = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    ro.observe(containerRef.current);
    return () => { markers?.detach(); chart.remove(); ro.disconnect(); };
  }, [data, huijinEvents, hasGap]);

  if (data.length === 0) return <EmptyChart text="该时间段暂无数据" />;
  return <div ref={containerRef} style={{ width: '100%' }} />;
}

function EtfShareChart({ symbols, etfData, range }: {
  symbols: string[]; etfData: Record<string, EtfRow[]>; range: Range;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current || symbols.length === 0) return;
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth, height: 260,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#9ca3af' },
      grid: { vertLines: { color: 'rgba(255,255,255,0.05)' }, horzLines: { color: 'rgba(255,255,255,0.05)' } },
      timeScale: { borderColor: 'rgba(255,255,255,0.1)' },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
      crosshair: { mode: 1 },
    });
    symbols.forEach(sym => {
      const rows = filterByRange(etfData[sym] || [], range);
      const series = chart.addSeries(LineSeries, {
        color: ETF_COLORS[sym] || '#9ca3af', lineWidth: 2, lineType: LineType.Curved,
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 }, title: `${sym}(亿份)`,
      });
      series.setData(
        rows.filter(r => r.total_share !== null).map(r => ({ time: r.date as any, value: r.total_share as number }))
      );
    });
    chart.timeScale().fitContent();
    const ro = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    ro.observe(containerRef.current);
    return () => { chart.remove(); ro.disconnect(); };
  }, [symbols, etfData, range]);

  if (symbols.length === 0) return <EmptyChart text="暂无 ETF 份额数据" />;
  return <div ref={containerRef} style={{ width: '100%' }} />;
}

function SignalEvidenceChart({ data, range }: { data: BigMoneySignalRow[]; range: Range }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const rows = filterByRange(data, range);

  useEffect(() => {
    if (!containerRef.current || rows.length === 0) return;
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth, height: 260,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#9ca3af' },
      grid: { vertLines: { color: 'rgba(255,255,255,0.05)' }, horzLines: { color: 'rgba(255,255,255,0.05)' } },
      timeScale: { borderColor: 'rgba(255,255,255,0.1)' },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
      crosshair: { mode: 1 },
    });
    const deltaSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      title: '篮子份额变化(亿份)',
    });
    deltaSeries.setData(rows
      .filter(r => r.basket_delta_share !== null)
      .map(r => ({
        time: r.date as any,
        value: r.basket_delta_share as number,
        color: (r.basket_delta_share ?? 0) >= 0 ? 'rgba(239,68,68,0.65)' : 'rgba(34,197,94,0.65)',
      })));
    deltaSeries.createPriceLine({ price: 0, color: 'rgba(255,255,255,0.18)', lineWidth: 1, lineStyle: 0, axisLabelVisible: false, title: '' });

    const zSeries = chart.addSeries(LineSeries, {
      color: '#f59e0b', lineWidth: 2, lineType: LineType.Curved,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      title: '20日异常度(σ)',
    });
    zSeries.setData(rows
      .filter(r => r.z_score !== null)
      .map(r => ({ time: r.date as any, value: r.z_score as number })));
    zSeries.createPriceLine({ price: 2.5, color: 'rgba(239,68,68,0.35)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '+2.5σ' });
    zSeries.createPriceLine({ price: -2.5, color: 'rgba(34,197,94,0.35)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '-2.5σ' });

    chart.timeScale().fitContent();
    const ro = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    ro.observe(containerRef.current);
    return () => { chart.remove(); ro.disconnect(); };
  }, [rows]);

  if (rows.length === 0) return <EmptyChart text="暂无托底信号数据" />;
  return <div ref={containerRef} style={{ width: '100%' }} />;
}

function Bei50RiskChart({ data, range }: { data: Bei50RiskRow[]; range: Range }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const rows = filterByRange(data, range).filter(r => r.bei50_close !== null && r.hs300_close !== null);

  useEffect(() => {
    if (!containerRef.current || rows.length === 0) return;
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth, height: 240,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#9ca3af' },
      grid: { vertLines: { color: 'rgba(255,255,255,0.05)' }, horzLines: { color: 'rgba(255,255,255,0.05)' } },
      timeScale: { borderColor: 'rgba(255,255,255,0.1)' },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
      crosshair: { mode: 1 },
    });
    const firstBei = rows[0].bei50_close || 1;
    const firstHs = rows[0].hs300_close || 1;
    const beiSeries = chart.addSeries(LineSeries, {
      color: '#ec4899', lineWidth: 2, lineType: LineType.Curved,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 }, title: '北证50累计涨跌(%)',
    });
    const hsSeries = chart.addSeries(LineSeries, {
      color: '#6366f1', lineWidth: 2, lineType: LineType.Curved,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 }, title: '沪深300累计涨跌(%)',
    });
    beiSeries.setData(rows.map(r => ({
      time: r.date as any,
      value: ((r.bei50_close || firstBei) / firstBei - 1) * 100,
    })));
    hsSeries.setData(rows.map(r => ({
      time: r.date as any,
      value: ((r.hs300_close || firstHs) / firstHs - 1) * 100,
    })));
    beiSeries.createPriceLine({ price: 0, color: 'rgba(255,255,255,0.16)', lineWidth: 1, lineStyle: 0, axisLabelVisible: false, title: '' });

    chart.timeScale().fitContent();
    const ro = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    ro.observe(containerRef.current);
    return () => { chart.remove(); ro.disconnect(); };
  }, [rows]);

  if (rows.length === 0) return <EmptyChart text="暂无北证50风险偏好数据" />;
  return <div ref={containerRef} style={{ width: '100%' }} />;
}

function IntradayChart({ data, date, sourceBroken, message }: {
  data: IntradayRow[]; date: string | null; sourceBroken?: boolean; message?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current || data.length === 0) return;
    const validData = data.filter(r => r.total !== null);
    if (validData.length === 0) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth, height: 200,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#9ca3af' },
      grid: { vertLines: { color: 'rgba(255,255,255,0.05)' }, horzLines: { color: 'rgba(255,255,255,0.05)' } },
      timeScale: { borderColor: 'rgba(255,255,255,0.1)', timeVisible: true, tickMarkFormatter: (_: any, __: any, locale: string) => '' },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
      crosshair: { mode: 1 },
    });

    // Use index as time since minutes aren't ISO dates
    const shSeries = chart.addSeries(LineSeries, { color: '#6366f1', lineWidth: 2, title: '沪股通' });
    const szSeries = chart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 2, title: '深股通' });
    const totalSeries = chart.addSeries(LineSeries, { color: '#10b981', lineWidth: 2, title: '北向合计' });

    // Build time series — use trading date + index as fake timestamps for display
    const baseDate = date ?? '2000-01-01';
    const toTs = (idx: number) => {
      const d = new Date(`${baseDate}T09:30:00+08:00`);
      d.setMinutes(d.getMinutes() + idx);
      return Math.floor(d.getTime() / 1000) as any;
    };

    shSeries.setData(validData.map((r, i) => ({ time: toTs(i), value: r.sh_hk ?? 0 })));
    szSeries.setData(validData.map((r, i) => ({ time: toTs(i), value: r.sz_hk ?? 0 })));
    totalSeries.setData(validData.map((r, i) => ({ time: toTs(i), value: r.total ?? 0 })));

    totalSeries.createPriceLine({ price: 0, color: 'rgba(255,255,255,0.15)', lineWidth: 1, lineStyle: 0, axisLabelVisible: false, title: '' });
    chart.timeScale().fitContent();

    const ro = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    ro.observe(containerRef.current);
    return () => { chart.remove(); ro.disconnect(); };
  }, [data, date]);

  if (sourceBroken || data.filter(r => r.total !== null && r.total !== 0).length === 0) {
    return (
      <div style={{
        height: 120, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        color: 'var(--text-muted)', fontSize: 12, gap: 6,
        border: '1px dashed var(--border-color)', borderRadius: 10,
        padding: '0 24px', textAlign: 'center',
      }}>
        <span style={{ color: '#f59e0b', fontWeight: 600 }}>数据源不可用</span>
        <span>东方财富于 2024 年 8 月更改接口结构，AkShare 分钟级北向资金数据接口目前返回全零，暂无法显示盘中走势。</span>
        {message && <span style={{ fontSize: 11, opacity: 0.7 }}>{message}</span>}
      </div>
    );
  }
  return <div ref={containerRef} style={{ width: '100%' }} />;
}

function EmptyChart({ text }: { text: string }) {
  return (
    <div style={{
      height: 260, display: 'flex', alignItems: 'center', justifyContent: 'center',
      color: 'var(--text-muted)', fontSize: 13, gap: 8,
      border: '1px dashed var(--border-color)', borderRadius: 10,
    }}>
      <Database size={16} />{text}
    </div>
  );
}

function etfActionHint(delta: number | null | undefined, guide: typeof ETF_GUIDE[string]) {
  if (delta === null || delta === undefined) return '暂无前后份额变化，先等待盘后快照补齐。';
  if (delta > 0) return guide.increaseAction;
  if (delta < 0) return guide.decreaseAction;
  return '份额基本持平，暂不作为独立加减仓依据，结合篮子合计和异常度判断。';
}

function EtfGuidePanel({ latest }: { latest: BigMoneySignalRow | null }) {
  const evidenceBySymbol = new Map((latest?.evidence?.core_etfs ?? []).map(item => [item.symbol, item]));
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
      gap: 10,
      marginBottom: 14,
    }}>
      {Object.entries(ETF_GUIDE).map(([symbol, guide]) => {
        const evidence = evidenceBySymbol.get(symbol);
        const color = ETF_COLORS[symbol] || 'var(--text-primary)';
        return (
          <div key={symbol} style={{
            background: 'var(--bg-secondary)',
            border: '1px solid var(--border-color)',
            borderRadius: 10,
            padding: '12px 14px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <span style={{ width: 8, height: 8, borderRadius: 99, background: color, flexShrink: 0 }} />
              <span style={{ fontSize: 13, fontWeight: 800, color }}>{symbol}</span>
              <span style={{ fontSize: 12, color: 'var(--text-primary)', fontWeight: 700 }}>{guide.shortName}</span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.65 }}>
              跟踪 {guide.index} · {guide.exposure}
            </div>
            <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.7 }}>
              {guide.role}
            </div>
            <div style={{
              marginTop: 9,
              padding: '8px 9px',
              borderRadius: 8,
              background: 'rgba(255,255,255,0.035)',
              color: evidence?.delta_share === undefined ? 'var(--text-muted)' : flowColor(evidence.delta_share),
              fontSize: 11,
              lineHeight: 1.65,
            }}>
              今日变化 {fmtYiFen(evidence?.delta_share ?? null)} · {etfActionHint(evidence?.delta_share, guide)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function bei50SignalColor(signal?: string) {
  if (signal === 'accumulate_watch' || signal === 'risk_on_watch') return '#ef4444';
  if (signal === 'reduce_watch') return '#22c55e';
  return '#9ca3af';
}

function bei50SignalBg(signal?: string) {
  if (signal === 'accumulate_watch' || signal === 'risk_on_watch') return 'rgba(239,68,68,0.10)';
  if (signal === 'reduce_watch') return 'rgba(34,197,94,0.10)';
  return 'rgba(107,114,128,0.10)';
}

function Bei50RiskPanel({ risk, range, onRangeChange }: {
  risk: Bei50RiskResp | null;
  range: Range;
  onRangeChange: (range: Range) => void;
}) {
  const latest = risk?.latest ?? null;
  const color = bei50SignalColor(latest?.signal);
  const actionText = latest?.signal === 'accumulate_watch'
    ? '可提高小盘/成长观察权重，但只作为辅助，不覆盖托底主信号。'
    : latest?.signal === 'reduce_watch'
      ? '降低北交所和小盘题材暴露，等待相对强弱修复。'
      : latest?.signal === 'risk_on_watch'
        ? '风险偏好在扩散，等5日绝对涨幅或连续性确认后再升级。'
        : '不单独调整仓位，继续观察北证50相对沪深300的变化。';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
        gap: 10,
      }}>
        <div style={{
          background: bei50SignalBg(latest?.signal),
          border: `1px solid ${color}44`,
          borderRadius: 10,
          padding: '13px 15px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, color, fontSize: 12, fontWeight: 800, marginBottom: 7 }}>
            {latest?.signal === 'reduce_watch' ? <TrendingDown size={15} /> : <TrendingUp size={15} />}
            北交所风险偏好
          </div>
          <div style={{ fontSize: 24, fontWeight: 850, color }}>{latest?.label ?? '暂无信号'}</div>
          <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.7 }}>
            {latest?.summary ?? '暂无北证50风险偏好数据。'} {actionText}
          </div>
        </div>
        {([
          ['北证50 1日', fmtPct(latest?.bei50_return_1d ?? null), latest?.bei50_return_1d ?? null],
          ['北证50 5日', fmtPct(latest?.bei50_return_5d ?? null), latest?.bei50_return_5d ?? null],
          ['相对沪深300', fmtPct(latest?.relative_return_5d ?? null), latest?.relative_return_5d ?? null],
          ['成交量异常', fmtSigma(latest?.volume_z_score ?? null), latest?.volume_z_score ?? null],
        ] as [string, string, number | null][]).map(([label, value, raw]) => (
          <div key={label} style={{
            background: 'var(--bg-secondary)',
            border: '1px solid var(--border-color)',
            borderRadius: 10,
            padding: '12px 13px',
          }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 5 }}>{label}</div>
            <div style={{ fontSize: 18, fontWeight: 800, color: flowColor(raw) }}>{value}</div>
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: 12, color: 'var(--text-secondary)' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}><i style={{ width: 16, height: 3, background: '#ec4899', borderRadius: 2 }} />北证50</span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}><i style={{ width: 16, height: 3, background: '#6366f1', borderRadius: 2 }} />沪深300</span>
          <span>20日回撤 {fmtPct(latest?.drawdown_20d ?? null)}</span>
        </div>
        <RangeButtons value={range} onChange={onRangeChange} />
      </div>
      <Bei50RiskChart data={risk?.data ?? []} range={range} />
      {risk?.message && (
        <div style={{ fontSize: 12, color: 'var(--text-muted)', textAlign: 'center' }}>{risk.message}</div>
      )}
    </div>
  );
}

function SectionCard({ title, subtitle, children, action }: {
  title: string; subtitle?: string; children: React.ReactNode; action?: React.ReactNode;
}) {
  return (
    <div style={{ background: 'var(--bg-primary)', border: '1px solid var(--border-color)', borderRadius: 14, padding: '20px 24px' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>{title}</div>
          {subtitle && <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>{subtitle}</div>}
        </div>
        {action}
      </div>
      {children}
    </div>
  );
}

function TodayCards({ today }: { today: TodayResp | null }) {
  if (!today) return null;
  const channels = today.northbound.channels;
  const total = channels.find(c => c.channel === 'total');
  const shHk = channels.find(c => c.channel === 'sh_hk');
  const szHk = channels.find(c => c.channel === 'sz_hk');
  const cardStyle: React.CSSProperties = {
    background: 'var(--bg-secondary)', border: '1px solid var(--border-color)',
    borderRadius: 10, padding: '14px 16px', flex: 1, minWidth: 140,
  };
  const lbl: React.CSSProperties = { fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 };
  const val = (v: number | null): React.CSSProperties => ({ fontSize: 20, fontWeight: 700, color: flowColor(v) });

  return (
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
      <div style={cardStyle}>
        <div style={lbl}>北向资金 · 今日净买额</div>
        <div style={val(total?.net_buy_amount ?? null)}>{fmtYi(total?.net_buy_amount ?? null)}</div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>{today.northbound.date ?? '—'}</div>
      </div>
      {shHk && (
        <div style={cardStyle}>
          <div style={lbl}>沪股通净买额</div>
          <div style={val(shHk.net_buy_amount)}>{fmtYi(shHk.net_buy_amount)}</div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>沪深300 {fmtPct(shHk.hs300_change_pct)}</div>
        </div>
      )}
      {szHk && (
        <div style={cardStyle}>
          <div style={lbl}>深股通净买额</div>
          <div style={val(szHk.net_buy_amount)}>{fmtYi(szHk.net_buy_amount)}</div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>{today.northbound.date ?? '—'}</div>
        </div>
      )}
      {today.etf_shares.items.map(item => (
        (() => {
          const guide = ETF_GUIDE[item.symbol];
          return (
            <div key={item.symbol} style={cardStyle}>
              <div style={lbl}>{item.symbol} · 基金份额</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: ETF_COLORS[item.symbol] || 'var(--text-primary)' }}>
                {item.total_share !== null ? `${item.total_share.toFixed(2)}亿份` : '—'}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                {item.name} · {today.etf_shares.date ?? '—'}
              </div>
              {guide && (
                <div style={{ marginTop: 7, fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.55 }}>
                  跟踪 {guide.index} · {guide.role}
                </div>
              )}
            </div>
          );
        })()
      ))}
    </div>
  );
}

function SupportSignalPanel({ latest }: { latest: BigMoneySignalRow | null }) {
  if (!latest) {
    return (
      <div style={{ padding: 18, borderRadius: 10, background: 'var(--bg-secondary)', color: 'var(--text-muted)', fontSize: 13 }}>
        暂无托底大盘信号，请先导入 ETF 份额历史。
      </div>
    );
  }
  const mainColor = signalColor(latest.signal, latest.watch_signal);
  const displayLabel = latest.signal !== 'neutral' ? latest.signal_label : latest.watch_signal !== 'none' ? latest.watch_label : latest.signal_label;
  const Icon = latest.signal === 'accumulate' || latest.watch_signal === 'watch_accumulate'
    ? TrendingUp
    : latest.signal === 'reduce' || latest.signal === 'support_fading' || latest.watch_signal === 'watch_reduce'
    ? TrendingDown
    : ShieldCheck;
  const evidence = latest.evidence?.core_etfs ?? [];
  const metricStyle: React.CSSProperties = {
    background: 'rgba(255,255,255,0.03)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: 8,
    padding: '10px 12px',
    minWidth: 132,
    flex: 1,
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(min(280px, 100%), 1fr))',
        gap: 14,
      }}>
        <div style={{
          background: signalBg(latest.signal, latest.watch_signal),
          border: `1px solid ${mainColor}55`,
          borderRadius: 10,
          padding: '16px 18px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: mainColor, fontSize: 12, fontWeight: 700, marginBottom: 10 }}>
            <Icon size={16} />
            托底大盘信号
          </div>
          <div style={{ fontSize: 28, fontWeight: 800, color: mainColor, lineHeight: 1.15 }}>{displayLabel}</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
            <span style={{ fontSize: 11, padding: '4px 8px', borderRadius: 999, background: 'rgba(255,255,255,0.08)', color: 'var(--text-secondary)' }}>
              {latest.date}
            </span>
            <span style={{ fontSize: 11, padding: '4px 8px', borderRadius: 999, background: 'rgba(255,255,255,0.08)', color: 'var(--text-secondary)' }}>
              置信度 {confidenceLabel(latest.confidence)}
            </span>
            <span style={{ fontSize: 11, padding: '4px 8px', borderRadius: 999, background: 'rgba(255,255,255,0.08)', color: 'var(--text-secondary)' }}>
              {dataQualityLabel(latest.data_quality)}
            </span>
          </div>
        </div>
        <div style={{
          background: 'var(--bg-secondary)',
          border: '1px solid var(--border-color)',
          borderRadius: 10,
          padding: '14px 16px',
          color: 'var(--text-secondary)',
          fontSize: 13,
          lineHeight: 1.8,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, color: 'var(--text-primary)', fontWeight: 700, marginBottom: 6 }}>
            <Activity size={15} />
            证据摘要
          </div>
          {latest.evidence?.explanation ?? '当前信号缺少解释数据。'}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <div style={metricStyle}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>篮子份额变化</div>
          <div style={{ fontSize: 18, fontWeight: 800, color: flowColor(latest.basket_delta_share) }}>{fmtYiFen(latest.basket_delta_share)}</div>
        </div>
        <div style={metricStyle}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>估算资金</div>
          <div style={{ fontSize: 18, fontWeight: 800, color: flowColor(latest.estimated_amount) }}>{fmtYi(latest.estimated_amount)}</div>
        </div>
        <div style={metricStyle}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>20日异常度</div>
          <div style={{ fontSize: 18, fontWeight: 800, color: signalColor(latest.signal, latest.watch_signal) }}>{fmtSigma(latest.z_score)}</div>
        </div>
        <div style={metricStyle}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>20日回撤</div>
          <div style={{ fontSize: 18, fontWeight: 800, color: flowColor(latest.market_drawdown_20) }}>{fmtPct(latest.market_drawdown_20)}</div>
        </div>
      </div>

      {evidence.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 10 }}>
          {evidence.map(item => (
            <div key={item.symbol} style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: 10, padding: '12px 14px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: ETF_COLORS[item.symbol] || 'var(--text-primary)' }}>{item.symbol}</span>
                <span style={{ fontSize: 11, color: item.status === 'complete' ? 'var(--text-muted)' : '#f59e0b' }}>
                  {item.status === 'complete' ? '完整' : item.status}
                </span>
              </div>
              <div style={{ marginTop: 8, fontSize: 18, fontWeight: 800, color: flowColor(item.delta_share) }}>{fmtYiFen(item.delta_share)}</div>
              <div style={{ marginTop: 3, fontSize: 11, color: 'var(--text-muted)' }}>
                总份额 {item.total_share !== null ? `${item.total_share.toFixed(2)}亿份` : '—'} · 估算 {fmtYi(item.estimated_amount)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function BigMoney() {
  const [northbound, setNorthbound] = useState<NorthboundResp | null>(null);
  const [etf, setEtf] = useState<EtfResp | null>(null);
  const [today, setToday] = useState<TodayResp | null>(null);
  const [intraday, setIntraday] = useState<IntradayResp | null>(null);
  const [signals, setSignals] = useState<BigMoneySignalResp | null>(null);
  const [bei50Risk, setBei50Risk] = useState<Bei50RiskResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshResult, setRefreshResult] = useState<RefreshResp | null>(null);
  const [backfilling, setBackfilling] = useState(false);
  const [backfillDone, setBackfillDone] = useState(false);
  const [nbRange, setNbRange] = useState<Range>('3Y');
  const [etfRange, setEtfRange] = useState<Range>('ALL');
  const [signalRange, setSignalRange] = useState<Range>('1Y');
  const [bei50Range, setBei50Range] = useState<Range>('3M');
  const hasBackfilled = useRef(false);
  const intradayTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchIntraday = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/api/v1/big-money/northbound/intraday`);
      setIntraday(res.data);
    } catch { /* silent */ }
  }, []);

  const fetchAll = useCallback(async () => {
    try {
      const [nbRes, etfRes, todayRes, signalRes, bei50Res] = await Promise.all([
        axios.get(`${API}/api/v1/big-money/northbound`),
        axios.get(`${API}/api/v1/big-money/etf-shares`),
        axios.get(`${API}/api/v1/big-money/today`),
        axios.get(`${API}/api/v1/big-money/signals?days=3650`),
        axios.get(`${API}/api/v1/big-money/bei50-risk?days=365`),
      ]);
      setNorthbound(nbRes.data);
      setEtf(etfRes.data);
      setToday(todayRes.data);
      setSignals(signalRes.data);
      setBei50Risk(bei50Res.data);

      const hasNb = (nbRes.data.data?.length ?? 0) > 0;
      const hasEtf = (etfRes.data.symbols?.length ?? 0) > 0;
      if (!hasNb && !hasEtf && !hasBackfilled.current) {
        hasBackfilled.current = true;
        setBackfilling(true);
        axios.post(`${API}/api/v1/big-money/backfill?northbound_history=true&etf_days=730`, null, POST_OPTS).catch(() => {});
        setTimeout(() => fetchAll(), 45000);
        setTimeout(() => fetchAll(), 120000);
        setTimeout(() => { setBackfilling(false); setBackfillDone(true); }, 130000);
      }
    } catch (e) {
      console.error('BigMoney fetchAll error', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    fetchIntraday();
    // Poll intraday every 2 minutes
    intradayTimer.current = setInterval(fetchIntraday, 2 * 60 * 1000);
    return () => { if (intradayTimer.current) clearInterval(intradayTimer.current); };
  }, [fetchAll, fetchIntraday]);

  const handleRefresh = async () => {
    setRefreshing(true);
    setRefreshResult(null);
    try {
      const res = await axios.post(`${API}/api/v1/big-money/refresh`, null, { timeout: 45000 });
      setRefreshResult(res.data);
      await fetchAll();
    } finally {
      setRefreshing(false);
    }
    await fetchIntraday();
  };

  const handleBackfillHistory = async () => {
    setBackfilling(true);
    try {
      await axios.post(`${API}/api/v1/big-money/backfill?northbound_history=true&etf_days=730`, null, POST_OPTS);
    } finally {
      setBackfilling(false);
    }
    setTimeout(() => fetchAll(), 45000);
    setTimeout(() => fetchAll(), 120000);
  };

  const nbFiltered = filterByRange(northbound?.data ?? [], nbRange);
  const huijinEvents = northbound?.huijin_events ?? [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>大资金动向</h1>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '4px 0 0' }}>
            北向资金（沪深港通）· 国家队 ETF 份额监控
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={handleBackfillHistory}
            disabled={backfilling}
            style={{
              display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px',
              borderRadius: 8, fontSize: 12, border: '1px solid var(--border-color)',
              background: 'var(--bg-secondary)', color: 'var(--text-secondary)',
              cursor: backfilling ? 'not-allowed' : 'pointer', opacity: backfilling ? 0.6 : 1,
            }}
          >
            <Database size={14} />{backfilling ? '回填中…' : '导入历史'}
          </button>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            style={{
              display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px',
              borderRadius: 8, fontSize: 12,
              border: `1px solid ${refreshing ? 'var(--border-color)' : 'rgba(99,102,241,0.4)'}`,
              background: refreshing ? 'var(--bg-secondary)' : 'rgba(99,102,241,0.1)',
              color: refreshing ? 'var(--text-muted)' : '#6366f1',
              cursor: refreshing ? 'not-allowed' : 'pointer',
            }}
          >
            <RefreshCw size={14} style={{ animation: refreshing ? 'spin 1s linear infinite' : 'none' }} />
            {refreshing ? '刷新中…' : '刷新今日'}
          </button>
        </div>
      </div>

      {backfilling && (
        <div style={{ padding: '10px 16px', borderRadius: 8, fontSize: 12, background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(99,102,241,0.2)', color: '#6366f1' }}>
          正在后台导入历史数据（北向资金历史 + ETF 份额/托底信号近2年）…完成后页面将自动刷新。
        </div>
      )}
      {backfillDone && (
        <div style={{ padding: '10px 16px', borderRadius: 8, fontSize: 12, background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.2)', color: '#10b981' }}>
          历史数据导入完成，图表已更新。
        </div>
      )}
      {refreshResult && (
        <div style={{ padding: '10px 16px', borderRadius: 8, fontSize: 12, ...refreshStatusStyle(refreshResult.status) }}>
          <div style={{ fontWeight: 700, marginBottom: 6 }}>
            {refreshResult.message}（目标日期：{refreshResult.target_date}）
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            {refreshResult.details.map(item => (
              <span key={item.key} style={{ color: 'var(--text-secondary)' }}>
                <strong style={{ color: item.status === 'success' ? '#10b981' : item.status === 'error' ? '#ef4444' : '#f59e0b' }}>
                  {item.label}
                </strong>
                ：{item.latest_date ?? '无数据'} · {item.message}
              </span>
            ))}
          </div>
        </div>
      )}

      {loading ? (
        <div style={{ textAlign: 'center', padding: 60, color: 'var(--text-muted)', fontSize: 13 }}>加载中…</div>
      ) : (
        <>
          {/* Today snapshot */}
          <SectionCard title="今日快照" subtitle={today?.northbound.date ? `数据日期：${today.northbound.date}` : undefined}>
            <TodayCards today={today} />
          </SectionCard>

          <SectionCard
            title="托底大盘信号"
            subtitle="主信号保守，观察提示敏感；依据 510050 / 510300 / 510500 份额变化"
          >
            <SupportSignalPanel latest={signals?.latest ?? null} />
          </SectionCard>

          <SectionCard
            title="北交所风险偏好"
            subtitle="北证50相对沪深300强弱 · 辅助判断小盘/成长是否扩散，不纳入国家队托底主信号"
          >
            <Bei50RiskPanel risk={bei50Risk} range={bei50Range} onRangeChange={setBei50Range} />
          </SectionCard>

          <SectionCard
            title="信号证据"
            subtitle="核心 ETF 篮子每日份额变化与 20 日滚动异常度"
            action={<RangeButtons value={signalRange} onChange={setSignalRange} />}
          >
            <SignalEvidenceChart data={signals?.data ?? []} range={signalRange} />
            {signals?.message && (
              <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-muted)', textAlign: 'center' }}>{signals.message}</div>
            )}
          </SectionCard>

          <SectionCard
            title="今日盘中走势"
            subtitle={intraday?.source_broken ? '数据源不可用' : intraday?.date ? `${intraday.date} · 分钟级累计净买额（亿元）` : '交易日 9:30–15:00'}
          >
            <div style={{ display: 'flex', gap: 16, marginBottom: 10, flexWrap: 'wrap' }}>
              {[['#10b981', '北向合计'], ['#6366f1', '沪股通'], ['#f59e0b', '深股通']].map(([color, label]) => (
                <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                  <div style={{ width: 16, height: 3, background: color, borderRadius: 2 }} />
                  <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
                </div>
              ))}
            </div>
            <IntradayChart
              data={intraday?.data ?? []}
              date={intraday?.date ?? null}
              sourceBroken={intraday?.source_broken}
              message={intraday?.message}
            />
          </SectionCard>

          {/* Northbound history */}
          <SectionCard
            title="北向资金净买额趋势"
            subtitle="沪股通 + 深股通合计，亿元，正值 = 净流入 A 股"
            action={<RangeButtons value={nbRange} onChange={setNbRange} />}
          >
            <NorthboundChart data={nbFiltered} huijinEvents={huijinEvents} />
            {northbound?.message && (
              <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-muted)', textAlign: 'center' }}>{northbound.message}</div>
            )}
            {huijinEvents.length > 0 && nbFiltered.length > 0 && (
              <div style={{ marginTop: 10, display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                {huijinEvents.map(ev => (
                  <div key={ev.date} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#f59e0b' }}>
                    <div style={{ width: 20, height: 2, background: '#f59e0b', borderRadius: 1 }} />
                    {ev.date} {ev.label}
                  </div>
                ))}
              </div>
            )}
          </SectionCard>

          {/* ETF shares */}
          <SectionCard
            title="国家队 ETF 份额监控"
            subtitle="510050 / 510300 / 510500 基金份额（亿份）· 份额突增 = 推断汇金入场"
            action={<RangeButtons value={etfRange} onChange={setEtfRange} />}
          >
            <div style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 10,
              padding: '11px 13px',
              borderRadius: 10,
              background: 'rgba(245,158,11,0.08)',
              color: 'var(--text-secondary)',
              fontSize: 12,
              lineHeight: 1.75,
              marginBottom: 12,
            }}>
              <Info size={15} style={{ color: '#f59e0b', marginTop: 2, flexShrink: 0 }} />
              <div>
                <strong style={{ color: 'var(--text-primary)' }}>怎么读份额：</strong>
                ETF 份额增加通常表示一级市场申购，可能对应大资金买入该宽基篮子；份额减少通常表示赎回，说明托底或配置力度下降。
                单只 ETF 变化只看结构，三只合计变化和 20 日异常度才作为主信号依据。
              </div>
            </div>
            <EtfGuidePanel latest={signals?.latest ?? null} />
            <div style={{ display: 'flex', gap: 16, marginBottom: 12, flexWrap: 'wrap' }}>
              {Object.entries(ETF_COLORS).map(([sym, color]) => (
                <div key={sym} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                  <div style={{ width: 16, height: 3, background: color, borderRadius: 2 }} />
                  <span style={{ color: 'var(--text-secondary)' }}>{sym} · {ETF_GUIDE[sym]?.shortName ?? 'ETF'}</span>
                </div>
              ))}
            </div>
            <EtfShareChart symbols={etf?.symbols ?? []} etfData={etf?.data ?? {}} range={etfRange} />
            {etf?.message && (
              <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-muted)', textAlign: 'center' }}>{etf.message}</div>
            )}
          </SectionCard>

          {/* Note */}
          <div style={{ padding: '10px 14px', borderRadius: 8, fontSize: 11, background: 'rgba(107,114,128,0.06)', border: '1px solid var(--border-color)', color: 'var(--text-muted)', lineHeight: 1.8 }}>
            <strong style={{ color: 'var(--text-secondary)' }}>数据说明：</strong>
            北向资金历史来自东方财富（有效至 2024-08-16）。
            <span style={{ color: '#f59e0b', margin: '0 4px' }}>▲ 数据断档</span>
            — 东方财富于 2024-08-19 更改接口字段结构，AkShare 尚未适配，历史净买额及分钟级实时数据均已不可用（约 21 个月缺口）。
            ETF 份额来自上交所每日快照，每日盘后更新。份额变化是基金总规模变化的代理，托底信号基于宽基 ETF 份额变化推断，不等于国家队实时持仓披露，也不构成单独买卖指令。
          </div>
        </>
      )}
    </div>
  );
}
