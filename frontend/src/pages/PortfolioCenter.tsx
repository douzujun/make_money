import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowDownRight, ArrowUpRight, BadgeInfo, CheckCircle2, Coins, Gauge,
  Layers, Loader2, PieChart, Plus, Save, Search, ShieldCheck, Target, Trash2,
  WalletCards, Waves,
} from 'lucide-react';

const API = '/api/v1';
const PORTFOLIO_DRAFT_KEY = 'portfolio-center-draft-v1';
const PORTFOLIO_CODE_BOOK_KEY = 'portfolio-center-fund-code-book-v1';
const PORTFOLIO_PROFIT_BOOK_KEY = 'portfolio-center-profit-book-v1';
const PORTFOLIO_SECTOR_BOOK_KEY = 'portfolio-center-flow-sector-book-v1';
const PORTFOLIO_BACKTEST_A_KEY = 'portfolio-center-backtest-a-v1';

type BucketId =
  | 'a_share_core'
  | 'overseas_core'
  | 'gold'
  | 'cash'
  | 'commodities'
  | 'themes'
  | 'fragments';

type ActionType = 'add' | 'add_watch' | 'trim' | 'trim_watch' | 'hold' | 'clear' | 'merge_watch';

interface Holding {
  id?: number;
  fund_code?: string | null;
  name: string;
  amount: number;
  profit_amount?: number | null;
  profit_rate?: number | null;
  bucket: Exclude<BucketId, 'cash'>;
  flow_sector_name?: string | null;
  note?: string | null;
}

interface Snapshot {
  id: number;
  snapshot_date: string;
  money_fund_amount: number;
  cash_amount: number;
  usable_cash_amount: number;
  reserve_floor_amount: number;
  note?: string | null;
  holdings: Holding[];
}

interface BucketRow {
  bucket: BucketId;
  name: string;
  short: string;
  amount: number;
  pct: number;
  target: number;
  diff_amount: number;
  diff_pct: number;
}

interface RecommendationAction {
  type: ActionType;
  bucket: BucketId;
  target_name: string;
  amount: number;
  raw_amount?: number;
  priority: number;
  reason: string;
  execution: string;
  market_confirmation?: MarketConfirmation;
}

interface MarketConfirmation {
  status: 'supportive' | 'caution' | 'neutral' | 'not_applicable' | 'unavailable' | string;
  label: string;
  factor: number;
  date?: string | null;
  sector_name?: string | null;
  operation_permission?: string;
  permission_label?: string;
  summary: string;
  evidence: Record<string, any>;
}

interface FundRecommendation {
  fund_code?: string | null;
  name: string;
  bucket: Exclude<BucketId, 'cash'>;
  amount: number;
  profit_amount?: number | null;
  profit_rate?: number | null;
  flow_sector_name?: string | null;
  recommendation: string;
  recommendation_label: string;
  suggested_amount: number;
  intraday_cap: number;
  reason: string;
  data_note: string;
  estimate_modifier: {
    factor: number;
    label: string;
    reason: string;
  };
  profit_modifier: {
    factor: number;
    label: string;
    reason: string;
  };
  market_confirmation: MarketConfirmation;
  estimate: {
    available: boolean;
    source: string;
    fund_code?: string;
    name?: string;
    nav_date?: string;
    nav?: number | null;
    estimate_nav?: number | null;
    estimate_change_pct?: number | null;
    estimate_time?: string;
    message: string;
  };
}

interface Recommendation {
  snapshot: Snapshot;
  total_assets: number;
  cash_budget: number;
  daily_add_cap: number;
  daily_trim_cap: number;
  signal: string;
  signal_label: string;
  policy: Record<string, string | number>;
  bucket_rows: BucketRow[];
  market_confirmations: Partial<Record<BucketId, MarketConfirmation>>;
  actions: RecommendationAction[];
  fund_recommendations: FundRecommendation[];
  sector_options: string[];
  intraday_policy: {
    source: string;
    max_action: number;
    role: string;
  };
  formula: string;
}

const BUCKETS: Record<BucketId, { name: string; color: string; role: string }> = {
  a_share_core: {
    name: 'A股宽基核心仓',
    color: '#2563eb',
    role: '组合进攻底座，优先补沪深300/中证500等低重叠资产。',
  },
  overseas_core: {
    name: '海外宽基/全球成长',
    color: '#7c3aed',
    role: '分散人民币资产与A股周期，纳指/全球成长重复度要控制。',
  },
  gold: {
    name: '黄金防守仓',
    color: '#d97706',
    role: '防守与尾部风险对冲，接近目标时只观察不追高。',
  },
  cash: {
    name: '现金/货币基金',
    color: '#16a34a',
    role: '再平衡弹药与生活安全垫，最低保留 8 万。',
  },
  commodities: {
    name: '商品/资源链',
    color: '#dc2626',
    role: '高波动卫星仓，只适合小比例表达通胀和周期观点。',
  },
  themes: {
    name: '行业主题仓',
    color: '#0891b2',
    role: '半导体、新能源、软件等弹性仓，单次调仓 1%-2%。',
  },
  fragments: {
    name: '碎片/待合并仓',
    color: '#64748b',
    role: '金额过小或策略不清晰的仓位，优先合并减少噪音。',
  },
};

const HOLDING_BUCKETS = Object.entries(BUCKETS)
  .filter(([key]) => key !== 'cash') as [Exclude<BucketId, 'cash'>, { name: string; color: string; role: string }][];

function money(v: number) {
  if (Math.abs(v) >= 10000) return `${(v / 10000).toFixed(2)} 万`;
  return `${Math.round(v).toLocaleString('zh-CN')} 元`;
}

function pct(v: number) {
  return `${(v * 100).toFixed(1)}%`;
}

function actionColor(type: ActionType | string) {
  if (type === 'add' || type === 'intraday_add_watch') return '#2563eb';
  if (type === 'add_watch') return '#d97706';
  if (type === 'trim_watch') return '#d97706';
  if (type === 'trim' || type === 'clear' || type === 'clear_watch' || type === 'intraday_trim_watch') return '#dc2626';
  if (type === 'merge_watch') return '#d97706';
  return '#16a34a';
}

function actionLabel(type: ActionType | string) {
  return {
    add: '加仓',
    add_watch: '加仓观察',
    trim: '减仓',
    trim_watch: '减仓观察',
    hold: '持有',
    clear: '清仓',
    merge_watch: '合并观察',
  }[type] ?? type;
}

