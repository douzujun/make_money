import { useState, useEffect } from 'react';
import { Loader2, Plus, Check, TrendingUp, TrendingDown } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

interface CommodityDef {
  id: string;
  nameEn: string;
  nameCn: string;
  unit: string;
  exchange: string;
  color: string;
  abbr: string;
}

interface PriceEntry {
  close: number;
  date: string;
}

interface CommodityRow {
  id: string;
  price: number | null;
  change: number | null;
  changePercent: number | null;
  loading: boolean;
  error: boolean;
}

const COMMODITIES: CommodityDef[] = [
  { id: 'GC=F', nameEn: 'Gold Futures',   nameCn: '黄金',    unit: 'USD/盎司',  exchange: 'COMEX', color: '#FFD700', abbr: 'AU'  },
  { id: 'SI=F', nameEn: 'Silver Futures', nameCn: '白银',    unit: 'USD/盎司',  exchange: 'COMEX', color: '#A8A9AD', abbr: 'AG'  },
  { id: 'CL=F', nameEn: 'WTI Crude Oil',  nameCn: 'WTI原油', unit: 'USD/桶',    exchange: 'NYMEX', color: '#8B6914', abbr: 'OIL' },
  { id: 'NG=F', nameEn: 'Natural Gas',    nameCn: '天然气',  unit: 'USD/MMBtu', exchange: 'NYMEX', color: '#E8834A', abbr: 'GAS' },
  { id: 'HG=F', nameEn: 'Copper Futures', nameCn: '铜',      unit: 'USD/磅',    exchange: 'COMEX', color: '#B87333', abbr: 'CU'  },
];

const initRow = (id: string): CommodityRow => ({
  id, price: null, change: null, changePercent: null, loading: true, error: false,
});

