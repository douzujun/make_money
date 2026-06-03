import { useState, useEffect, useCallback } from 'react';
import { Star, Plus, TrendingUp, TrendingDown, Trash2, ExternalLink, RefreshCw, AlertCircle, Download, Loader2, Info, ChevronDown, ChevronUp } from 'lucide-react';

// 波动率指数：监测对象说明
const VOLATILITY_DESC: Record<string, string> = {
  'VIX':  '监测标普500大盘',
  '^VIX': '监测标普500大盘',
  'VXN':  '监测纳斯达克科技股',
  '^VXN': '监测纳斯达克科技股',
  'VXD':  '监测道琼斯蓝筹股',
  '^VXD': '监测道琼斯蓝筹股',
  'OVX':  '监测原油市场',
  '^OVX': '监测原油市场',
  'GVZ':  '监测黄金市场',
  '^GVZ': '监测黄金市场',
};
import { Link, useNavigate, useLocation } from 'react-router-dom';
import axios from 'axios';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import Sparkline from '@/components/Sparkline';
import CategoryTabs from '@/components/assets/CategoryTabs';
import type { AssetCategory } from '@/types/assets';

// Enable dayjs plugins
dayjs.extend(relativeTime);

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

// Constants
const AUTO_REFRESH_INTERVAL = 60 * 1000; // 60 seconds

interface Asset {
  id: string;
  symbol: string;
  name: string;
  asset_type: string;
  exchange?: string;
  currency?: string;
  is_active: boolean;
  created_at: string;
}

interface PriceInfo {
  asset_id: string;
  symbol: string;
  close: number;
  open?: number;
  high?: number;
  low?: number;
  volume?: number;
  change?: number;
  change_percent?: number;
  date: string;
  last_updated: string;
  data_freshness: 'fresh' | 'stale' | 'outdated';
}

interface MergedAsset extends Asset {
  price?: PriceInfo;
}

interface BackfillResult {
  asset_id: string;
  status: string;
  records: number;
  message: string;
}

interface SparklinePoint {
  date: string;
  close: number;
}

interface SparklineData {
  asset_id: string;
  symbol: string;
  data: SparklinePoint[];
  days: number;
  change_percent?: number;
}

interface AssetWithSparkline extends MergedAsset {
  sparkline?: SparklineData;
}

