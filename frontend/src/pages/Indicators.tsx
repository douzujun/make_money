import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, AlertCircle, TrendingUp, Gauge } from 'lucide-react';
import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

interface IndicatorTemplate {
  id: string;
  name: string;
  indicator_type: string;
  category?: string;
}

interface Indicator {
  id: number;
  template_id: string;
  asset_id?: string;
  name: string;
  description?: string;
  template?: IndicatorTemplate;
}

interface IndicatorValue {
  id: number;
  indicator_id: number;
  date: string;
  value: number;
  grade?: string;
  grade_label?: string;
}

const typeConfig: Record<string, { label: string; color: string; bg: string; icon: React.ElementType }> = {
  fear_greed: { label: '恐慌贪婪', color: '#8b5cf6', bg: 'rgba(139, 92, 246, 0.1)', icon: AlertCircle },
  vix: { label: 'VIX', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.1)', icon: Gauge },
  ma200: { label: 'MA200', color: '#3b82f6', bg: 'rgba(59, 130, 246, 0.1)', icon: TrendingUp },
  pe: { label: '市盈率', color: '#22c55e', bg: 'rgba(34, 197, 94, 0.1)', icon: Activity },
  metric: { label: '技术指标', color: '#3b82f6', bg: 'rgba(59, 130, 246, 0.1)', icon: TrendingUp },
  sentiment: { label: '情绪指标', color: '#8b5cf6', bg: 'rgba(139, 92, 246, 0.1)', icon: AlertCircle },
  volatility: { label: '波动率', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.1)', icon: Gauge },
};

// label 字段仅作后备；渲染时优先使用 API 返回的 grade_label
const levelConfig: Record<string, { label: string; color: string; bg: string }> = {
  // Fear & Greed 指数
  extreme_fear:  { label: '极度恐惧', color: '#dc2626', bg: 'rgba(220, 38, 38, 0.1)' },
  fear:          { label: '恐惧',     color: '#ea580c', bg: 'rgba(234, 88, 12, 0.1)' },
  neutral:       { label: '中性',     color: '#6b7280', bg: 'rgba(107, 114, 128, 0.1)' },
  greed:         { label: '贪婪',     color: '#22c55e', bg: 'rgba(34, 197, 94, 0.1)' },
  extreme_greed: { label: '极度贪婪', color: '#16a34a', bg: 'rgba(22, 163, 74, 0.1)' },
  // MA200 偏离度
  very_low:    { label: '极度低估', color: '#16a34a', bg: 'rgba(22, 163, 74, 0.1)' },
  low:         { label: '低估',     color: '#22c55e', bg: 'rgba(34, 197, 94, 0.1)' },
  medium_low:  { label: '偏低',     color: '#84cc16', bg: 'rgba(132, 204, 22, 0.1)' },
  medium:      { label: '合理',     color: '#6b7280', bg: 'rgba(107, 114, 128, 0.1)' },
  medium_high: { label: '偏高',     color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.1)' },
  high:        { label: '高估',     color: '#ef4444', bg: 'rgba(239, 68, 68, 0.1)' },
  very_high:   { label: '极度高估', color: '#dc2626', bg: 'rgba(220, 38, 38, 0.1)' },
  // 波动率指数（VIX / VXN / VXD / OVX / GVZ）
  calm:     { label: '极度平静', color: '#22c55e', bg: 'rgba(34, 197, 94, 0.1)' },
  normal:   { label: '正常波动', color: '#6b7280', bg: 'rgba(107, 114, 128, 0.1)' },
  elevated: { label: '波动加剧', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.1)' },
  panic:    { label: '极度恐慌', color: '#dc2626', bg: 'rgba(220, 38, 38, 0.1)' },
};

