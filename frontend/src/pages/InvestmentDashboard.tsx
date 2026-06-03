import { useEffect, useState } from 'react';
import axios from 'axios';
import { TrendingUp, TrendingDown, Minus, RefreshCw } from 'lucide-react';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

interface ScoreBlock {
  score: number | null;
  grade: string | null;
  grade_label: string;
  value: number | null;
  value_text: string | null;
  date: string | null;
}

interface MarketData {
  id: string;
  name: string;
  asset_id: string;
  long_term: ScoreBlock;
  daily: ScoreBlock;
}

// ── Score → color gradient ──────────────────────────────────────────
function scoreColor(score: number | null): string {
  if (score === null) return '#6b7280';
  if (score <= 20) return '#22c55e';   // oversold / undervalued → green (opportunity)
  if (score <= 35) return '#84cc16';
  if (score <= 50) return '#6b7280';   // neutral → grey
  if (score <= 65) return '#f59e0b';   // slightly elevated → amber
  if (score <= 80) return '#ef4444';   // high → red (caution)
  return '#dc2626';                    // extreme → dark red
}

function scoreBg(score: number | null): string {
  if (score === null) return 'rgba(107,114,128,0.1)';
  if (score <= 20) return 'rgba(34,197,94,0.12)';
  if (score <= 35) return 'rgba(132,204,22,0.12)';
  if (score <= 50) return 'rgba(107,114,128,0.1)';
  if (score <= 65) return 'rgba(245,158,11,0.12)';
  if (score <= 80) return 'rgba(239,68,68,0.12)';
  return 'rgba(220,38,38,0.12)';
}

function ScoreBar({ score }: { score: number | null }) {
  const pct = score ?? 0;
  const color = scoreColor(score);
  return (
    <div style={{ marginTop: '8px' }}>
      <div
        style={{
          height: '6px',
          borderRadius: '3px',
          background: 'var(--bg-tertiary, rgba(0,0,0,0.08))',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            height: '100%',
            width: `${pct}%`,
            background: color,
            borderRadius: '3px',
            transition: 'width 0.6s ease',
          }}
        />
      </div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          marginTop: '4px',
          fontSize: '11px',
          color: 'var(--text-muted)',
        }}
      >
        <span>低估/超卖</span>
        <span>中性</span>
        <span>高估/超买</span>
      </div>
    </div>
  );
}

function ScoreChip({ block, label }: { block: ScoreBlock; label: string }) {
  const color = scoreColor(block.score);
  const bg = scoreBg(block.score);
  return (
    <div style={{ flex: 1 }}>
      <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px', fontWeight: 500 }}>
        {label}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px', flexWrap: 'wrap' }}>
        <span
          style={{
            fontSize: '28px',
            fontWeight: 700,
            color,
            lineHeight: 1,
          }}
        >
          {block.score ?? '—'}
        </span>
        <span style={{ fontSize: '14px', color: 'var(--text-muted)' }}>/100</span>
        <span
          style={{
            fontSize: '12px',
            fontWeight: 600,
            padding: '2px 10px',
            borderRadius: '20px',
            background: bg,
            color,
          }}
        >
          {block.grade_label}
        </span>
      </div>
      <ScoreBar score={block.score} />
      <div style={{ marginTop: '8px', fontSize: '12px', color: 'var(--text-muted)' }}>
        {block.value_text || (block.value !== null ? String(block.value) : '')}
        {block.date && (
          <span style={{ marginLeft: '6px', opacity: 0.7 }}>{block.date}</span>
        )}
      </div>
    </div>
  );
}

const MARKET_META: Record<string, { emoji: string; desc: string }> = {
  a_shares:  { emoji: '🇨🇳', desc: '沪深300 · A股大盘' },
  hk_stocks: { emoji: '🏦', desc: '恒生指数 · 港股大盘' },
  gold:      { emoji: '🟡', desc: 'COMEX黄金 · 避险资产' },
  oil:       { emoji: '🛢️', desc: 'WTI原油 · 经济活力' },
};

function MarketCard({ market }: { market: MarketData }) {
  const meta = MARKET_META[market.id] || { emoji: '📊', desc: market.asset_id };

  const ltScore = market.long_term.score;
  const dailyScore = market.daily.score;

  // Combined signal icon
  let SignalIcon = Minus;
  let signalColor = '#6b7280';
  if (ltScore !== null && dailyScore !== null) {
    const avg = (ltScore + dailyScore) / 2;
    if (avg <= 40) { SignalIcon = TrendingUp; signalColor = '#22c55e'; }
    else if (avg >= 65) { SignalIcon = TrendingDown; signalColor = '#ef4444'; }
  }

  return (
    <div
      style={{
        background: 'var(--bg-primary)',
        border: '1px solid var(--border-color)',
        borderRadius: '20px',
        padding: '28px',
        display: 'flex',
        flexDirection: 'column',
        gap: '20px',
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <div style={{ fontSize: '32px', lineHeight: 1 }}>{meta.emoji}</div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: '17px', fontWeight: 700, color: 'var(--text-primary)' }}>
            {market.name}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
            {meta.desc}
          </div>
        </div>
        <div
          style={{
            width: '36px',
            height: '36px',
            borderRadius: '10px',
            background: `${signalColor}20`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: signalColor,
          }}
        >
          <SignalIcon size={18} />
        </div>
      </div>

      {/* Divider */}
      <div style={{ height: '1px', background: 'var(--border-color)' }} />

      {/* Scores */}
      <div style={{ display: 'flex', gap: '24px' }}>
        <ScoreChip block={market.long_term} label="长期（MA200趋势）" />
        <div style={{ width: '1px', background: 'var(--border-color)' }} />
        <ScoreChip block={market.daily} label="今日（情绪/波动）" />
      </div>

      {/* Interpretation hint */}
      <InterpretationHint lt={market.long_term} daily={market.daily} />
    </div>
  );
}

