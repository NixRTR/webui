/**
 * Sidebar navigation with Flowbite - Mobile responsive with hamburger menu
 */
import { useState, useEffect } from 'react';
import { Sidebar as FlowbiteSidebar } from 'flowbite-react';
import { Link, useLocation } from 'react-router-dom';
import {
  HiChartPie,
  HiViewBoards,
  HiUsers,
  HiClock,
  HiLogout,
  HiBookOpen,
  HiTrendingUp,
  HiBell,
  HiGlobe,
  HiServer,
  HiCog,
  HiShieldCheck,
  HiArrowRight,
  HiRefresh,
  HiLightningBolt,
  HiInformationCircle,
  HiDocumentText,
} from 'react-icons/hi';
import { FaGithub } from 'react-icons/fa';
import { apiClient } from '../../api/client';

const SIDEBAR_STORAGE_KEY = 'webui-sidebar-expanded';

function loadSidebarExpanded(): { network: boolean; system: boolean; config: boolean } {
  try {
    const s = localStorage.getItem(SIDEBAR_STORAGE_KEY);
    if (s) {
      const o = JSON.parse(s) as Record<string, boolean>;
      return {
        network: !!o.network,
        system: !!o.system,
        config: !!o.config,
      };
    }
  } catch {
    // ignore
  }
  return { network: false, system: false, config: false };
}

function saveSidebarExpanded(expanded: { network: boolean; system: boolean; config: boolean }) {
  try {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, JSON.stringify(expanded));
  } catch {
    // ignore
  }
}

interface SidebarProps {
  onLogout: () => void;
  isOpen: boolean;
  onClose: () => void;
}

