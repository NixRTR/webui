/**
 * Logs page - live view of systemd journal logs for configured services
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { Button, Card, Spinner } from 'flowbite-react';
import { HiRefresh, HiPlay, HiStop } from 'react-icons/hi';
import { Sidebar } from '../components/layout/Sidebar';
import { Navbar } from '../components/layout/Navbar';
import { useMetrics } from '../hooks/useMetrics';
import { apiClient } from '../api/client';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';
const LOG_SOURCES = [
  { id: 'system', label: 'System Log' },
  { id: 'dnsmasq-lan', label: 'LAN DNS/DHCP' },
  { id: 'dnsmasq-homelab', label: 'HOMELAB DNS/DHCP' },
  { id: 'nginx', label: 'Nginx' },
  { id: 'router-webui-backend', label: 'WebUI Backend' },
  { id: 'router-webui-celery-parallel', label: 'Parallel Celery Worker' },
  { id: 'router-webui-celery-sequential', label: 'Sequential Celery Worker' },
  { id: 'router-webui-celery-aggregation', label: 'Aggregation Celery Worker' },
  { id: 'postgresql', label: 'Database' },
  { id: 'sshd', label: 'SSH' },
];

export function Logs() {
  const token = localStorage.getItem('access_token');
  const username = localStorage.getItem('username') || 'Unknown';
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const serviceId = searchParams.get('service') || '';
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [logText, setLogText] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [following, setFollowing] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const preRef = useRef<HTMLPreElement>(null);

  const { connectionStatus } = useMetrics(token);

  const fetchLogs = useCallback(
    async (lines: number = 500) => {
      if (!serviceId || !token) return;
      setLoading(true);
      setError(null);
      try {
        const text = await apiClient.getLogs(serviceId, lines);
        setLogText(text);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Failed to load logs';
        setError(msg);
        setLogText('');
      } finally {
        setLoading(false);
      }
    },
    [serviceId, token]
  );

  useEffect(() => {
    if (serviceId) {
      fetchLogs();
    } else {
      setLogText('');
      setError(null);
    }
  }, [serviceId, fetchLogs]);

  useEffect(() => {
    if (!following || !serviceId || !token) return;
    setLogText('');
    const controller = new AbortController();
    abortRef.current = controller;
    const url = `${API_BASE_URL}/api/logs?service=${encodeURIComponent(serviceId)}&lines=200&follow=true`;
    (async () => {
      try {
        const response = await fetch(url, {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
        });
        if (!response.ok || !response.body) {
          setError(`HTTP ${response.status}`);
          return;
        }
        setError(null);
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          setLogText((prev) => prev + decoder.decode(value, { stream: true }));
        }
      } catch (e) {
        if ((e as Error).name !== 'AbortError') {
          setError((e as Error).message);
        }
      } finally {
        setFollowing(false);
      }
    })();
    return () => {
      controller.abort();
      abortRef.current = null;
    };
  }, [following, serviceId, token]);

  useEffect(() => {
    if (preRef.current && logText) {
      preRef.current.scrollTop = preRef.current.scrollHeight;
    }
  }, [logText]);

  const handleLogout = async () => {
    await apiClient.logout();
    navigate('/login');
  };

  const stopFollow = () => {
    if (abortRef.current) {
      abortRef.current.abort();
    }
    setFollowing(false);
  };

  const currentLabel = LOG_SOURCES.find((s) => s.id === serviceId)?.label || serviceId;

  return (
    <div className="flex h-screen">
      <Sidebar
        onLogout={handleLogout}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />
      <div className="flex flex-1 flex-col min-w-0">
        <Navbar
          hostname="nixos-router"
          username={username}
          connectionStatus={connectionStatus}
          onMenuClick={() => setSidebarOpen(true)}
        />
        <main className="flex-1 overflow-auto p-4">
          <div className="mx-auto max-w-full">
            <Card>
              <h1 className="text-xl font-semibold text-gray-900 dark:text-white">Logs</h1>
              {!serviceId ? (
                <>
                  <p className="text-gray-600 dark:text-gray-400">Select a log source</p>
                  <ul className="mt-2 space-y-1">
                  {LOG_SOURCES.map((src) => (
                    <li key={src.id}>
                      <Link
                        to={`/system/logs?service=${src.id}`}
                        className="text-blue-600 hover:underline dark:text-blue-400"
                      >
                        {src.label}
                      </Link>
                    </li>
                  ))}
                  </ul>
                </>
              ) : (
                <>
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <span className="text-sm text-gray-600 dark:text-gray-400">
                      {currentLabel}
                    </span>
                    <Button
                      size="xs"
                      onClick={() => fetchLogs()}
                      disabled={loading || following}
                    >
                      <HiRefresh className="mr-1 h-4 w-4" />
                      Refresh
                    </Button>
                    {following ? (
                      <Button size="xs" color="failure" onClick={stopFollow}>
                        <HiStop className="mr-1 h-4 w-4" />
                        Stop
                      </Button>
                    ) : (
                      <Button
                        size="xs"
                        color="success"
                        onClick={() => setFollowing(true)}
                        disabled={loading}
                      >
                        <HiPlay className="mr-1 h-4 w-4" />
                        Follow
                      </Button>
                    )}
                  </div>
                  {error && (
                    <p className="mb-2 text-sm text-red-600 dark:text-red-400">{error}</p>
                  )}
                  {loading && !logText && (
                    <div className="flex items-center gap-2 py-4">
                      <Spinner size="sm" />
                      <span className="text-sm text-gray-600 dark:text-gray-400">
                        Loading logs...
                      </span>
                    </div>
                  )}
                  <pre
                    ref={preRef}
                    className="max-h-[70vh] overflow-auto rounded bg-gray-900 p-3 text-xs text-gray-100 font-mono whitespace-pre-wrap break-words"
                  >
                    {logText || (loading ? '' : 'No log output.')}
                  </pre>
                </>
              )}
            </Card>
          </div>
        </main>
      </div>
    </div>
  );
}
