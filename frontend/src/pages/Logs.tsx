/**
 * Logs page - live view of systemd journal logs for configured services
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Spinner, Select, Checkbox, Label } from 'flowbite-react';
import { HiRefresh } from 'react-icons/hi';
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

const LINES_OPTIONS = [100, 200, 500, 1000, 2000];

const LOG_LEVEL_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'err', label: 'Error' },
  { value: 'warning', label: 'Warning' },
  { value: 'info', label: 'Info' },
  { value: 'debug', label: 'Debug' },
];

export function Logs() {
  const token = localStorage.getItem('access_token');
  const username = localStorage.getItem('username') || 'Unknown';
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [serviceId, setServiceId] = useState(LOG_SOURCES[0].id);
  const [lines, setLines] = useState(500);
  const [priority, setPriority] = useState<string>('all');
  const [follow, setFollow] = useState(false);
  const [logText, setLogText] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const preRef = useRef<HTMLPreElement>(null);

  const { connectionStatus } = useMetrics(token);

  const fetchLogs = useCallback(
    async (lineCount: number, level: string = priority) => {
      if (!serviceId || !token) return;
      setLoading(true);
      setError(null);
      try {
        const text = await apiClient.getLogs(serviceId, lineCount, level);
        setLogText(text);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Failed to load logs';
        setError(msg);
        setLogText('');
      } finally {
        setLoading(false);
      }
    },
    [serviceId, token, priority]
  );

  // One-shot load when service, lines, or priority change (and not following)
  useEffect(() => {
    if (!follow && serviceId) {
      fetchLogs(lines, priority);
    }
  }, [serviceId, lines, priority, follow, fetchLogs]);

  // Follow mode: stream logs with selected lines
  useEffect(() => {
    if (!follow || !serviceId || !token) return;
    setLogText('');
    setError(null);
    setLoading(true);
    const controller = new AbortController();
    abortRef.current = controller;
    const params = new URLSearchParams({
      service: serviceId,
      lines: String(lines),
      follow: 'true',
    });
    if (priority && priority !== 'all') params.set('priority', priority);
    const url = `${API_BASE_URL}/api/logs?${params.toString()}`;
    (async () => {
      try {
        const response = await fetch(url, {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
        });
        if (!response.ok || !response.body) {
          setError(`HTTP ${response.status}`);
          setLoading(false);
          return;
        }
        setLoading(false);
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
        setLoading(false);
      } finally {
        setFollow(false);
      }
    })();
    return () => {
      controller.abort();
      abortRef.current = null;
    };
  }, [follow, serviceId, lines, priority, token]);

  useEffect(() => {
    if (preRef.current && logText) {
      preRef.current.scrollTop = preRef.current.scrollHeight;
    }
  }, [logText]);

  const handleLogout = async () => {
    await apiClient.logout();
    navigate('/login');
  };

  const handleFollowChange = (checked: boolean) => {
    if (!checked && abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setFollow(checked);
  };

  const handleRefresh = () => {
    if (follow) {
      handleFollowChange(false);
    }
    fetchLogs(lines, priority);
  };

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
              <div className="mb-4 flex flex-wrap items-end gap-4">
                <div className="min-w-[200px]">
                  <Label htmlFor="log-source" className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                    Log to view
                  </Label>
                  <Select
                    id="log-source"
                    value={serviceId}
                    onChange={(e) => setServiceId(e.target.value)}
                    disabled={follow}
                  >
                    {LOG_SOURCES.map((src) => (
                      <option key={src.id} value={src.id}>
                        {src.label}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="min-w-[120px]">
                  <Label htmlFor="lines" className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                    Lines to view
                  </Label>
                  <Select
                    id="lines"
                    value={lines}
                    onChange={(e) => setLines(Number(e.target.value))}
                    disabled={follow}
                  >
                    {LINES_OPTIONS.map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="min-w-[140px]">
                  <Label htmlFor="log-level" className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                    Log level
                  </Label>
                  <Select
                    id="log-level"
                    value={priority}
                    onChange={(e) => setPriority(e.target.value)}
                    disabled={follow}
                  >
                    {LOG_LEVEL_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="follow"
                    checked={follow}
                    onChange={(e) => handleFollowChange(e.target.checked)}
                    disabled={loading}
                  />
                  <Label htmlFor="follow" className="cursor-pointer text-sm text-gray-700 dark:text-gray-300">
                    Follow log (live tail, includes selected lines)
                  </Label>
                </div>
                <Button
                  size="sm"
                  onClick={handleRefresh}
                  disabled={loading || follow}
                >
                  <HiRefresh className="mr-2 h-4 w-4" />
                  Refresh
                </Button>
              </div>
              {error && (
                <p className="mb-2 text-sm text-red-600 dark:text-red-400">{error}</p>
              )}
              {loading && !logText && (
                <div className="flex items-center gap-2 py-4">
                  <Spinner size="sm" />
                  <span className="text-sm text-gray-600 dark:text-gray-400">
                    {follow ? 'Connecting...' : 'Loading logs...'}
                  </span>
                </div>
              )}
              <pre
                ref={preRef}
                className="max-h-[70vh] overflow-auto rounded bg-gray-900 p-3 text-xs text-gray-100 font-mono whitespace-pre-wrap break-words"
              >
                {logText || (loading ? '' : 'Select a log and click Refresh or enable Follow.')}
              </pre>
            </Card>
          </div>
        </main>
      </div>
    </div>
  );
}
