import { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { ConfigProvider, theme } from 'antd';

// Pages
import Dashboard from '@/pages/Dashboard';
import Assets from '@/pages/Assets';
import AssetDetail from '@/pages/AssetDetail';
import Indicators from '@/pages/Indicators';
import IndicatorDetail from '@/pages/IndicatorDetail';
import Watchlist from '@/pages/Watchlist';
import InvestmentDashboard from '@/pages/InvestmentDashboard';
import SectorFlow from '@/pages/SectorFlow';
import BigMoney from '@/pages/BigMoney';
import Backtest from '@/pages/Backtest';
import PortfolioCenter from '@/pages/PortfolioCenter';

// Layouts
import MainLayout from '@/layouts/MainLayout';
import { useLocation } from 'react-router-dom';

function RouteTitleManager() {
  const location = useLocation();

  useEffect(() => {
    const path = location.pathname;
    let pageTitle = '数据终端';

    if (path === '/') {
      pageTitle = '仪表盘';
    } else if (path === '/investment') {
      pageTitle = '投资仪表盘';
    } else if (path === '/sector-flow') {
      pageTitle = '板块资金流';
    } else if (path === '/big-money') {
      pageTitle = '大资金动向';
    } else if (path === '/backtest') {
      pageTitle = '组合回测';
    } else if (path === '/portfolio-center') {
      pageTitle = '组合配置中枢';
    } else if (path === '/assets') {
      pageTitle = '标的列表';
    } else if (path.startsWith('/assets/')) {
      pageTitle = '标的详情';
    } else if (path === '/watchlist') {
      pageTitle = '关注列表';
    } else if (path === '/indicators') {
      pageTitle = '指标中心';
    } else if (path.startsWith('/indicators/')) {
      pageTitle = '指标详情';
    }

    document.title = `Vestoria - ${pageTitle}`;
  }, [location.pathname]);

  return null;
}

function App() {
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    setIsDark(mediaQuery.matches);

    const handler = (e: MediaQueryListEvent) => {
      setIsDark(e.matches);
    };
    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, []);

  return (
    <ConfigProvider
      theme={{
        algorithm: isDark ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: {
          colorPrimary: '#6366f1',
          colorBgBase: isDark ? '#0f172a' : '#ffffff',
          colorTextBase: isDark ? '#f8fafc' : '#0f172a',
        },
      }}
    >
      <Router>
        <RouteTitleManager />
        <Routes>
          <Route path="/login" element={<Navigate to="/" replace />} />
          <Route path="/" element={<MainLayout />}>
            <Route index element={<Dashboard />} />
            <Route path="investment" element={<InvestmentDashboard />} />
            <Route path="sector-flow" element={<SectorFlow />} />
            <Route path="big-money" element={<BigMoney />} />
            <Route path="portfolio-center" element={<PortfolioCenter />} />
            <Route path="backtest" element={<Backtest />} />
            <Route path="assets" element={<Assets />} />
            <Route path="assets/:id" element={<AssetDetail />} />
            <Route path="indicators" element={<Indicators />} />
            <Route path="indicators/:id" element={<IndicatorDetail />} />
            <Route path="watchlist" element={<Watchlist />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Router>
    </ConfigProvider>
  );
}

export default App;
