import { useState, useEffect } from 'react';
import { Outlet, Link, useLocation } from 'react-router-dom';
import {
  LayoutDashboard, Database, Activity, Star,
  Bell, BarChart3, LineChart, BarChart2, ChevronRight, Menu, X, TrendingUp, PieChart,
  WalletCards,
} from 'lucide-react';

const menuItems = [
  { path: '/',            label: '仪表盘',    icon: LayoutDashboard },
  { path: '/investment',  label: '投资仪表盘', icon: LineChart },
  { path: '/sector-flow', label: '板块资金流', icon: BarChart2 },
  { path: '/big-money',   label: '大资金动向', icon: TrendingUp },
  { path: '/portfolio-center', label: '组合配置中枢', icon: WalletCards },
  { path: '/backtest',    label: '组合回测',   icon: PieChart },
  { path: '/assets',      label: '标的列表',  icon: Database },
  { path: '/watchlist',   label: '关注列表',  icon: Star },
  { path: '/indicators',  label: '指标中心',  icon: Activity },
];

export default function MainLayout() {
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const check = () => {
      const mobile = window.innerWidth < 1024;
      setIsMobile(mobile);
      setSidebarOpen(!mobile);
    };
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);

  const from = (location.state as { from?: string })?.from;
  const isFromWatchlist = from === 'watchlist';

  const isActive = (path: string) => {
    if (path === '/') return location.pathname === '/';
    if (location.pathname.startsWith('/assets/')) {
      if (path === '/watchlist' && isFromWatchlist) return true;
      if (path === '/assets' && !isFromWatchlist) return true;
      return false;
    }
    return location.pathname.startsWith(path);
  };

  return (
    <div style={{ display: 'flex', height: '100vh', background: 'var(--bg-secondary)' }}>

      {/* ── Sidebar ──────────────────────────────────────── */}
      <aside style={{
        width: sidebarOpen ? 220 : 0,
        flexShrink: 0,
        height: '100vh',
        background: 'var(--bg-primary)',
        borderRight: sidebarOpen ? '1px solid var(--border-color)' : 'none',
        display: 'flex',
        flexDirection: 'column',
        position: isMobile ? 'fixed' : 'sticky',
        top: 0,
        left: 0,
        zIndex: isMobile ? 99 : 'auto' as any,
        overflow: 'hidden',
        transition: 'width 0.25s ease',
      }}>

        {/* Logo */}
        <div style={{
          padding: '20px 20px 16px',
          borderBottom: '1px solid var(--border-color)',
          flexShrink: 0,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{
              width: 38, height: 38, borderRadius: 10,
              background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0,
            }}>
              <BarChart3 size={20} color="white" />
            </div>
            <div style={{ whiteSpace: 'nowrap', overflow: 'hidden' }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.4px' }}>
                Vestoria
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: '-1px' }}>数据终端</div>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav style={{ flex: 1, padding: '12px', overflowY: 'auto' }}>
          <div style={{
            fontSize: 10, fontWeight: 700, color: 'var(--text-muted)',
            letterSpacing: '0.8px', textTransform: 'uppercase',
            margin: '4px 8px 10px', whiteSpace: 'nowrap',
          }}>
            主菜单
          </div>
          {menuItems.map(({ path, label, icon: Icon }) => {
            const active = isActive(path);
            return (
              <Link
                key={path}
                to={path}
                onClick={() => isMobile && setSidebarOpen(false)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '9px 12px', marginBottom: 2, borderRadius: 10,
                  textDecoration: 'none', fontSize: 13, fontWeight: 500,
                  whiteSpace: 'nowrap',
                  color: active ? '#6366f1' : 'var(--text-secondary)',
                  background: active
                    ? 'linear-gradient(135deg, rgba(99,102,241,0.12) 0%, rgba(139,92,246,0.06) 100%)'
                    : 'transparent',
                  border: active ? '1px solid rgba(99,102,241,0.18)' : '1px solid transparent',
                  transition: 'all 0.15s',
                }}
                onMouseEnter={e => {
                  if (!active) (e.currentTarget as HTMLElement).style.background = 'var(--bg-secondary)';
                }}
                onMouseLeave={e => {
                  if (!active) (e.currentTarget as HTMLElement).style.background = 'transparent';
                }}
              >
                <Icon size={17} />
                <span style={{ flex: 1 }}>{label}</span>
                {active && <ChevronRight size={13} style={{ opacity: 0.4 }} />}
              </Link>
            );
          })}
        </nav>

      </aside>

      {/* Mobile overlay */}
      {isMobile && sidebarOpen && (
        <div
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 98 }}
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* ── Right side ───────────────────────────────────── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>

        {/* Thin top bar */}
        <header style={{
          height: 52, flexShrink: 0,
          background: 'var(--bg-primary)',
          borderBottom: '1px solid var(--border-color)',
          display: 'flex', alignItems: 'center',
          padding: '0 20px', gap: 10,
        }}>
          <button
            onClick={() => setSidebarOpen(v => !v)}
            title={sidebarOpen ? '收起侧边栏' : '展开侧边栏'}
            style={{
              width: 34, height: 34, borderRadius: 8,
              border: '1px solid var(--border-color)', background: 'var(--bg-secondary)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              cursor: 'pointer', color: 'var(--text-secondary)', flexShrink: 0,
            }}
            onMouseEnter={e => {
              (e.currentTarget as HTMLElement).style.borderColor = 'var(--primary-color)';
              (e.currentTarget as HTMLElement).style.color = 'var(--primary-color)';
            }}
            onMouseLeave={e => {
              (e.currentTarget as HTMLElement).style.borderColor = 'var(--border-color)';
              (e.currentTarget as HTMLElement).style.color = 'var(--text-secondary)';
            }}
          >
            {sidebarOpen ? <X size={16} /> : <Menu size={16} />}
          </button>

          <div style={{ flex: 1 }} />

          <button style={{
            width: 34, height: 34, borderRadius: 8,
            border: '1px solid var(--border-color)', background: 'var(--bg-secondary)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: 'pointer', color: 'var(--text-secondary)',
          }}>
            <Bell size={16} />
          </button>
        </header>

        {/* Content */}
        <main style={{ flex: 1, overflowY: 'auto', padding: '24px 28px' }}>
          <div style={{ maxWidth: 1400, margin: '0 auto' }}>
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