export function Sidebar({ onLogout, isOpen, onClose }: SidebarProps) {
  const location = useLocation();
  const [githubStats, setGitHubStats] = useState<{ stars: number; forks: number } | null>(null);
  const [networkExpanded, setNetworkExpanded] = useState(() => loadSidebarExpanded().network);
  const [systemExpanded, setSystemExpanded] = useState(() => loadSidebarExpanded().system);
  const [configExpanded, setConfigExpanded] = useState(() => loadSidebarExpanded().config);

  useEffect(() => {
    const fetchGitHubStats = async () => {
      try {
        const stats = await apiClient.getGitHubStats();
        setGitHubStats(stats);
      } catch (error) {
        console.error('Failed to fetch GitHub stats:', error);
        setGitHubStats({ stars: 0, forks: 0 });
      }
    };
    fetchGitHubStats();
  }, []);

  const handleItemClick = () => {
    if (window.innerWidth < 1650) {
      onClose();
    }
  };

  const isActive = (path: string) => location.pathname === path;
  const isParentActive = (path: string, children?: Array<{ path: string }>) => {
    if (isActive(path)) return true;
    if (children) {
      return children.some(child => location.pathname.startsWith(child.path) || (child.path.includes('?') ? false : location.pathname === child.path));
    }
    return false;
  };

  const networkChildren = [
    { path: '/network', label: 'Charts', icon: HiViewBoards },
    { path: '/devices', label: 'Devices', icon: HiUsers },
    { path: '/device-usage', label: 'Usage', icon: HiChartPie },
  ];
  const systemChildren = [
    { path: '/system', label: 'Charts', icon: HiChartPie },
    { path: '/settings/worker-status', label: 'Worker Status', icon: HiServer },
    { path: '/speedtest', label: 'Speedtest', icon: HiLightningBolt },
    { path: '/system-info', label: 'System Info', icon: HiInformationCircle },
    { path: '/system/logs', label: 'Logs', icon: HiDocumentText },
  ];
  const configChildren = [
    { path: '/settings/cake', label: 'CAKE', icon: HiTrendingUp },
    { path: '/settings/dhcp', label: 'DHCP', icon: HiServer },
    { path: '/settings/dns', label: 'DNS', icon: HiGlobe },
    { path: '/settings/blocklists-whitelist', label: 'Blocklists', icon: HiShieldCheck },
    { path: '/settings/port-forwarding', label: 'Port Forwarding', icon: HiArrowRight },
    { path: '/settings/dyndns', label: 'Dynamic DNS', icon: HiRefresh },
    { path: '/settings/apprise', label: 'Apprise', icon: HiBell },
  ];

  const isNetworkActive = ['/network', '/devices', '/device-usage'].some(p => location.pathname === p || (p !== '/network' && location.pathname.startsWith(p)));
  const isSystemActive = location.pathname === '/system' || location.pathname === '/system-info' || location.pathname === '/speedtest' || location.pathname === '/settings/worker-status' || location.pathname.startsWith('/system/logs');
  const isConfigActive = isParentActive('/settings', configChildren);

  useEffect(() => {
    if (isNetworkActive) setNetworkExpanded(true);
  }, [isNetworkActive]);
  useEffect(() => {
    if (isSystemActive) setSystemExpanded(true);
  }, [isSystemActive]);
  useEffect(() => {
    if (isConfigActive) setConfigExpanded(true);
  }, [isConfigActive]);

  const toggleNetwork = () => {
    setNetworkExpanded((prev) => {
      const next = !prev;
      saveSidebarExpanded({
        network: next,
        system: systemExpanded,
        config: configExpanded,
      });
      return next;
    });
  };
  const toggleSystem = () => {
    setSystemExpanded((prev) => {
      const next = !prev;
      saveSidebarExpanded({
        network: networkExpanded,
        system: next,
        config: configExpanded,
      });
      return next;
    });
  };
  const toggleConfig = () => {
    setConfigExpanded((prev) => {
      const next = !prev;
      saveSidebarExpanded({
        network: networkExpanded,
        system: systemExpanded,
        config: next,
      });
      return next;
    });
  };

  return (
    <>
      {/* Overlay - visible below 1650px */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black bg-opacity-50 z-40 xl-custom:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar */}
      <div
        className={`
          fixed xl-custom:static inset-y-0 left-0 z-50
          transform transition-transform duration-300 ease-in-out
          xl-custom:transform-none
          ${isOpen ? 'translate-x-0' : '-translate-x-full xl-custom:translate-x-0'}
        `}
      >
        <FlowbiteSidebar aria-label="Sidebar with navigation" className="h-full">
          <FlowbiteSidebar.Items>
            <FlowbiteSidebar.ItemGroup>
              <FlowbiteSidebar.Item
                as={Link}
                to="/dashboard"
                icon={HiChartPie}
                active={location.pathname === '/dashboard'}
                onClick={handleItemClick}
              >
                Dashboard
              </FlowbiteSidebar.Item>

              {/* Network - collapsible */}
              <li>
                <button
                  type="button"
                  onClick={toggleNetwork}
                  className={`flex items-center w-full p-2 rounded-lg ${
                    isNetworkActive
                      ? 'text-blue-600 bg-blue-50 dark:text-blue-500 dark:bg-gray-700'
                      : 'text-gray-900 hover:bg-gray-100 dark:text-white dark:hover:bg-gray-700'
                  }`}
                >
                  <HiViewBoards className="w-5 h-5 mr-3" />
                  <span>Network</span>
                </button>
                {networkExpanded && (
                  <ul className="ml-6 mt-2 space-y-1">
                    {networkChildren.map((child) => {
                      const IconComponent = child.icon;
                      return (
                        <li key={child.path}>
                          <Link
                            to={child.path}
                            onClick={handleItemClick}
                            className={`flex items-center p-2 rounded-lg text-sm ${
                              isActive(child.path)
                                ? 'text-blue-600 bg-blue-50 dark:text-blue-500 dark:bg-gray-700'
                                : 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700'
                            }`}
                          >
                            <IconComponent className="w-4 h-4 mr-2" />
                            {child.label}
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </li>

              {/* System - collapsible (Charts, Worker Status, Speedtest, System Info, Logs) */}
              <li>
                <button
                  type="button"
                  onClick={toggleSystem}
                  className={`flex items-center w-full p-2 rounded-lg ${
                    isSystemActive
                      ? 'text-blue-600 bg-blue-50 dark:text-blue-500 dark:bg-gray-700'
                      : 'text-gray-900 hover:bg-gray-100 dark:text-white dark:hover:bg-gray-700'
                  }`}
                >
                  <HiClock className="w-5 h-5 mr-3" />
                  <span>System</span>
                </button>
                {systemExpanded && (
                  <ul className="ml-6 mt-2 space-y-1">
                    {systemChildren.map((child) => {
                      const IconComponent = child.icon;
                      return (
                        <li key={child.path}>
                          <Link
                            to={child.path}
                            onClick={handleItemClick}
                            className={`flex items-center p-2 rounded-lg text-sm ${
                              isActive(child.path) || (child.path === '/system/logs' && location.pathname.startsWith('/system/logs'))
                                ? 'text-blue-600 bg-blue-50 dark:text-blue-500 dark:bg-gray-700'
                                : 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700'
                            }`}
                          >
                            <IconComponent className="w-4 h-4 mr-2" />
                            {child.label}
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </li>

              {/* Settings - collapsible */}
              <li>
                <button
                  type="button"
                  onClick={toggleConfig}
                  className={`flex items-center w-full p-2 rounded-lg ${
                    isConfigActive
                      ? 'text-blue-600 bg-blue-50 dark:text-blue-500 dark:bg-gray-700'
                      : 'text-gray-900 hover:bg-gray-100 dark:text-white dark:hover:bg-gray-700'
                  }`}
                >
                  <HiCog className="w-5 h-5 mr-3" />
                  <span>Settings</span>
                </button>
                {configExpanded && (
                  <ul className="ml-6 mt-2 space-y-1">
                    {configChildren.map((child) => {
                      const IconComponent = child.icon;
                      return (
                        <li key={child.path}>
                          <Link
                            to={child.path}
                            onClick={handleItemClick}
                            className={`flex items-center p-2 rounded-lg text-sm ${
                              isActive(child.path)
                                ? 'text-blue-600 bg-blue-50 dark:text-blue-500 dark:bg-gray-700'
                                : 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700'
                            }`}
                          >
                            <IconComponent className="w-4 h-4 mr-2" />
                            {child.label}
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </li>

            <FlowbiteSidebar.Item
              as={Link}
              to="/notifications"
              icon={HiBell}
              active={location.pathname === '/notifications'}
              onClick={handleItemClick}
            >
              Notifications
            </FlowbiteSidebar.Item>
            </FlowbiteSidebar.ItemGroup>

            <FlowbiteSidebar.ItemGroup>
              <FlowbiteSidebar.Item
                icon={HiLogout}
                style={{ cursor: 'pointer' }}
                onClick={() => {
                  handleItemClick();
                  onLogout();
                }}
              >
                Logout
              </FlowbiteSidebar.Item>
              <FlowbiteSidebar.Item
                href="/docs"
                target="_blank"
                rel="noopener noreferrer"
                icon={HiBookOpen}
                as="a"
                onClick={handleItemClick}
              >
                Documentation
              </FlowbiteSidebar.Item>
              <FlowbiteSidebar.Item
                href="https://github.com/NixRTR/nixos-router"
                target="_blank"
                rel="noopener noreferrer"
                icon={FaGithub}
                as="a"
              >
                <div className="flex items-center justify-between w-full">
                  <span>GitHub</span>
                  {githubStats !== null && (
                    <span className="ml-2 text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap">
                      ⭐ {githubStats.stars} 🍴 {githubStats.forks}
                    </span>
                  )}
                </div>
              </FlowbiteSidebar.Item>
            </FlowbiteSidebar.ItemGroup>
          </FlowbiteSidebar.Items>
        </FlowbiteSidebar>
      </div>
    </>
  );
}