export default function Watchlist() {
  const [assets, setAssets] = useState<AssetWithSparkline[]>([]);
  const [loading, setLoading] = useState(true);
  const [priceLoading, setPriceLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [backfillingIds, setBackfillingIds] = useState<Set<string>>(new Set());
  const [backfillResults, setBackfillResults] = useState<Record<string, string>>({});
  const [activeCategory, setActiveCategory] = useState<AssetCategory>('equities');
  const [showHint, setShowHint] = useState(false);

  // Filter assets by category
  const filteredAssets = assets.filter(asset => {
    const type = asset.asset_type.toLowerCase();
    switch (activeCategory) {
      case 'equities':
        return ['equity', 'etf', 'stock', 'index'].includes(type);
      case 'crypto':
        return type === 'crypto';
      case 'commodities':
        return type === 'commodity';
      default:
        return true;
    }
  });

  // Count assets without price data (from filtered)
  const missingPriceCount = filteredAssets.filter(a => !a.price).length;
  const hasMissingPrices = missingPriceCount > 0;
  const hasWatchlist = filteredAssets.length > 0;

  // Load watchlist (assets + prices + sparklines)
  const loadWatchlist = useCallback(async () => {
    setLoading(true);
    try {
      // Step 1: Load assets
      const assetsResponse = await axios.get<Asset[]>(`${API_BASE_URL}/api/v1/assets?watched_only=true`);
      const assetsData = assetsResponse.data || [];

      // Step 2: Load prices and sparklines (if we have assets)
      if (assetsData.length > 0) {
        const assetIds = assetsData.map(a => a.id).join(',');
        
        try {
          // Fetch both latest prices and sparkline data in parallel
          const [pricesResponse, sparklineResponse] = await Promise.all([
            axios.get<PriceInfo[]>(
              `${API_BASE_URL}/api/v1/prices/latest/batch?asset_ids=${assetIds}`
            ),
            axios.get<SparklineData[]>(
              `${API_BASE_URL}/api/v1/prices/sparkline/batch?asset_ids=${assetIds}&days=7`
            ).catch(() => ({ data: [] })) // Sparkline is optional
          ]);
          
          const pricesData = pricesResponse.data || [];
          const sparklineData = sparklineResponse.data || [];
          
          // Merge assets with prices and sparklines
          const priceMap = new Map(pricesData.map(p => [p.asset_id, p]));
          const sparklineMap = new Map(sparklineData.map(s => [s.asset_id, s]));
          
          const mergedAssets = assetsData.map(asset => ({
            ...asset,
            price: priceMap.get(asset.id),
            sparkline: sparklineMap.get(asset.id)
          }));
          
          setAssets(mergedAssets);
          setLastRefresh(new Date());
        } catch (priceError) {
          console.error('Failed to load prices:', priceError);
          setAssets(assetsData.map(asset => ({ ...asset })));
        }
      } else {
        setAssets([]);
      }
    } catch (error) {
      console.error('Failed to load watchlist:', error);
      setAssets([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // Manual refresh prices only
  const refreshPrices = useCallback(async () => {
    if (assets.length === 0 || priceLoading) return;
    
    setPriceLoading(true);
    setRefreshing(true);
    try {
      const assetIds = assets.map(a => a.id).join(',');
      const pricesResponse = await axios.get<PriceInfo[]>(
        `${API_BASE_URL}/api/v1/prices/latest/batch?asset_ids=${assetIds}`
      );
      const pricesData = pricesResponse.data || [];
      
      const priceMap = new Map(pricesData.map(p => [p.asset_id, p]));
      setAssets(prev => prev.map(asset => ({
        ...asset,
        price: priceMap.get(asset.id) || asset.price
      })));
      setLastRefresh(new Date());
    } catch (error) {
      console.error('Failed to refresh prices:', error);
    } finally {
      setPriceLoading(false);
      setRefreshing(false);
    }
  }, [assets.length, priceLoading]);

  // Trigger update job based on active category and refresh prices
  const triggerUpdate = useCallback(async () => {
    if (priceLoading) return;
    
    setPriceLoading(true);
    setRefreshing(true);
    try {
      // Step 1: Determine job based on active category
      // crypto -> update_crypto, equities/commodities -> update_us_market
      const jobId = activeCategory === 'crypto' ? 'update_crypto' : 'update_us_market';
      
      // Step 2: Trigger the appropriate job
      await axios.post(`${API_BASE_URL}/api/v1/scheduler/jobs/${jobId}/run`);
      
      // Step 3: Wait a bit for the job to process (2 seconds)
      await new Promise(resolve => setTimeout(resolve, 2000));
      
      // Step 4: Refresh prices
      const assetIds = assets.map(a => a.id).join(',');
      const pricesResponse = await axios.get<PriceInfo[]>(
        `${API_BASE_URL}/api/v1/prices/latest/batch?asset_ids=${assetIds}`
      );
      const pricesData = pricesResponse.data || [];
      
      const priceMap = new Map(pricesData.map(p => [p.asset_id, p]));
      setAssets(prev => prev.map(asset => ({
        ...asset,
        price: priceMap.get(asset.id) || asset.price
      })));
      setLastRefresh(new Date());
    } catch (error) {
      console.error('Failed to trigger update:', error);
    } finally {
      setPriceLoading(false);
      setRefreshing(false);
    }
  }, [assets, priceLoading, activeCategory]);

  // Backfill single asset
  const backfillAsset = useCallback(async (assetId: string) => {
    if (backfillingIds.has(assetId)) return;
    
    setBackfillingIds(prev => new Set([...prev, assetId]));
    setBackfillResults(prev => ({ ...prev, [assetId]: '' }));
    
    try {
      const response = await axios.post<BackfillResult>(
        `${API_BASE_URL}/api/v1/update/backfill/${assetId}?days=365`
      );
      
      setBackfillResults(prev => ({ 
        ...prev, 
        [assetId]: `✅ 已获取 ${response.data.records} 条记录` 
      }));
      
      // Refresh prices after backfill
      await refreshPrices();
    } catch (error) {
      console.error(`Failed to backfill ${assetId}:`, error);
      setBackfillResults(prev => ({ 
        ...prev, 
        [assetId]: '❌ 获取失败，请重试' 
      }));
    } finally {
      setBackfillingIds(prev => {
        const next = new Set(prev);
        next.delete(assetId);
        return next;
      });
    }
  }, [backfillingIds, refreshPrices]);

  // Backfill all missing assets
  const backfillAllMissing = useCallback(async () => {
    const missingAssets = assets.filter(a => !a.price);
    if (missingAssets.length === 0) return;
    
    for (const asset of missingAssets) {
      await backfillAsset(asset.id);
      // Small delay to avoid rate limiting
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
  }, [assets, backfillAsset]);

  // Initial load
  useEffect(() => {
    loadWatchlist();
  }, [loadWatchlist]);

  // Auto refresh prices
  useEffect(() => {
    if (assets.length === 0) return;
    
    const intervalId = setInterval(() => {
      refreshPrices();
    }, AUTO_REFRESH_INTERVAL);
    
    return () => clearInterval(intervalId);
  }, [assets.length, refreshPrices]);

  // Delete asset
  const handleDelete = async (id: string) => {
    if (deletingId) return;
    
    setDeletingId(id);
    try {
      await axios.delete(`${API_BASE_URL}/api/v1/assets/${id}`);
      setAssets((prev) => prev.filter((a) => a.id !== id));
    } catch (error) {
      console.error('Failed to delete asset:', error);
    } finally {
      setDeletingId(null);
    }
  };

  // Format price with currency
  const formatPrice = (price: number, currency?: string) => {
    const symbol = currency === 'USD' ? '$' : currency === 'CNY' ? '¥' : '';
    return `${symbol}${price.toLocaleString('en-US', { 
      minimumFractionDigits: 2, 
      maximumFractionDigits: 4 
    })}`;
  };

  // Format change percent
  const formatChange = (change?: number, changePercent?: number) => {
    if (changePercent === undefined || changePercent === null) return null;
    const isPositive = changePercent >= 0;
    const sign = isPositive ? '+' : '';
    return {
      text: `${sign}${changePercent.toFixed(2)}%`,
      subText: change !== undefined ? `(${sign}${change.toFixed(2)})` : '',
      isPositive,
      color: isPositive ? '#22c55e' : '#ef4444',
      bg: isPositive ? 'rgba(34, 197, 94, 0.1)' : 'rgba(239, 68, 68, 0.1)'
    };
  };

  // Get asset type display
  const getAssetTypeLabel = (type: string) => {
    const labels: Record<string, string> = {
      equity: '股票',
      crypto: '加密货币',
      etf: 'ETF',
      commodity: '大宗商品',
      forex: '外汇',
    };
    return labels[type] || type;
  };

  // Get asset type color
  const getAssetTypeColor = (type: string) => {
    const colors: Record<string, { bg: string; color: string }> = {
      equity: { bg: 'rgba(99, 102, 241, 0.1)', color: '#6366f1' },
      crypto: { bg: 'rgba(245, 158, 11, 0.1)', color: '#f59e0b' },
      etf: { bg: 'rgba(34, 197, 94, 0.1)', color: '#22c55e' },
      commodity: { bg: 'rgba(239, 68, 68, 0.1)', color: '#ef4444' },
      forex: { bg: 'rgba(6, 182, 212, 0.1)', color: '#06b6d4' },
    };
    return colors[type] || { bg: 'rgba(99, 102, 241, 0.1)', color: '#6366f1' };
  };

  // Get freshness indicator
  // fresh: 0-2 days, stale: 2-5 days, outdated: >5 days
  const getFreshnessIndicator = (freshness?: string) => {
    switch (freshness) {
      case 'fresh':
        return { color: '#22c55e', label: '最新' };
      case 'stale':
        return { color: '#f59e0b', label: '滞后' };
      case 'outdated':
        return { color: '#ef4444', label: '过期' };
      default:
        return { color: '#9ca3af', label: '无数据' };
    }
  };

  return (
    <div className="animate-fade-in">
      {/* Header Row: Category Tabs (left) + Actions (right) */}
      <div style={{ marginBottom: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '16px' }}>
        {/* Category Tabs (left) */}
        <CategoryTabs activeCategory={activeCategory} onChange={setActiveCategory} />

        {/* Actions (right) */}
        <div style={{ display: 'flex', gap: '12px', flexShrink: 0 }}>
          {/* Refresh Button */}
          {hasWatchlist && (
            <button
              onClick={triggerUpdate}
              disabled={refreshing}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '8px',
                padding: '10px 20px',
                borderRadius: '12px',
                border: '1px solid var(--border-color)',
                background: 'var(--bg-secondary)',
                color: 'var(--text-primary)',
                fontSize: '14px',
                fontWeight: 600,
                cursor: refreshing ? 'not-allowed' : 'pointer',
                opacity: refreshing ? 0.7 : 1,
                transition: 'all 0.3s ease',
              }}
              title={activeCategory === 'crypto' ? '触发 update_crypto 任务并刷新价格' : '触发 update_us_market 任务并刷新价格'}
            >
              <RefreshCw size={18} className={refreshing ? 'animate-spin' : ''} />
              刷新
            </button>
          )}
          <Link
            to="/assets"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px',
              padding: '10px 20px',
              borderRadius: '12px',
              border: 'none',
              background: 'var(--primary-color)',
              color: 'white',
              fontSize: '14px',
              fontWeight: 600,
              textDecoration: 'none',
              transition: 'all 0.3s ease',
            }}
          >
            <Plus size={18} />
            添加标的
          </Link>
        </div>
      </div>

      {/* Missing Data Alert */}
      {hasMissingPrices && (
        <div
          style={{
            marginBottom: '24px',
            padding: '16px 20px',
            background: 'rgba(245, 158, 11, 0.1)',
            border: '1px solid rgba(245, 158, 11, 0.3)',
            borderRadius: '12px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '16px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <AlertCircle size={20} color="#f59e0b" />
            <div>
              <p style={{ margin: '0 0 2px 0', fontSize: '14px', fontWeight: 600, color: '#f59e0b' }}>
                {missingPriceCount} 个标的缺少价格数据
              </p>
              <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-muted)' }}>
                点击右侧按钮获取历史价格数据
              </p>
            </div>
          </div>
          <button
            onClick={backfillAllMissing}
            disabled={backfillingIds.size > 0}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px',
              padding: '8px 16px',
              borderRadius: '8px',
              border: 'none',
              background: '#f59e0b',
              color: 'white',
              fontSize: '13px',
              fontWeight: 600,
              cursor: backfillingIds.size > 0 ? 'not-allowed' : 'pointer',
              opacity: backfillingIds.size > 0 ? 0.7 : 1,
              whiteSpace: 'nowrap',
            }}
          >
            {backfillingIds.size > 0 ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                获取中...
              </>
            ) : (
              <>
                <Download size={16} />
                获取全部数据
              </>
            )}
          </button>
        </div>
      )}

      {/* Watchlist Content */}

      {/* Volatility Hint Card — equities tab only */}
      {activeCategory === 'equities' && hasWatchlist && (
        <div style={{
          marginBottom: '16px',
          borderRadius: '12px',
          border: '1px solid rgba(99,102,241,0.25)',
          background: 'rgba(99,102,241,0.05)',
          overflow: 'hidden',
        }}>
          {/* Header row (always visible) */}
          <div
            onClick={() => setShowHint(v => !v)}
            style={{
              padding: '10px 16px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              cursor: 'pointer',
              userSelect: 'none',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Info size={15} color="#6366f1" />
              <span style={{ fontSize: '13px', fontWeight: 600, color: '#6366f1' }}>
                波动率指数解读指南
              </span>
              <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                — 数值越高 = 市场越恐慌
              </span>
            </div>
            {showHint
              ? <ChevronUp size={15} color="#6366f1" />
              : <ChevronDown size={15} color="#6366f1" />}
          </div>

          {/* Expandable content */}
          {showHint && (
            <div style={{
              padding: '0 16px 14px',
              borderTop: '1px solid rgba(99,102,241,0.15)',
            }}>
              {/* Threshold table */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                gap: '8px',
                marginTop: '12px',
                marginBottom: '12px',
              }}>
                {[
                  { range: 'VIX < 20',  label: '低波动',   desc: '市场平静，正常操作',          color: '#22c55e' },
                  { range: 'VIX 20–30', label: '波动加剧', desc: '风险上升，谨慎仓位',           color: '#f59e0b' },
                  { range: 'VIX > 30',  label: '市场恐慌', desc: '历史上往往是左侧布局时机',    color: '#ef4444' },
                  { range: 'VIX > 40',  label: '极度恐慌', desc: '类2008/2020，可能是历史底部', color: '#dc2626' },
                ].map(item => (
                  <div key={item.range} style={{
                    padding: '10px 12px',
                    borderRadius: '8px',
                    background: 'var(--bg-primary)',
                    border: `1px solid ${item.color}33`,
                  }}>
                    <div style={{ fontSize: '12px', fontWeight: 700, color: item.color, marginBottom: '4px' }}>
                      {item.range}
                    </div>
                    <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '2px' }}>
                      {item.label}
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: '1.4' }}>
                      {item.desc}
                    </div>
                  </div>
                ))}
              </div>

              {/* Tips */}
              <div style={{
                display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px',
              }}>
                {[
                  { icon: '📊', text: 'VXN 通常高于 VIX，科技股波动本来就大；VXD 略低于 VIX，蓝筹股更稳健。' },
                  { icon: '🛢️', text: 'OVX 飙升（>60）往往伴随油价大幅震荡，配合 CL=F 价格走势一起判断方向。' },
                  { icon: '🥇', text: 'GVZ 上升 + 黄金价格上涨 = 避险资金涌入；GVZ 上升但黄金跌 = 市场抛售一切。' },
                  { icon: '💡', text: '各指数历史分位比绝对值更有参考意义，点进详情页看历史走势图。' },
                ].map(tip => (
                  <div key={tip.icon} style={{
                    display: 'flex', gap: '8px', alignItems: 'flex-start',
                    padding: '8px 10px', borderRadius: '8px',
                    background: 'var(--bg-primary)',
                    fontSize: '12px', color: 'var(--text-secondary)', lineHeight: '1.5',
                  }}>
                    <span style={{ flexShrink: 0 }}>{tip.icon}</span>
                    <span>{tip.text}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {loading ? (        <div
          style={{
            background: 'var(--bg-primary)',
            borderRadius: '20px',
            border: '1px solid var(--border-color)',
            padding: '60px',
            textAlign: 'center',
          }}
        >
          <p style={{ color: 'var(--text-muted)' }}>加载中...</p>
        </div>
      ) : !hasWatchlist ? (
        <div
          style={{
            background: 'var(--bg-primary)',
            borderRadius: '20px',
            border: '1px solid var(--border-color)',
            padding: '60px',
          }}
        >
          <div style={{ textAlign: 'center' }}>
            <div
              style={{
                width: '80px',
                height: '80px',
                borderRadius: '20px',
                background: 'var(--bg-secondary)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 20px',
              }}
            >
              <Star size={32} color="var(--text-muted)" />
            </div>
            <p
              style={{
                fontSize: '16px',
                fontWeight: 600,
                color: 'var(--text-primary)',
                marginBottom: '8px',
              }}
            >
              暂无关注标的
            </p>
            <p style={{ color: 'var(--text-muted)', marginBottom: '24px' }}>
              添加你感兴趣的标的到关注列表
            </p>
            <Link
              to="/assets"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '8px',
                padding: '12px 24px',
                borderRadius: '12px',
                border: 'none',
                background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
                color: 'white',
                fontSize: '14px',
                fontWeight: 600,
                textDecoration: 'none',
                transition: 'all 0.3s ease',
                boxShadow: '0 4px 14px rgba(99, 102, 241, 0.4)',
              }}
            >
              <Plus size={18} />
              去添加标的
            </Link>
          </div>
        </div>
      ) : (
        <div
          style={{
            background: 'var(--bg-primary)',
            borderRadius: '20px',
            border: '1px solid var(--border-color)',
            overflow: 'hidden',
          }}
        >
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'var(--bg-secondary)' }}>
                <th style={thStyle}>标的</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>价格</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>涨跌</th>
                <th style={{ ...thStyle, textAlign: 'center' }}>7日走势</th>
                <th style={thStyle}>类型</th>
                <th style={{ ...thStyle, textAlign: 'center' }}>状态</th>
                <th style={{ ...thStyle, textAlign: 'center' }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {filteredAssets.map((asset, index) => {
                const typeStyle = getAssetTypeColor(asset.asset_type);
                const change = asset.price ? formatChange(asset.price.change, asset.price.change_percent) : null;
                const freshness = getFreshnessIndicator(asset.price?.data_freshness);
                const isBackfilling = backfillingIds.has(asset.id);
                const backfillResult = backfillResults[asset.id];
                const hasNoPrice = !asset.price;
                
                return (
                  <tr
                    key={asset.id}
                    onClick={() => window.location.href = `/assets/${asset.id}`}
                    style={{
                      borderBottom:
                        index < filteredAssets.length - 1 ? '1px solid var(--border-color)' : 'none',
                      transition: 'background 0.2s',
                      cursor: 'pointer',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = 'var(--bg-secondary)';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = 'transparent';
                    }}
                  >
                    {/* Asset Info */}
                    <td style={tdStyle}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <div
                          style={{
                            width: '40px',
                            height: '40px',
                            borderRadius: '10px',
                            background: typeStyle.bg,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            color: typeStyle.color,
                            fontSize: '12px',
                            fontWeight: 600,
                          }}
                        >
                          {asset.symbol.slice(0, 2)}
                        </div>
                        <div>
                          <Link
                            to={`/assets/${asset.id}`}
                            state={{ from: 'watchlist' }}
                            style={{
                              fontSize: '15px',
                              fontWeight: 600,
                              color: 'var(--text-primary)',
                              textDecoration: 'none',
                              margin: '0 0 2px 0',
                              display: 'block',
                            }}
                          >
                            {asset.symbol}
                          </Link>
                          <p
                            style={{
                              fontSize: '13px',
                              color: 'var(--text-muted)',
                              margin: 0,
                            }}
                          >
                            {asset.name}
                          </p>
                          {VOLATILITY_DESC[asset.symbol] && (
                            <span style={{
                              fontSize: '11px',
                              color: '#6366f1',
                              marginTop: '2px',
                              display: 'block',
                              fontWeight: 500,
                            }}>
                              {VOLATILITY_DESC[asset.symbol]}
                            </span>
                          )}
                        </div>
                      </div>
                    </td>

                    {/* Price */}
                    <td style={{ ...tdStyle, textAlign: 'right' }}>
                      {asset.price ? (
                        <div>
                          <span
                            style={{
                              fontSize: '16px',
                              fontWeight: 700,
                              color: 'var(--text-primary)',
                            }}
                          >
                            {formatPrice(asset.price.close, asset.currency)}
                          </span>
                          <p
                            style={{
                              fontSize: '11px',
                              color: 'var(--text-muted)',
                              margin: '2px 0 0 0',
                            }}
                          >
                            {dayjs(asset.price.date).format('MM-DD')}
                          </p>
                        </div>
                      ) : backfillResult ? (
                        <span style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                          {backfillResult}
                        </span>
                      ) : (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            backfillAsset(asset.id);
                          }}
                          disabled={isBackfilling}
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '4px',
                            padding: '6px 12px',
                            borderRadius: '6px',
                            border: '1px dashed var(--border-color)',
                            background: 'transparent',
                            color: 'var(--text-muted)',
                            fontSize: '12px',
                            cursor: isBackfilling ? 'not-allowed' : 'pointer',
                            opacity: isBackfilling ? 0.7 : 1,
                          }}
                        >
                          {isBackfilling ? (
                            <Loader2 size={14} className="animate-spin" />
                          ) : (
                            <Download size={14} />
                          )}
                          获取数据
                        </button>
                      )}
                    </td>

                    {/* Change */}
                    <td style={{ ...tdStyle, textAlign: 'right' }}>
                      {change ? (
                        <div
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '4px',
                            padding: '4px 8px',
                            borderRadius: '6px',
                            background: change.bg,
                            color: change.color,
                            fontSize: '13px',
                            fontWeight: 600,
                          }}
                        >
                          {change.isPositive ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                          {change.text}
                        </div>
                      ) : asset.price ? (
                        <span style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
                          -
                        </span>
                      ) : (
                        <span style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
                          无数据
                        </span>
                      )}
                    </td>

                    {/* Sparkline - 7 Day Trend */}
                    <td style={{ ...tdStyle, textAlign: 'center' }}>
                      {asset.sparkline && asset.sparkline.data.length > 1 ? (
                        <Sparkline
                          data={asset.sparkline.data}
                          width={100}
                          height={32}
                          isPositive={(asset.sparkline.change_percent || 0) >= 0}
                        />
                      ) : (
                        <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>
                          -
                        </span>
                      )}
                    </td>

                    {/* Type */}
                    <td style={tdStyle}>
                      <span
                        style={{
                          fontSize: '12px',
                          fontWeight: 500,
                          padding: '4px 10px',
                          borderRadius: '6px',
                          background: typeStyle.bg,
                          color: typeStyle.color,
                        }}
                      >
                        {getAssetTypeLabel(asset.asset_type)}
                      </span>
                    </td>

                    {/* Data Freshness */}
                    <td style={{ ...tdStyle, textAlign: 'center' }}>
                      <div
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '4px',
                          fontSize: '12px',
                          color: freshness.color,
                        }}
                        title={`数据状态: ${freshness.label}\n最后更新: ${asset.price?.last_updated ? dayjs(asset.price.last_updated).format('YYYY-MM-DD HH:mm:ss') : '无'}`}
                      >
                        <span
                          style={{
                            width: '6px',
                            height: '6px',
                            borderRadius: '50%',
                            background: freshness.color,
                          }}
                        />
                        {freshness.label}
                      </div>
                    </td>

                    {/* Actions */}
                    <td style={{ ...tdStyle, textAlign: 'center' }}>
                      <div style={{ display: 'flex', gap: '8px', justifyContent: 'center' }}>
                        <button
                          onClick={(e) => e.stopPropagation()}
                          style={{
                            padding: '8px',
                            borderRadius: '8px',
                            border: 'none',
                            background: 'var(--bg-secondary)',
                            color: 'var(--text-secondary)',
                            cursor: 'pointer',
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                          }}
                          title="查看详情"
                        >
                          <ExternalLink size={16} />
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDelete(asset.id);
                          }}
                          disabled={deletingId === asset.id}
                          style={{
                            padding: '8px',
                            borderRadius: '8px',
                            border: 'none',
                            background: 'rgba(239, 68, 68, 0.1)',
                            color: '#ef4444',
                            cursor: deletingId === asset.id ? 'not-allowed' : 'pointer',
                            opacity: deletingId === asset.id ? 0.7 : 1,
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                          }}
                          title="删除"
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Data Status Footer */}
      {hasWatchlist && (
        <div
          style={{
            marginTop: '16px',
            padding: '12px 16px',
            background: 'var(--bg-secondary)',
            borderRadius: '12px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontSize: '13px',
            color: 'var(--text-muted)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <AlertCircle size={16} />
            <span>
              价格数据自动每 60 秒刷新一次。
              <span style={{ color: '#22c55e', marginLeft: '4px' }}>●</span> 最新(0-2天)
              <span style={{ color: '#f59e0b', marginLeft: '4px' }}>●</span> 滞后(2-5天)
              <span style={{ color: '#ef4444', marginLeft: '4px' }}>●</span> 过期(5天以上)
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <span>当前分类: <strong style={{ color: 'var(--text-primary)' }}>{filteredAssets.length}</strong> / 总计: {assets.length}</span>
            {lastRefresh && (
              <span>更新于 {dayjs(lastRefresh).fromNow()}</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// Style constants
const thStyle: React.CSSProperties = {
  padding: '14px 16px',
  textAlign: 'left',
  fontSize: '12px',
  fontWeight: 600,
  color: 'var(--text-secondary)',
  textTransform: 'uppercase',
  letterSpacing: '0.5px',
};

const tdStyle: React.CSSProperties = {
  padding: '14px 16px',
};