function InterpretationHint({ lt, daily }: { lt: ScoreBlock; daily: ScoreBlock }) {
  if (lt.score === null || daily.score === null) return null;

  let hint = '';
  let hintColor = '#6b7280';

  if (lt.score <= 50 && daily.score <= 40) {
    hint = '长期低估 + 短期超卖 → 历史上较好的买入时机';
    hintColor = '#22c55e';
  } else if (lt.score >= 65 && daily.score >= 65) {
    hint = '长期偏高 + 短期超买 → 注意风险，可考虑减仓';
    hintColor = '#ef4444';
  } else if (lt.score <= 50 && daily.score >= 65) {
    hint = '长期低估但短期过热 → 可持仓，等待回调再加仓';
    hintColor = '#f59e0b';
  } else if (lt.score >= 65 && daily.score <= 40) {
    hint = '长期偏高但短期超卖 → 短线反弹机会，注意长期风险';
    hintColor = '#8b5cf6';
  } else {
    hint = '处于中性区间，可维持现有仓位';
    hintColor = '#6b7280';
  }

  return (
    <div
      style={{
        padding: '10px 14px',
        borderRadius: '10px',
        background: `${hintColor}15`,
        borderLeft: `3px solid ${hintColor}`,
        fontSize: '13px',
        color: hintColor,
        fontWeight: 500,
      }}
    >
      {hint}
    </div>
  );
}

export default function InvestmentDashboard() {
  const [markets, setMarkets] = useState<MarketData[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<string>('');

  const fetchData = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_BASE_URL}/api/v1/dashboard/investment`);
      setMarkets(res.data.markets);
      setLastUpdated(new Date().toLocaleTimeString('zh-CN'));
    } catch (e) {
      console.error('Failed to fetch dashboard:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  return (
    <div className="animate-fade-in">
      {/* Title bar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '24px',
        }}
      >
        <div>
          <h1
            style={{
              fontSize: '22px',
              fontWeight: 700,
              color: 'var(--text-primary)',
              margin: 0,
            }}
          >
            投资仪表盘
          </h1>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)', margin: '4px 0 0' }}>
            基于 MA200 + RSI/波动率的每日市场评分，独立判断 · 不构成投资建议
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {lastUpdated && (
            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              更新于 {lastUpdated}
            </span>
          )}
          <button
            onClick={fetchData}
            disabled={loading}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 16px',
              borderRadius: '10px',
              border: '1px solid var(--border-color)',
              background: 'var(--bg-secondary)',
              color: 'var(--text-secondary)',
              cursor: loading ? 'not-allowed' : 'pointer',
              fontSize: '13px',
              fontWeight: 500,
            }}
          >
            <RefreshCw size={14} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
            刷新
          </button>
        </div>
      </div>

      {/* Legend */}
      <div
        style={{
          background: 'var(--bg-primary)',
          border: '1px solid var(--border-color)',
          borderRadius: '14px',
          padding: '16px 20px',
          marginBottom: '24px',
          display: 'flex',
          gap: '28px',
          flexWrap: 'wrap',
          alignItems: 'center',
        }}
      >
        <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>
          评分说明：
        </span>
        {[
          { range: '0–35', label: '低估/超卖', color: '#22c55e' },
          { range: '35–50', label: '偏低/中性', color: '#84cc16' },
          { range: '50–65', label: '中性/偏高', color: '#6b7280' },
          { range: '65–80', label: '高估/超买', color: '#f59e0b' },
          { range: '80–100', label: '极度高估', color: '#dc2626' },
        ].map(({ range, label, color }) => (
          <div key={range} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <div style={{ width: '10px', height: '10px', borderRadius: '50%', background: color }} />
            <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              {range} {label}
            </span>
          </div>
        ))}
      </div>

      {/* Market Grid */}
      {loading ? (
        <div style={{ padding: '80px', textAlign: 'center', color: 'var(--text-muted)' }}>
          加载中...
        </div>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(480px, 1fr))',
            gap: '20px',
          }}
        >
          {markets.map((m) => (
            <MarketCard key={m.id} market={m} />
          ))}
        </div>
      )}

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