export default function CommoditiesPanel() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<Map<string, CommodityRow>>(
    () => new Map(COMMODITIES.map(c => [c.id, initRow(c.id)]))
  );
  const [addingId, setAddingId] = useState<string | null>(null);
  const [addedIds, setAddedIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      await Promise.all(COMMODITIES.map(c => ensureAsset(c)));
      if (cancelled) return;
      await Promise.all(COMMODITIES.map(c => fetchPrice(c.id, cancelled)));
    };
    load();
    return () => { cancelled = true; };
  }, []);

  const ensureAsset = async (c: CommodityDef) => {
    try {
      await axios.post(`${API_BASE_URL}/api/v1/assets`, {
        id: c.id,
        symbol: c.id,
        name: c.nameEn,
        asset_type: 'commodity',
        exchange: c.exchange,
        country: 'US',
        currency: 'USD',
        data_source: 'yfinance',
        source_symbol: c.id,
        is_active: true,
        is_watched: false,
      });
    } catch (e) {
      if (!axios.isAxiosError(e) || e.response?.status !== 409) {
        console.warn(`ensureAsset ${c.id}:`, e);
      }
    }
  };

  const fetchPrice = async (id: string, cancelled: boolean) => {
    try {
      const res = await axios.get<PriceEntry[]>(`${API_BASE_URL}/api/v1/prices/live`, {
        params: { asset_id: id, days: 5 },
      });
      if (cancelled) return;
      const data = res.data;
      if (!data.length) {
        setRows(prev => new Map(prev).set(id, { ...prev.get(id)!, loading: false, error: true }));
        return;
      }
      const latest = data[data.length - 1];
      const prev2 = data.length >= 2 ? data[data.length - 2] : null;
      const change = prev2 ? latest.close - prev2.close : null;
      const changePercent = prev2 && prev2.close ? (change! / prev2.close) * 100 : null;
      setRows(prev => new Map(prev).set(id, {
        id, price: latest.close, change, changePercent, loading: false, error: false,
      }));
    } catch {
      if (!cancelled) {
        setRows(prev => new Map(prev).set(id, { ...prev.get(id)!, loading: false, error: true }));
      }
    }
  };

  const handleAdd = async (c: CommodityDef) => {
    if (addingId || addedIds.has(c.id)) return;
    setAddingId(c.id);
    try {
      await axios.post(
        `${API_BASE_URL}/api/v1/update/backfill/${encodeURIComponent(c.id)}?days=365`
      );
      setAddedIds(prev => new Set([...prev, c.id]));
    } catch (e) {
      console.error('backfill failed:', e);
    } finally {
      setAddingId(null);
    }
  };

  const formatPrice = (price: number) =>
    `$${price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  const renderChange = (pct: number | null) => {
    if (pct === null) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
    const pos = pct >= 0;
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: '4px',
        padding: '4px 8px', borderRadius: '6px',
        background: pos ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)',
        color: pos ? '#22c55e' : '#ef4444',
        fontSize: '13px', fontWeight: 600,
      }}>
        {pos ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
        {pos ? '+' : ''}{pct.toFixed(2)}%
      </span>
    );
  };

  return (
    <div>
      <div style={{
        background: 'var(--bg-primary)',
        borderRadius: '16px',
        border: '1px solid var(--border-color)',
        overflow: 'hidden',
      }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: 'var(--bg-secondary)' }}>
              <th style={thStyle}>品种</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>最新价格</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>日涨跌</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>单位</th>
              <th style={{ ...thStyle, textAlign: 'center' }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {COMMODITIES.map((c, i) => {
              const row = rows.get(c.id)!;
              const isAdded = addedIds.has(c.id);
              const isAdding = addingId === c.id;

              return (
                <tr
                  key={c.id}
                  onClick={() => navigate(`/assets/${encodeURIComponent(c.id)}`)}
                  style={{
                    borderBottom: i < COMMODITIES.length - 1 ? '1px solid var(--border-color)' : 'none',
                    cursor: 'pointer',
                    transition: 'background 0.15s',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-secondary)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                >
                  <td style={tdStyle}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <div style={{
                        width: '40px', height: '40px', borderRadius: '10px', flexShrink: 0,
                        background: `${c.color}22`,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        color: c.color, fontSize: '11px', fontWeight: 700, letterSpacing: '0.5px',
                      }}>
                        {c.abbr}
                      </div>
                      <div>
                        <div style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)' }}>
                          {c.nameCn}
                        </div>
                        <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
                          {c.nameEn} · {c.exchange}
                        </div>
                      </div>
                    </div>
                  </td>

                  <td style={{ ...tdStyle, textAlign: 'right' }}>
                    {row.loading ? (
                      <Loader2 size={16} color="var(--text-muted)"
                        style={{ animation: 'spin 1s linear infinite', display: 'inline-block' }} />
                    ) : row.error ? (
                      <span style={{ color: 'var(--text-muted)', fontSize: '13px' }}>获取失败</span>
                    ) : (
                      <span style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>
                        {formatPrice(row.price!)}
                      </span>
                    )}
                  </td>

                  <td style={{ ...tdStyle, textAlign: 'right' }}>
                    {row.loading ? (
                      <span style={{ color: 'var(--text-muted)' }}>—</span>
                    ) : (
                      renderChange(row.changePercent)
                    )}
                  </td>

                  <td style={{ ...tdStyle, textAlign: 'right' }}>
                    <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>{c.unit}</span>
                  </td>

                  <td style={{ ...tdStyle, textAlign: 'center' }}>
                    <button
                      onClick={e => { e.stopPropagation(); handleAdd(c); }}
                      disabled={isAdding || isAdded}
                      style={{
                        display: 'inline-flex', alignItems: 'center', gap: '4px',
                        padding: '6px 14px', borderRadius: '8px', border: 'none',
                        background: isAdded ? '#22c55e' : c.color,
                        color: isAdded ? 'white' : (c.color === '#FFD700' || c.color === '#A8A9AD') ? '#1a1a1a' : 'white',
                        fontSize: '12px', fontWeight: 600,
                        cursor: isAdding || isAdded ? 'not-allowed' : 'pointer',
                        opacity: isAdding || isAdded ? 0.8 : 1,
                        transition: 'opacity 0.15s',
                      }}
                    >
                      {isAdding
                        ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} />
                        : isAdded
                          ? <Check size={13} />
                          : <Plus size={13} />}
                      {isAdded ? '已添加' : '加入关注'}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div style={{
        marginTop: '12px', padding: '10px 14px',
        background: 'var(--bg-secondary)', borderRadius: '10px',
        fontSize: '12px', color: 'var(--text-muted)',
      }}>
        数据来源：Yahoo Finance 期货合约（行情有15分钟延迟）· 点击任意行查看历史走势
      </div>
    </div>
  );
}

const thStyle: React.CSSProperties = {
  padding: '14px 16px', textAlign: 'left',
  fontSize: '12px', fontWeight: 600,
  color: 'var(--text-secondary)',
  textTransform: 'uppercase', letterSpacing: '0.5px',
};

const tdStyle: React.CSSProperties = {
  padding: '14px 16px',
};