export default function Indicators() {
  const navigate = useNavigate();
  const [indicators, setIndicators] = useState<Indicator[]>([]);
  const [values, setValues] = useState<Record<number, IndicatorValue>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchIndicators();
  }, []);

  const fetchIndicators = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/v1/indicators`);
      setIndicators(response.data);

      const valuesMap: Record<number, IndicatorValue> = {};
      for (const indicator of response.data) {
        try {
          const valueRes = await axios.get(`${API_BASE_URL}/api/v1/indicators/${indicator.id}/values?limit=1`);
          if (valueRes.data.length > 0) {
            valuesMap[indicator.id] = valueRes.data[0];
          }
        } catch (e) {
          console.error(`Failed to fetch values for indicator ${indicator.id}`);
        }
      }
      setValues(valuesMap);
    } catch (error) {
      console.error('Failed to fetch indicators:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="animate-fade-in">
      {/* Indicators Grid */}
      <div
        style={{
          background: 'var(--bg-primary)',
          borderRadius: '20px',
          border: '1px solid var(--border-color)',
          overflow: 'hidden',
        }}
      >
        {loading ? (
          <div style={{ padding: '80px', textAlign: 'center', color: 'var(--text-muted)' }}>
            加载中...
          </div>
        ) : indicators.length === 0 ? (
          <div style={{ padding: '80px', textAlign: 'center' }}>
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
              <Activity size={32} color="var(--text-muted)" />
            </div>
            <p style={{ color: 'var(--text-muted)', fontSize: '16px' }}>暂无指标数据</p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: 'var(--bg-secondary)' }}>
                  <th
                    style={{
                      padding: '16px 20px',
                      textAlign: 'left',
                      fontSize: '13px',
                      fontWeight: 600,
                      color: 'var(--text-secondary)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.5px',
                    }}
                  >
                    指标名称
                  </th>
                  <th
                    style={{
                      padding: '16px 20px',
                      textAlign: 'left',
                      fontSize: '13px',
                      fontWeight: 600,
                      color: 'var(--text-secondary)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.5px',
                    }}
                  >
                    类型
                  </th>
                  <th
                    style={{
                      padding: '16px 20px',
                      textAlign: 'left',
                      fontSize: '13px',
                      fontWeight: 600,
                      color: 'var(--text-secondary)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.5px',
                    }}
                  >
                    关联标的
                  </th>
                  <th
                    style={{
                      padding: '16px 20px',
                      textAlign: 'left',
                      fontSize: '13px',
                      fontWeight: 600,
                      color: 'var(--text-secondary)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.5px',
                    }}
                  >
                    当前值
                  </th>
                  <th
                    style={{
                      padding: '16px 20px',
                      textAlign: 'center',
                      fontSize: '13px',
                      fontWeight: 600,
                      color: 'var(--text-secondary)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.5px',
                    }}
                  >
                    档位
                  </th>
                  <th
                    style={{
                      padding: '16px 20px',
                      textAlign: 'left',
                      fontSize: '13px',
                      fontWeight: 600,
                      color: 'var(--text-secondary)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.5px',
                    }}
                  >
                    日期
                  </th>
                </tr>
              </thead>
              <tbody>
                {indicators.map((indicator, index) => {
                  const indicatorType = indicator.template?.indicator_type || 'metric';
                  const config = typeConfig[indicatorType] || typeConfig['metric'];
                  const Icon = config.icon;
                  const value = values[indicator.id];
                  const level = value?.grade ? levelConfig[value.grade] : null;

                  return (
                    <tr
                      key={indicator.id}
                      onClick={() => navigate(`/indicators/${indicator.id}`)}
                      style={{
                        borderBottom:
                          index < indicators.length - 1 ? '1px solid var(--border-color)' : 'none',
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
                      <td style={{ padding: '20px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                          <div
                            style={{
                              width: '40px',
                              height: '40px',
                              borderRadius: '10px',
                              background: config.bg,
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              color: config.color,
                            }}
                          >
                            <Icon size={20} />
                          </div>
                          <span
                            style={{
                              fontSize: '15px',
                              fontWeight: 600,
                              color: 'var(--text-primary)',
                            }}
                          >
                            {indicator.name}
                          </span>
                        </div>
                      </td>
                      <td style={{ padding: '20px' }}>
                        <span
                          style={{
                            fontSize: '13px',
                            fontWeight: 500,
                            padding: '4px 10px',
                            borderRadius: '6px',
                            background: config.bg,
                            color: config.color,
                          }}
                        >
                          {config.label}
                        </span>
                      </td>
                      <td style={{ padding: '20px' }}>
                        <span style={{ fontSize: '14px', color: 'var(--text-secondary)' }}>
                          {indicator.asset_id || '-'}
                        </span>
                      </td>
                      <td style={{ padding: '20px' }}>
                        <span
                          style={{
                            fontSize: '18px',
                            fontWeight: 700,
                            color: 'var(--text-primary)',
                          }}
                        >
                          {value ? value.value.toFixed(2) : '-'}
                        </span>
                      </td>
                      <td style={{ padding: '20px', textAlign: 'center' }}>
                        {level ? (
                          <span
                            style={{
                              fontSize: '12px',
                              fontWeight: 600,
                              padding: '4px 12px',
                              borderRadius: '20px',
                              background: level.bg,
                              color: level.color,
                            }}
                          >
                            {value.grade_label || level.label}
                          </span>
                        ) : (
                          '-'
                        )}
                      </td>
                      <td style={{ padding: '20px' }}>
                        <span style={{ fontSize: '14px', color: 'var(--text-muted)' }}>
                          {value ? value.date : '-'}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