function confirmationColor(status?: string) {
  if (status === 'supportive') return '#2563eb';
  if (status === 'caution') return '#dc2626';
  if (status === 'neutral') return '#d97706';
  return '#64748b';
}

function formatYi(v?: number | null) {
  if (v === undefined || v === null || Number.isNaN(v)) return '—';
  return `${v >= 0 ? '+' : ''}${Number(v).toFixed(2)} 亿`;
}

function formatSigma(v?: number | null) {
  if (v === undefined || v === null || Number.isNaN(v)) return '—';
  return `${v >= 0 ? '+' : ''}${Number(v).toFixed(2)}σ`;
}

function formatSignedPct(v?: number | null) {
  if (v === undefined || v === null || Number.isNaN(v)) return '—';
  return `${v >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`;
}

function MarketBadge({ confirmation }: { confirmation?: MarketConfirmation }) {
  if (!confirmation) return null;
  const color = confirmationColor(confirmation.status);
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '4px 8px', borderRadius: 999, background: `${color}18`, color, fontSize: 11, fontWeight: 800 }}>
      <Waves size={12} />
      {confirmation.label}
    </span>
  );
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function authHeaders() {
  const token = localStorage.getItem('token');
  return { Authorization: `Bearer ${token}` };
}

function loadDraft(): Snapshot | null {
  try {
    const raw = localStorage.getItem(PORTFOLIO_DRAFT_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveDraft(snapshot: Snapshot) {
  localStorage.setItem(PORTFOLIO_DRAFT_KEY, JSON.stringify(snapshot));
}

function loadCodeBook(): Record<string, string> {
  try {
    const raw = localStorage.getItem(PORTFOLIO_CODE_BOOK_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveCodeBook(holdings: Holding[]) {
  const current = loadCodeBook();
  const next = { ...current };
  holdings.forEach(h => {
    const code = (h.fund_code ?? '').trim();
    if (h.name && code) next[h.name] = code;
  });
  localStorage.setItem(PORTFOLIO_CODE_BOOK_KEY, JSON.stringify(next));
}

function applyCodeBook(snapshot: Snapshot): Snapshot {
  const book = loadCodeBook();
  return {
    ...snapshot,
    holdings: snapshot.holdings.map(h => ({
      ...h,
      fund_code: h.fund_code || book[h.name] || '',
    })),
  };
}

function loadProfitBook(): Record<string, { profit_amount?: number | null; profit_rate?: number | null }> {
  try {
    const raw = localStorage.getItem(PORTFOLIO_PROFIT_BOOK_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveProfitBook(holdings: Holding[]) {
  const current = loadProfitBook();
  const next = { ...current };
  holdings.forEach(h => {
    if (!h.name) return;
    if (h.profit_amount !== undefined || h.profit_rate !== undefined) {
      next[h.name] = {
        profit_amount: h.profit_amount ?? null,
        profit_rate: h.profit_rate ?? null,
      };
    }
  });
  localStorage.setItem(PORTFOLIO_PROFIT_BOOK_KEY, JSON.stringify(next));
}

function applyProfitBook(snapshot: Snapshot): Snapshot {
  const book = loadProfitBook();
  return {
    ...snapshot,
    holdings: snapshot.holdings.map(h => ({
      ...h,
      profit_amount: h.profit_amount ?? book[h.name]?.profit_amount ?? null,
      profit_rate: h.profit_rate ?? book[h.name]?.profit_rate ?? null,
    })),
  };
}

function loadSectorBook(): Record<string, string> {
  try {
    const raw = localStorage.getItem(PORTFOLIO_SECTOR_BOOK_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveSectorBook(holdings: Holding[]) {
  const current = loadSectorBook();
  const next = { ...current };
  holdings.forEach(h => {
    const sector = (h.flow_sector_name ?? '').trim();
    if (h.name && sector) next[h.name] = sector;
  });
  localStorage.setItem(PORTFOLIO_SECTOR_BOOK_KEY, JSON.stringify(next));
}

function applySectorBook(snapshot: Snapshot): Snapshot {
  const book = loadSectorBook();
  return {
    ...snapshot,
    holdings: snapshot.holdings.map(h => ({
      ...h,
      flow_sector_name: h.flow_sector_name || book[h.name] || '',
    })),
  };
}

function applyLocalBooks(snapshot: Snapshot): Snapshot {
  return applySectorBook(applyProfitBook(applyCodeBook(snapshot)));
}

function normaliseWeights(weights: Record<string, number>) {
  const total = Object.values(weights).reduce((sum, value) => sum + value, 0);
  if (!total) return weights;
  return Object.fromEntries(
    Object.entries(weights).map(([key, value]) => [key, Math.round((value / total) * 10000) / 10000]),
  );
}

function buildBacktestProxy(snapshot: Snapshot) {
  const bucketAmounts: Record<BucketId, number> = {
    a_share_core: 0,
    overseas_core: 0,
    gold: 0,
    cash: snapshot.money_fund_amount + snapshot.cash_amount,
    commodities: 0,
    themes: 0,
    fragments: 0,
  };
  snapshot.holdings.forEach(holding => {
    bucketAmounts[holding.bucket] += holding.amount;
  });
  const total = Object.values(bucketAmounts).reduce((sum, amount) => sum + amount, 0) || 1;
  const weights = {
    '510300': (bucketAmounts.a_share_core / total) * 0.7,
    '510050': 0,
    '510500': (bucketAmounts.a_share_core / total) * 0.3 + (bucketAmounts.commodities / total) * 0.6,
    '159915': bucketAmounts.themes / total,
    '513100': bucketAmounts.overseas_core / total,
    '511010': 0,
    '518880': bucketAmounts.gold / total + (bucketAmounts.commodities / total) * 0.4,
    CASH: (bucketAmounts.cash + bucketAmounts.fragments) / total,
  };
  return {
    weights: normaliseWeights(weights),
    snapshot_date: snapshot.snapshot_date,
    generated_at: new Date().toISOString(),
    source: 'portfolio_center_snapshot',
  };
}

function saveBacktestProxy(snapshot: Snapshot) {
  localStorage.setItem(PORTFOLIO_BACKTEST_A_KEY, JSON.stringify(buildBacktestProxy(snapshot)));
}

function Card({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <div
      style={{
        background: 'var(--bg-primary)',
        border: '1px solid var(--border-color)',
        borderRadius: 12,
        padding: 18,
        boxShadow: 'var(--shadow-sm)',
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function SectionTitle({
  icon: Icon,
  title,
  subtitle,
}: {
  icon: React.ElementType;
  title: string;
  subtitle?: string;
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
      <div
        style={{
          width: 32,
          height: 32,
          borderRadius: 8,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: '#6366f118',
          color: '#4f46e5',
          flexShrink: 0,
        }}
      >
        <Icon size={17} />
      </div>
      <div>
        <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>{title}</div>
        {subtitle && <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 1 }}>{subtitle}</div>}
      </div>
    </div>
  );
}

function NumberInput({
  value,
  onChange,
  width = 112,
}: {
  value: number;
  onChange: (value: number) => void;
  width?: number;
}) {
  return (
    <input
      type="number"
      min={0}
      step={100}
      value={Number.isFinite(value) ? value : 0}
      onChange={e => onChange(Math.max(0, Number(e.target.value) || 0))}
      style={{
        width,
        padding: '7px 9px',
        borderRadius: 8,
        border: '1px solid var(--border-color)',
        background: 'var(--bg-secondary)',
        color: 'var(--text-primary)',
        fontSize: 12,
      }}
    />
  );
}

function SignedNumberInput({
  value,
  onChange,
  width = 96,
  step = 100,
}: {
  value?: number | null;
  onChange: (value: number | null) => void;
  width?: number;
  step?: number;
}) {
  return (
    <input
      type="number"
      step={step}
      value={value ?? ''}
      onChange={e => onChange(e.target.value === '' ? null : Number(e.target.value))}
      style={{
        width,
        padding: '7px 9px',
        borderRadius: 8,
        border: '1px solid var(--border-color)',
        background: 'var(--bg-secondary)',
        color: 'var(--text-primary)',
        fontSize: 12,
      }}
    />
  );
}

function SectorSelect({
  value,
  options,
  onChange,
  width = 170,
}: {
  value?: string | null;
  options: string[];
  onChange: (value: string | null) => void;
  width?: number;
}) {
  const [query, setQuery] = useState(value ?? '');
  const [open, setOpen] = useState(false);
  const trimmed = query.trim();
  const filtered = useMemo(() => {
    if (!trimmed) return options.slice(0, 30);
    return options
      .filter(name => name.toLowerCase().includes(trimmed.toLowerCase()))
      .slice(0, 30);
  }, [options, trimmed]);

  useEffect(() => {
    setQuery(value ?? '');
  }, [value]);

  const choose = (name: string | null) => {
    setQuery(name ?? '');
    setOpen(false);
    onChange(name);
  };

  return (
    <div style={{ position: 'relative', width }}>
      <div style={{ position: 'relative' }}>
        <Search size={13} style={{ position: 'absolute', left: 8, top: 9, color: 'var(--text-muted)', pointerEvents: 'none' }} />
        <input
          value={query}
          placeholder="搜索板块/自动匹配"
          onFocus={() => setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 140)}
          onChange={e => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          style={{
            width: '100%',
            padding: '7px 9px 7px 27px',
            borderRadius: 8,
            border: '1px solid var(--border-color)',
            background: 'var(--bg-secondary)',
            color: 'var(--text-primary)',
            fontSize: 12,
            boxSizing: 'border-box',
          }}
        />
      </div>
      {open && (
        <div
          style={{
            position: 'absolute',
            top: 36,
            left: 0,
            width: Math.max(width, 220),
            maxHeight: 240,
            overflowY: 'auto',
            background: 'var(--bg-primary)',
            border: '1px solid var(--border-color)',
            borderRadius: 10,
            boxShadow: 'var(--shadow-md)',
            zIndex: 20,
          }}
        >
          <button
            type="button"
            onMouseDown={e => {
              e.preventDefault();
              choose(null);
            }}
            style={{
              width: '100%',
              padding: '9px 10px',
              border: 'none',
              borderBottom: '1px solid var(--border-color)',
              background: !value ? '#6366f114' : 'transparent',
              color: '#4f46e5',
              textAlign: 'left',
              cursor: 'pointer',
              fontSize: 12,
              fontWeight: 750,
            }}
          >
            自动匹配
          </button>
          {filtered.map(name => (
            <button
              key={name}
              type="button"
              onMouseDown={e => {
                e.preventDefault();
                choose(name);
              }}
              style={{
                width: '100%',
                padding: '8px 10px',
                border: 'none',
                borderBottom: '1px solid var(--border-color)',
                background: name === value ? '#6366f114' : 'transparent',
                color: name === value ? '#4f46e5' : 'var(--text-primary)',
                textAlign: 'left',
                cursor: 'pointer',
                fontSize: 12,
              }}
            >
              {name}
            </button>
          ))}
          {filtered.length === 0 && (
            <div style={{ padding: 10, fontSize: 12, color: 'var(--text-muted)' }}>
              没有匹配板块
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AllocationBar({ rows }: { rows: BucketRow[] }) {
  return (
    <div>
      <div style={{ display: 'flex', height: 22, borderRadius: 7, overflow: 'hidden', background: 'var(--bg-tertiary)' }}>
        {rows.map(row => (
          <div
            key={row.bucket}
            title={`${row.name} ${pct(row.pct)}`}
            style={{
              width: `${Math.max(row.pct * 100, row.pct > 0 ? 1 : 0)}%`,
              background: BUCKETS[row.bucket].color,
              minWidth: row.pct > 0.002 ? 3 : 0,
            }}
          />
        ))}
      </div>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 12 }}>
        {rows.map(row => (
          <div key={row.bucket} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-secondary)' }}>
            <span style={{ width: 9, height: 9, borderRadius: 3, background: BUCKETS[row.bucket].color }} />
            <span>{row.short}</span>
            <strong style={{ color: 'var(--text-primary)' }}>{pct(row.pct)}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function TargetDeviation({ rows }: { rows: BucketRow[] }) {
  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {rows.map(row => {
        const over = row.diff_amount > 0;
        const barWidth = Math.min(100, Math.abs(row.diff_pct) * 280);
        return (
          <div key={row.bucket}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 6 }}>
              <span style={{ fontSize: 13, fontWeight: 650, color: 'var(--text-primary)' }}>{row.name}</span>
              <span style={{ fontSize: 12, color: over ? '#dc2626' : '#2563eb', fontWeight: 700 }}>
                {over ? '超配' : '低配'} {money(Math.abs(row.diff_amount))}
              </span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4, alignItems: 'center' }}>
              <div style={{ height: 8, background: 'var(--bg-tertiary)', borderRadius: 4, overflow: 'hidden', transform: 'scaleX(-1)' }}>
                {!over && <div style={{ height: '100%', width: `${barWidth}%`, background: '#2563eb', borderRadius: 4 }} />}
              </div>
              <div style={{ height: 8, background: 'var(--bg-tertiary)', borderRadius: 4, overflow: 'hidden' }}>
                {over && <div style={{ height: '100%', width: `${barWidth}%`, background: '#dc2626', borderRadius: 4 }} />}
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
              <span>当前 {pct(row.pct)}</span>
              <span>目标 {pct(row.target)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function EvidenceTable({ rows }: { rows: BucketRow[] }) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 760 }}>
        <thead>
          <tr>
            {['资产桶', '当前', '目标', '偏离', '证据'].map(label => (
              <th key={label} style={{ textAlign: 'left', padding: '10px 8px', fontSize: 12, color: 'var(--text-muted)', borderBottom: '1px solid var(--border-color)' }}>
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(row => (
            <tr key={row.bucket}>
              <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--border-color)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 3, background: BUCKETS[row.bucket].color }} />
                  <span style={{ fontSize: 13, fontWeight: 650, color: 'var(--text-primary)' }}>{row.name}</span>
                </div>
              </td>
              <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--border-color)', fontSize: 13 }}>
                {money(row.amount)} / {pct(row.pct)}
              </td>
              <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--border-color)', fontSize: 13 }}>
                {pct(row.target)}
              </td>
              <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--border-color)', fontSize: 13, color: row.diff_amount > 0 ? '#dc2626' : '#2563eb', fontWeight: 650 }}>
                {row.diff_amount > 0 ? '+' : ''}{money(row.diff_amount)}
              </td>
              <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--border-color)', fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                {BUCKETS[row.bucket].role}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MarketConfirmationPanel({ confirmations }: { confirmations: Recommendation['market_confirmations'] }) {
  const order: BucketId[] = ['a_share_core', 'themes', 'commodities', 'gold', 'overseas_core'];
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
      {order.map(bucket => {
        const item = confirmations?.[bucket];
        if (!item) return null;
        const color = confirmationColor(item.status);
        const ev = item.evidence || {};
        const topSectors = Array.isArray(ev.top_sectors) ? ev.top_sectors.slice(0, 2) : [];
        return (
          <div key={bucket} style={{ border: `1px solid ${color}2b`, background: `${color}0d`, borderRadius: 10, padding: 12, minHeight: 118 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'flex-start' }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text-primary)' }}>{BUCKETS[bucket].name}</div>
                <div style={{ marginTop: 5 }}><MarketBadge confirmation={item} /></div>
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{item.date || '—'}</div>
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.55, marginTop: 9 }}>{item.summary}</div>
            {bucket === 'a_share_core' && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6, marginTop: 10, fontSize: 11 }}>
                <span style={{ color: 'var(--text-muted)' }}>份额 {formatYi(ev.basket_delta_share)}</span>
                <span style={{ color: 'var(--text-muted)' }}>资金 {formatYi(ev.estimated_amount)}</span>
                <span style={{ color: 'var(--text-muted)' }}>异常 {formatSigma(ev.z_score)}</span>
              </div>
            )}
            {bucket === 'gold' && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 6, marginTop: 10, fontSize: 11 }}>
                <span style={{ color: 'var(--text-muted)' }}>金价MA20偏离 {formatSignedPct(ev.gold_ma20_deviation_pct)}</span>
                <span style={{ color: 'var(--text-muted)' }}>美元5日趋势 {formatSignedPct(ev.dollar_trend_5d_pct)}</span>
                <span style={{ color: 'var(--text-muted)' }}>金价 {ev.gold_close ? Number(ev.gold_close).toFixed(2) : '—'}</span>
                <span style={{ color: '#d97706', fontWeight: 800 }}>{item.permission_label || '人工确认'}</span>
              </div>
            )}
            {topSectors.length > 0 && (
              <div style={{ display: 'grid', gap: 4, marginTop: 10 }}>
                {topSectors.map((sector: MarketConfirmation) => (
                  <div key={`${bucket}-${sector.sector_name}`} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 11, color: 'var(--text-muted)' }}>
                    <span>{sector.sector_name}</span>
                    <span>{formatYi(sector.evidence?.latest_net_inflow_yi)} · {sector.evidence?.score ?? '—'}分</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

type FundRecommendationFilter = 'actionable' | 'all' | 'add' | 'trim' | 'estimate_available';

function SelectControl({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <label style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 12, color: 'var(--text-muted)' }}>
      {label}
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        style={{
          height: 32,
          minWidth: 132,
          padding: '0 10px',
          borderRadius: 8,
          border: '1px solid var(--border-color)',
          background: 'var(--bg-secondary)',
          color: 'var(--text-primary)',
          fontSize: 12,
          fontWeight: 650,
        }}
      >
        {options.map(option => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    </label>
  );
}

function FundRecommendationTable({
  items,
  sectorOptions,
  onSectorChange,
}: {
  items: FundRecommendation[];
  sectorOptions: string[];
  onSectorChange: (fundName: string, sectorName: string | null) => void;
}) {
  const [filter, setFilter] = useState<FundRecommendationFilter>('actionable');
  const [displayMode, setDisplayMode] = useState('18');
  const filtered = useMemo(() => {
    if (filter === 'all') return items;
    if (filter === 'add') return items.filter(item => item.recommendation === 'intraday_add_watch');
    if (filter === 'trim') return items.filter(item => ['intraday_trim_watch', 'clear_watch'].includes(item.recommendation));
    if (filter === 'estimate_available') return items.filter(item => item.estimate?.available);
    return items.filter(item => item.suggested_amount > 0 || item.recommendation !== 'hold');
  }, [filter, items]);
  const shown = displayMode === 'all' ? filtered : filtered.slice(0, Number(displayMode));
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 10 }}>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          当前显示 <strong style={{ color: 'var(--text-primary)' }}>{shown.length}</strong> / {filtered.length} 只，组合共 {items.length} 只
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <SelectControl
            label="筛选"
            value={filter}
            onChange={value => setFilter(value as FundRecommendationFilter)}
            options={[
              { value: 'actionable', label: '有动作建议' },
              { value: 'all', label: '全部基金' },
              { value: 'add', label: '加仓观察' },
              { value: 'trim', label: '减仓/清仓' },
              { value: 'estimate_available', label: '估值可用' },
            ]}
          />
          <SelectControl
            label="显示"
            value={displayMode}
            onChange={setDisplayMode}
            options={[
              { value: '18', label: '前 18 只' },
              { value: '30', label: '前 30 只' },
              { value: 'all', label: '全部显示' },
            ]}
          />
        </div>
      </div>
      <div style={{ overflow: 'auto', maxHeight: displayMode === 'all' ? 760 : 560, border: '1px solid var(--border-color)', borderRadius: 10 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 1160 }}>
          <thead style={{ position: 'sticky', top: 0, background: 'var(--bg-primary)', zIndex: 1 }}>
            <tr>
              {['基金', '估值', '持有收益', '资金流', '建议', '金额', '归因', '数据'].map(label => (
                <th key={label} style={{ textAlign: 'left', padding: '10px 8px', fontSize: 12, color: 'var(--text-muted)', borderBottom: '1px solid var(--border-color)' }}>
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map(item => {
              const estimate = item.estimate;
              const estPct = estimate.estimate_change_pct;
              const estColor = estPct === undefined || estPct === null
                ? 'var(--text-muted)'
                : estPct >= 0
                  ? '#dc2626'
                  : '#16a34a';
              return (
                <tr key={`${item.name}-${item.fund_code ?? 'none'}`}>
                  <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--border-color)', minWidth: 260 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>{item.name}</div>
                    <div style={{ fontSize: 11, color: BUCKETS[item.bucket].color, marginTop: 2 }}>
                      {item.fund_code || '未填代码'} · {BUCKETS[item.bucket].name}
                    </div>
                  </td>
                  <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--border-color)' }}>
                    {estimate.available ? (
                      <div>
                        <div style={{ fontSize: 14, fontWeight: 800, color: estColor }}>
                          {estPct !== undefined && estPct !== null ? `${estPct >= 0 ? '+' : ''}${estPct.toFixed(2)}%` : '—'}
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{estimate.estimate_time || estimate.nav_date}</div>
                      </div>
                    ) : (
                      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{estimate.message}</div>
                    )}
                  </td>
                  <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--border-color)' }}>
                    <div style={{ fontSize: 13, fontWeight: 800, color: (item.profit_amount ?? 0) >= 0 ? '#dc2626' : '#16a34a' }}>
                      {item.profit_amount === null || item.profit_amount === undefined
                        ? '—'
                        : `${item.profit_amount >= 0 ? '+' : ''}${money(item.profit_amount)}`}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                      {item.profit_rate === null || item.profit_rate === undefined
                        ? '收益率未录入'
                        : `${item.profit_rate >= 0 ? '+' : ''}${item.profit_rate.toFixed(2)}%`}
                    </div>
                  </td>
                  <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--border-color)', minWidth: 170 }}>
                    <MarketBadge confirmation={item.market_confirmation} />
                    <div style={{ marginTop: 6 }}>
                      <SectorSelect
                        value={item.flow_sector_name}
                        options={sectorOptions}
                        onChange={value => onSectorChange(item.name, value)}
                        width={150}
                      />
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 5, lineHeight: 1.45 }}>
                      {item.market_confirmation?.sector_name || item.market_confirmation?.date || '—'}
                      {item.market_confirmation?.evidence?.score !== undefined && ` · ${item.market_confirmation.evidence.score}分`}
                    </div>
                  </td>
                  <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--border-color)' }}>
                    <span style={{ display: 'inline-flex', padding: '4px 9px', borderRadius: 999, background: `${actionColor(item.recommendation)}18`, color: actionColor(item.recommendation), fontSize: 12, fontWeight: 800 }}>
                      {item.recommendation_label}
                    </span>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>{item.estimate_modifier.label}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{item.profit_modifier.label}</div>
                  </td>
                  <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--border-color)', fontSize: 13, fontWeight: 750 }}>
                    {item.suggested_amount > 0 ? money(item.suggested_amount) : '—'}
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 400 }}>盘中上限 {money(item.intraday_cap)}</div>
                  </td>
                  <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--border-color)', fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5, minWidth: 260 }}>
                    {item.reason}
                    <div style={{ color: 'var(--text-muted)', marginTop: 2 }}>{item.estimate_modifier.reason}</div>
                    <div style={{ color: 'var(--text-muted)', marginTop: 2 }}>{item.profit_modifier.reason}</div>
                    <div style={{ color: confirmationColor(item.market_confirmation?.status), marginTop: 2 }}>{item.market_confirmation?.summary}</div>
                  </td>
                  <td style={{ padding: '12px 8px', borderBottom: '1px solid var(--border-color)', fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5, minWidth: 210 }}>
                    {item.data_note}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {shown.length === 0 && (
          <div style={{ padding: 28, textAlign: 'center', fontSize: 13, color: 'var(--text-muted)' }}>
            当前筛选下暂无基金
          </div>
        )}
      </div>
    </div>
  );
}

export default function PortfolioCenter() {
  const [data, setData] = useState<Recommendation | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [claudeReview, setClaudeReview] = useState('');
  const [error, setError] = useState('');
  const [savedText, setSavedText] = useState('');

  const loadLatest = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API}/portfolio/latest`, { headers: authHeaders() });
      if (!res.ok) throw new Error((await res.json()).detail ?? '加载持仓失败');
      const payload = await res.json();
      const draft = loadDraft();
      setData(payload);
      if (draft) {
        setSnapshot(applyLocalBooks(draft));
        setSavedText('已恢复未保存的本地草稿，记得点击保存写入数据库');
      } else {
        setSnapshot(applyLocalBooks({ ...payload.snapshot, snapshot_date: todayIso() }));
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadLatest();
  }, []);

  const updateSnapshot = (patch: Partial<Snapshot>) => {
    setSnapshot(prev => {
      if (!prev) return prev;
      const next = { ...prev, ...patch };
      saveDraft(next);
      return next;
    });
  };

  const updateHolding = (index: number, patch: Partial<Holding>) => {
    setSnapshot(prev => {
      if (!prev) return prev;
      const holdings = prev.holdings.map((h, i) => i === index ? { ...h, ...patch } : h);
      const next = { ...prev, holdings };
      saveDraft(next);
      saveCodeBook(holdings);
      saveProfitBook(holdings);
      saveSectorBook(holdings);
      return next;
    });
  };

  const addHolding = () => {
    setSnapshot(prev => {
      if (!prev) return prev;
      const newHolding: Holding = { fund_code: '', name: '新增基金', amount: 0, bucket: 'themes' };
      const next = {
        ...prev,
        holdings: [newHolding, ...prev.holdings],
      };
      saveDraft(next);
      saveCodeBook(next.holdings);
      saveProfitBook(next.holdings);
      saveSectorBook(next.holdings);
      return next;
    });
  };

  const removeHolding = (index: number) => {
    setSnapshot(prev => {
      if (!prev) return prev;
      const next = { ...prev, holdings: prev.holdings.filter((_, i) => i !== index) };
      saveDraft(next);
      return next;
    });
  };

  const updateHoldingSectorByName = (fundName: string, sectorName: string | null) => {
    setSnapshot(prev => {
      if (!prev) return prev;
      const holdings = prev.holdings.map(h => h.name === fundName ? { ...h, flow_sector_name: sectorName } : h);
      const next = { ...prev, holdings };
      saveDraft(next);
      saveSectorBook(holdings);
      return next;
    });
    setSavedText('已更新资金流板块，点击保存后写入数据库并重新生成建议');
  };

  const saveSnapshot = async () => {
    if (!snapshot) return;
    setSaving(true);
    setError('');
    setSavedText('');
    try {
      const res = await fetch(`${API}/portfolio/snapshots`, {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(snapshot),
      });
      if (!res.ok) throw new Error((await res.json()).detail ?? '保存失败');
      const payload = await res.json();
      saveCodeBook(snapshot.holdings);
      saveProfitBook(snapshot.holdings);
      saveSectorBook(snapshot.holdings);
      setData(payload);
      setSnapshot(applyLocalBooks(payload.snapshot));
      localStorage.removeItem(PORTFOLIO_DRAFT_KEY);
      setSavedText('已保存快照并重新生成建议');
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const runClaudeReview = async () => {
    setReviewing(true);
    setError('');
    setClaudeReview('');
    try {
      const res = await fetch(`${API}/portfolio/claude-review`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error((await res.json()).detail ?? 'Claude Code 审阅失败');
      const payload = await res.json();
      setClaudeReview(payload.review);
    } catch (e) {
      setError(String(e));
    } finally {
      setReviewing(false);
    }
  };

  const topHoldings = useMemo(() => {
    if (!snapshot || !data) return [];
    return [...snapshot.holdings]
      .sort((a, b) => b.amount - a.amount)
      .slice(0, 8)
      .map(h => ({ ...h, pct: h.amount / data.total_assets }));
  }, [snapshot, data]);

  if (loading) {
    return (
      <div style={{ padding: 80, textAlign: 'center', color: 'var(--text-muted)' }}>
        <Loader2 size={24} style={{ animation: 'spin 1s linear infinite' }} /> 加载组合配置中枢...
      </div>
    );
  }

  if (!data || !snapshot) {
    return <div style={{ color: '#dc2626' }}>{error || '暂无组合数据'}</div>;
  }

  const rows = data.bucket_rows;
  const aShare = rows.find(r => r.bucket === 'a_share_core')!;
  const gold = rows.find(r => r.bucket === 'gold')!;
  const cash = rows.find(r => r.bucket === 'cash')!;
  const riskOver = rows
    .filter(r => r.bucket === 'commodities' || r.bucket === 'themes')
    .reduce((sum, r) => sum + Math.max(0, r.diff_amount), 0);

  return (
    <div className="animate-fade-in" style={{ color: 'var(--text-primary)' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, marginBottom: 22, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 750, margin: 0 }}>组合配置中枢</h1>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: '4px 0 0' }}>
            手动维护每日持仓快照，按稳健慢调仓公式输出加仓、减仓、清仓建议
          </p>
        </div>
        <Link
          to="/backtest?portfolioA=current"
          onClick={() => snapshot && saveBacktestProxy(snapshot)}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            padding: '9px 14px',
            borderRadius: 9,
            border: '1px solid #6366f144',
            background: '#6366f114',
            color: '#4f46e5',
            textDecoration: 'none',
            fontSize: 13,
            fontWeight: 700,
          }}
        >
          <PieChart size={15} />
          用当前持仓回测
        </Link>
      </div>

      {error && (
        <div style={{ marginBottom: 12, padding: '10px 12px', borderRadius: 10, background: '#dc262618', color: '#dc2626', fontSize: 13 }}>
          {error}
        </div>
      )}
      {savedText && (
        <div style={{ marginBottom: 12, padding: '10px 12px', borderRadius: 10, background: '#16a34a18', color: '#16a34a', fontSize: 13, display: 'flex', gap: 8, alignItems: 'center' }}>
          <CheckCircle2 size={15} /> {savedText}
        </div>
      )}

      <Card style={{ marginBottom: 16 }}>
        <SectionTitle icon={Save} title="每日持仓快照" subtitle="今天只需要改金额和现金，保存后系统会重新计算建议" />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 12, marginBottom: 14 }}>
          <label style={{ display: 'grid', gap: 5, fontSize: 12, color: 'var(--text-muted)' }}>
            快照日期
            <input
              type="date"
              value={snapshot.snapshot_date}
              onChange={e => updateSnapshot({ snapshot_date: e.target.value })}
              style={{ padding: '7px 9px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)' }}
            />
          </label>
          <label style={{ display: 'grid', gap: 5, fontSize: 12, color: 'var(--text-muted)' }}>
            货币基金
            <NumberInput value={snapshot.money_fund_amount} onChange={v => updateSnapshot({ money_fund_amount: v })} width={160} />
          </label>
          <label style={{ display: 'grid', gap: 5, fontSize: 12, color: 'var(--text-muted)' }}>
            现金
            <NumberInput value={snapshot.cash_amount} onChange={v => updateSnapshot({ cash_amount: v })} width={160} />
          </label>
          <label style={{ display: 'grid', gap: 5, fontSize: 12, color: 'var(--text-muted)' }}>
            今日最多动用
            <NumberInput value={snapshot.usable_cash_amount} onChange={v => updateSnapshot({ usable_cash_amount: v })} width={160} />
          </label>
          <label style={{ display: 'grid', gap: 5, fontSize: 12, color: 'var(--text-muted)' }}>
            货基最低保留
            <NumberInput value={snapshot.reserve_floor_amount} onChange={v => updateSnapshot({ reserve_floor_amount: v })} width={160} />
          </label>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 10, flexWrap: 'wrap' }}>
          <div style={{ fontSize: 13, fontWeight: 750 }}>基金持仓明细</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={addHolding}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 10px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', cursor: 'pointer', fontSize: 12, fontWeight: 700 }}
            >
              <Plus size={14} /> 新增
            </button>
            <button
              onClick={saveSnapshot}
              disabled={saving}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 12px', borderRadius: 8, border: 'none', background: '#4f46e5', color: 'white', cursor: saving ? 'not-allowed' : 'pointer', fontSize: 12, fontWeight: 750 }}
            >
              {saving ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Save size={14} />}
              保存并生成建议
            </button>
          </div>
        </div>

        <div style={{ maxHeight: 360, overflow: 'auto', border: '1px solid var(--border-color)', borderRadius: 10 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 980 }}>
            <thead style={{ position: 'sticky', top: 0, background: 'var(--bg-primary)', zIndex: 1 }}>
              <tr>
                {['基金代码', '基金名称', '金额', '收益金额', '收益率', '资产桶', '资金流板块', '操作'].map(label => (
                  <th key={label} style={{ textAlign: 'left', padding: '10px 9px', fontSize: 12, color: 'var(--text-muted)', borderBottom: '1px solid var(--border-color)' }}>{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {snapshot.holdings.map((h, index) => (
                <tr key={`${h.name}-${index}`}>
                  <td style={{ padding: '8px 9px', borderBottom: '1px solid var(--border-color)' }}>
                    <input
                      value={h.fund_code ?? ''}
                      onChange={e => updateHolding(index, { fund_code: e.target.value })}
                      placeholder="如 000001"
                      style={{ width: 100, padding: '7px 9px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: 12 }}
                    />
                  </td>
                  <td style={{ padding: '8px 9px', borderBottom: '1px solid var(--border-color)' }}>
                    <input
                      value={h.name}
                      onChange={e => updateHolding(index, { name: e.target.value })}
                      style={{ width: '100%', minWidth: 280, padding: '7px 9px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: 12 }}
                    />
                  </td>
                  <td style={{ padding: '8px 9px', borderBottom: '1px solid var(--border-color)' }}>
                    <NumberInput value={h.amount} onChange={v => updateHolding(index, { amount: v })} />
                  </td>
                  <td style={{ padding: '8px 9px', borderBottom: '1px solid var(--border-color)' }}>
                    <SignedNumberInput value={h.profit_amount} onChange={v => updateHolding(index, { profit_amount: v })} />
                  </td>
                  <td style={{ padding: '8px 9px', borderBottom: '1px solid var(--border-color)' }}>
                    <SignedNumberInput value={h.profit_rate} onChange={v => updateHolding(index, { profit_rate: v })} width={82} step={0.01} />
                  </td>
                  <td style={{ padding: '8px 9px', borderBottom: '1px solid var(--border-color)' }}>
                    <select
                      value={h.bucket}
                      onChange={e => updateHolding(index, { bucket: e.target.value as Holding['bucket'] })}
                      style={{ width: 150, padding: '7px 9px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontSize: 12 }}
                    >
                      {HOLDING_BUCKETS.map(([key, meta]) => (
                        <option key={key} value={key}>{meta.name}</option>
                      ))}
                    </select>
                  </td>
                  <td style={{ padding: '8px 9px', borderBottom: '1px solid var(--border-color)' }}>
                    <SectorSelect
                      value={h.flow_sector_name}
                      options={data.sector_options ?? []}
                      onChange={value => updateHolding(index, { flow_sector_name: value })}
                    />
                  </td>
                  <td style={{ padding: '8px 9px', borderBottom: '1px solid var(--border-color)' }}>
                    <button
                      onClick={() => removeHolding(index)}
                      title="删除持仓"
                      style={{ width: 30, height: 30, borderRadius: 8, border: '1px solid #dc262633', background: '#dc262612', color: '#dc2626', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 14, marginBottom: 16 }}>
        <Card>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>总资产快照</span>
            <WalletCards size={16} color="#6366f1" />
          </div>
          <div style={{ fontSize: 25, fontWeight: 800, marginTop: 8 }}>{money(data.total_assets)}</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>基金 + 货币基金 + 现金</div>
        </Card>
        <Card>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>今日主信号</span>
            <Gauge size={16} color="#d97706" />
          </div>
          <div style={{ fontSize: 24, fontWeight: 800, marginTop: 8, color: actionColor(data.signal === 'conservative_add' ? 'add' : data.signal === 'trim_watch' ? 'trim' : 'merge_watch') }}>{data.signal_label}</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>今日加仓上限 {money(data.daily_add_cap)}</div>
        </Card>
        <Card>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>黄金状态</span>
            <ShieldCheck size={16} color="#d97706" />
          </div>
          <div style={{ fontSize: 24, fontWeight: 800, marginTop: 8 }}>{pct(gold.pct)}</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>目标 {pct(gold.target)}，接近目标时暂停追加</div>
        </Card>
        <Card>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>现金安全垫</span>
            <Coins size={16} color="#16a34a" />
          </div>
          <div style={{ fontSize: 24, fontWeight: 800, marginTop: 8 }}>{pct(cash.pct)}</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>可动用预算 {money(data.cash_budget)}</div>
        </Card>
      </div>

      <Card style={{ marginBottom: 16, borderColor: '#d9770633', background: 'linear-gradient(180deg, var(--bg-primary), rgba(217,119,6,0.04))' }}>
        <SectionTitle icon={Target} title="今日明确操作建议" subtitle={data.formula} />
        <div style={{ marginBottom: 16 }}>
          <SectionTitle icon={Waves} title="市场确认层" subtitle="仓位偏离决定该不该动；大资金动向和板块资金流决定今天动不动、动多少" />
          <MarketConfirmationPanel confirmations={data.market_confirmations ?? {}} />
        </div>
        <div className="portfolio-signal-grid" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.1fr) minmax(280px, 0.9fr)', gap: 18 }}>
          <div style={{ display: 'grid', gap: 12 }}>
            {data.actions.slice(0, 8).map(action => {
              const Icon = action.type === 'add' || action.type === 'add_watch' ? ArrowUpRight : ArrowDownRight;
              return (
                <div key={`${action.type}-${action.target_name}`} style={{ display: 'flex', gap: 10 }}>
                  <Icon size={18} color={actionColor(action.type)} style={{ marginTop: 2, flexShrink: 0 }} />
                  <div>
                    <div style={{ fontSize: 15, fontWeight: 800, color: 'var(--text-primary)' }}>
                      {actionLabel(action.type)}：{action.target_name}
                      {action.amount > 0 && <span style={{ color: actionColor(action.type) }}> {money(action.amount)}</span>}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginTop: 5 }}>
                      <MarketBadge confirmation={action.market_confirmation} />
                      {action.raw_amount !== undefined && action.raw_amount !== action.amount && (
                        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>仓位原始建议 {money(action.raw_amount)} → 市场修正 {money(action.amount)}</span>
                      )}
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>{action.reason}</div>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 1 }}>{action.execution}</div>
                  </div>
                </div>
              );
            })}
          </div>
          <div style={{ background: 'var(--bg-secondary)', borderRadius: 10, padding: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 10 }}>
              <div style={{ fontSize: 13, fontWeight: 750 }}>规则锁定</div>
              <button
                onClick={runClaudeReview}
                disabled={reviewing}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '5px 9px', borderRadius: 8, border: '1px solid #6366f144', background: '#6366f114', color: '#4f46e5', cursor: reviewing ? 'not-allowed' : 'pointer', fontSize: 12, fontWeight: 700 }}
              >
                {reviewing ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> : <ShieldCheck size={13} />}
                风控审阅
              </button>
            </div>
            {[
              `风格：${data.policy.style}`,
              `慢调仓系数：${Number(data.policy.slow_factor) * 100}%`,
              `1000 元以下允许清仓`,
              `1000-5000 元只给合并观察`,
              `单日加仓不超过 ${money(Number(data.policy.daily_add_cap))}`,
              `主题单次调仓 ${data.policy.single_theme_rebalance_pct}`,
              `盘中估值动作上限 ${money(data.intraday_policy.max_action)}`,
              `市场确认只放大/降级，不单独触发买卖`,
            ].map(item => (
              <div key={item} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, fontSize: 12, color: 'var(--text-secondary)' }}>
                <CheckCircle2 size={13} color="#16a34a" />
                {item}
              </div>
            ))}
            {claudeReview && (
              <div style={{ marginTop: 12, padding: 12, borderRadius: 10, background: 'var(--bg-primary)', border: '1px solid var(--border-color)', whiteSpace: 'pre-wrap', fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                {claudeReview}
              </div>
            )}
          </div>
        </div>
      </Card>

      <Card style={{ marginBottom: 16 }}>
        <SectionTitle
          icon={Gauge}
          title="单基金盘中估值建议"
          subtitle={`${data.intraday_policy.role} 数据源：天天基金/Eastmoney 估值接口`}
        />
        <FundRecommendationTable
          items={data.fund_recommendations ?? []}
          sectorOptions={data.sector_options ?? []}
          onSectorChange={updateHoldingSectorByName}
        />
      </Card>

      <div className="portfolio-two-column" style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 0.95fr) minmax(360px, 1.05fr)', gap: 16, marginBottom: 16 }}>
        <Card>
          <SectionTitle icon={Layers} title="当前资产桶占比" subtitle="按已保存快照实时归桶" />
          <AllocationBar rows={rows} />
          <div style={{ marginTop: 18, display: 'grid', gap: 9 }}>
            {rows.map(row => (
              <div key={row.bucket} style={{ display: 'grid', gridTemplateColumns: '92px 1fr auto', alignItems: 'center', gap: 10 }}>
                <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{row.name}</span>
                <div style={{ height: 7, background: 'var(--bg-tertiary)', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${Math.min(100, row.pct * 100)}%`, background: BUCKETS[row.bucket].color, borderRadius: 4 }} />
                </div>
                <strong style={{ fontSize: 12 }}>{pct(row.pct)}</strong>
              </div>
            ))}
          </div>
        </Card>
        <Card>
          <SectionTitle icon={Target} title="目标偏离证据" subtitle="左侧为低配，右侧为超配" />
          <TargetDeviation rows={rows} />
        </Card>
      </div>

      <Card style={{ marginBottom: 16 }}>
        <SectionTitle icon={BadgeInfo} title="仓位证据表" subtitle="偏离金额是加仓/减仓建议的基础，不直接等于一次性交易金额" />
        <EvidenceTable rows={rows} />
      </Card>

      <div className="portfolio-two-column" style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 1fr) minmax(320px, 1fr)', gap: 16 }}>
        <Card>
          <SectionTitle icon={WalletCards} title="前 8 大持仓" subtitle="观察组合真正由哪些仓位驱动" />
          {topHoldings.map(h => (
            <div key={h.name} style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 12, alignItems: 'center', padding: '9px 0', borderBottom: '1px solid var(--border-color)' }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 650, color: 'var(--text-primary)' }}>{h.name}</div>
                <div style={{ fontSize: 11, color: BUCKETS[h.bucket].color, marginTop: 2 }}>{BUCKETS[h.bucket].name}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 13, fontWeight: 750 }}>{money(h.amount)}</div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{pct(h.pct)}</div>
              </div>
            </div>
          ))}
        </Card>
        <Card>
          <SectionTitle icon={PieChart} title="回测代理说明" subtitle="真实场外基金缺历史净值时，用 ETF 桶代理，不做假回填" />
          <div style={{ display: 'grid', gap: 10, fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.7 }}>
            <div><strong style={{ color: 'var(--text-primary)' }}>当前截图代理：</strong>现金、黄金、海外、A股/主题/资源按资产桶映射，用于模拟当前防守组合。</div>
            <div><strong style={{ color: 'var(--text-primary)' }}>目标框架：</strong>沪深300 25%、中证500 10%、纳指 15%、创业板/主题 10%、黄金 25%、现金 15%。</div>
            <div><strong style={{ color: 'var(--text-primary)' }}>已接入：</strong>A股宽基参考托底大盘信号，行业/资源基金参考板块资金流；黄金和海外仓暂不混用A股资金流。</div>
          </div>
          <Link
            to="/backtest?portfolioA=current"
            onClick={() => snapshot && saveBacktestProxy(snapshot)}
            style={{ marginTop: 14, display: 'inline-flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderRadius: 9, background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', textDecoration: 'none', fontSize: 13, fontWeight: 700 }}
          >
            <PieChart size={15} />
            用当前持仓打开回测
          </Link>
        </Card>
      </div>

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @media (max-width: 980px) {
          .portfolio-signal-grid,
          .portfolio-two-column {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </div>
  );
}
