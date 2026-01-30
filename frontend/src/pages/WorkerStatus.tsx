/**
 * Worker Status page - Celery queue inspection and control
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Button,
  Card,
  Modal,
  Spinner,
  Table,
} from 'flowbite-react';
import { HiRefresh, HiTrash, HiPlay, HiX } from 'react-icons/hi';
import { Sidebar } from '../components/layout/Sidebar';
import { Navbar } from '../components/layout/Navbar';
import { useMetrics } from '../hooks/useMetrics';
import { apiClient } from '../api/client';
import type {
  WorkerStatusResponse,
  TaskInfo,
  QueueStats,
} from '../types/worker-status';

export function WorkerStatus() {
  const token = localStorage.getItem('access_token');
  const username = localStorage.getItem('username') || 'Unknown';
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const [status, setStatus] = useState<WorkerStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastTestTaskId, setLastTestTaskId] = useState<string | null>(null);
  const [purgeModalOpen, setPurgeModalOpen] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const { connectionStatus } = useMetrics(token);

  const fetchStatus = useCallback(async () => {
    if (!token) return;
    setError(null);
    try {
      const data = await apiClient.getWorkerStatus();
      setStatus(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load worker status';
      setError(msg);
      setStatus(null);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const handleLogout = async () => {
    await apiClient.logout();
    navigate('/login');
  };

  const handleRefresh = () => {
    setLoading(true);
    fetchStatus();
  };

  const handleRevoke = async (taskId: string) => {
    setActionLoading(taskId);
    try {
      await apiClient.revokeTask(taskId, true);
      await fetchStatus();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to revoke task';
      setError(msg);
    } finally {
      setActionLoading(null);
    }
  };

  const handlePurge = async () => {
    setPurgeModalOpen(false);
    setActionLoading('purge');
    try {
      await apiClient.purgeWorkerQueues();
      await fetchStatus();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to purge queues';
      setError(msg);
    } finally {
      setActionLoading(null);
    }
  };

  const handleTriggerTestTask = async () => {
    setActionLoading('test-task');
    try {
      const res = await apiClient.triggerWorkerTestTask();
      setLastTestTaskId(res.task_id);
      await fetchStatus();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to trigger test task';
      setError(msg);
    } finally {
      setActionLoading(null);
    }
  };

  const formatRuntime = (runtime: number | null, timeStarted: number | null): string => {
    if (runtime != null) return `${Math.round(runtime)}s`;
    if (timeStarted != null) {
      const sec = Math.round(Date.now() / 1000 - timeStarted);
      return `${sec}s`;
    }
    return '—';
  };

  return (
    <div className="flex min-h-screen bg-gray-50 dark:bg-gray-900">
      <Sidebar
        onLogout={handleLogout}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />
      <div className="flex flex-1 flex-col">
        <Navbar
          hostname="nixos-router"
          username={username}
          connectionStatus={connectionStatus}
          onMenuClick={() => setSidebarOpen(true)}
        />
        <main className="flex-1 p-4 md:p-6">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <h1 className="text-2xl font-semibold text-gray-900 dark:text-white">
              Worker Status
            </h1>
            <div className="flex flex-wrap gap-2">
              <Button
                color="gray"
                onClick={handleRefresh}
                disabled={loading}
              >
                {loading ? <Spinner size="sm" className="mr-2" /> : <HiRefresh className="mr-2 h-4 w-4" />}
                Refresh
              </Button>
              <Button
                color="failure"
                onClick={() => setPurgeModalOpen(true)}
                disabled={loading || actionLoading === 'purge'}
              >
                {actionLoading === 'purge' ? <Spinner size="sm" className="mr-2" /> : <HiTrash className="mr-2 h-4 w-4" />}
                Flush queue
              </Button>
              <Button
                color="info"
                onClick={handleTriggerTestTask}
                disabled={loading || actionLoading === 'test-task'}
              >
                {actionLoading === 'test-task' ? <Spinner size="sm" className="mr-2" /> : <HiPlay className="mr-2 h-4 w-4" />}
                Trigger test task
              </Button>
            </div>
          </div>

          {lastTestTaskId && (
            <Alert color="info" className="mb-4">
              Last test task ID: <code className="rounded bg-gray-100 px-1 dark:bg-gray-700">{lastTestTaskId}</code>
            </Alert>
          )}

          {error && (
            <Alert color="failure" className="mb-4" onDismiss={() => setError(null)}>
              {error}
            </Alert>
          )}

          {loading && !status ? (
            <div className="flex justify-center py-12">
              <Spinner size="xl" />
            </div>
          ) : !status ? (
            <Card className="p-6">
              <p className="text-gray-600 dark:text-gray-400">No worker data available. Check that Celery workers are running and Redis is reachable.</p>
            </Card>
          ) : (
            <div className="space-y-6">
              {/* Queues */}
              <Card>
                <h2 className="mb-3 text-lg font-semibold text-gray-900 dark:text-white">Queues</h2>
                <Table>
                  <Table.Head>
                    <Table.HeadCell>Queue</Table.HeadCell>
                    <Table.HeadCell>In broker</Table.HeadCell>
                    <Table.HeadCell>Reserved</Table.HeadCell>
                    <Table.HeadCell>Active</Table.HeadCell>
                  </Table.Head>
                  <Table.Body>
                    {status.queues.map((q: QueueStats) => (
                      <Table.Row key={q.name}>
                        <Table.Cell className="font-medium">{q.name}</Table.Cell>
                        <Table.Cell>{q.broker_length}</Table.Cell>
                        <Table.Cell>{q.reserved_count}</Table.Cell>
                        <Table.Cell>{q.active_count}</Table.Cell>
                      </Table.Row>
                    ))}
                  </Table.Body>
                </Table>
              </Card>

              {/* Active tasks */}
              <Card>
                <h2 className="mb-3 text-lg font-semibold text-gray-900 dark:text-white">Active tasks</h2>
                {status.active_tasks.length === 0 ? (
                  <p className="text-sm text-gray-500 dark:text-gray-400">None</p>
                ) : (
                  <Table>
                    <Table.Head>
                      <Table.HeadCell>Task ID</Table.HeadCell>
                      <Table.HeadCell>Name</Table.HeadCell>
                      <Table.HeadCell>Worker</Table.HeadCell>
                      <Table.HeadCell>Runtime</Table.HeadCell>
                      <Table.HeadCell></Table.HeadCell>
                    </Table.Head>
                    <Table.Body>
                      {status.active_tasks.map((t: TaskInfo) => (
                        <Table.Row key={t.id}>
                          <Table.Cell className="font-mono text-xs">{t.id}</Table.Cell>
                          <Table.Cell>{t.name}</Table.Cell>
                          <Table.Cell>{t.worker ?? '—'}</Table.Cell>
                          <Table.Cell>{formatRuntime(t.runtime, t.time_started)}</Table.Cell>
                          <Table.Cell>
                            <Button
                              size="xs"
                              color="failure"
                              onClick={() => handleRevoke(t.id)}
                              disabled={actionLoading === t.id}
                            >
                              {actionLoading === t.id ? <Spinner size="sm" /> : <HiX className="h-4 w-4" />}
                            </Button>
                          </Table.Cell>
                        </Table.Row>
                      ))}
                    </Table.Body>
                  </Table>
                )}
              </Card>

              {/* Reserved tasks */}
              <Card>
                <h2 className="mb-3 text-lg font-semibold text-gray-900 dark:text-white">Reserved (queued at workers)</h2>
                {status.reserved_tasks.length === 0 ? (
                  <p className="text-sm text-gray-500 dark:text-gray-400">None</p>
                ) : (
                  <Table>
                    <Table.Head>
                      <Table.HeadCell>Task ID</Table.HeadCell>
                      <Table.HeadCell>Name</Table.HeadCell>
                      <Table.HeadCell>Worker</Table.HeadCell>
                      <Table.HeadCell></Table.HeadCell>
                    </Table.Head>
                    <Table.Body>
                      {status.reserved_tasks.map((t: TaskInfo) => (
                        <Table.Row key={t.id}>
                          <Table.Cell className="font-mono text-xs">{t.id}</Table.Cell>
                          <Table.Cell>{t.name}</Table.Cell>
                          <Table.Cell>{t.worker ?? '—'}</Table.Cell>
                          <Table.Cell>
                            <Button
                              size="xs"
                              color="failure"
                              onClick={() => handleRevoke(t.id)}
                              disabled={actionLoading === t.id}
                            >
                              {actionLoading === t.id ? <Spinner size="sm" /> : <HiX className="h-4 w-4" />}
                            </Button>
                          </Table.Cell>
                        </Table.Row>
                      ))}
                    </Table.Body>
                  </Table>
                )}
              </Card>

              {/* Scheduled tasks */}
              <Card>
                <h2 className="mb-3 text-lg font-semibold text-gray-900 dark:text-white">Scheduled (ETA)</h2>
                {status.scheduled_tasks.length === 0 ? (
                  <p className="text-sm text-gray-500 dark:text-gray-400">None</p>
                ) : (
                  <Table>
                    <Table.Head>
                      <Table.HeadCell>Task ID</Table.HeadCell>
                      <Table.HeadCell>Name</Table.HeadCell>
                      <Table.HeadCell>Worker</Table.HeadCell>
                      <Table.HeadCell>ETA</Table.HeadCell>
                    </Table.Head>
                    <Table.Body>
                      {status.scheduled_tasks.map((t: TaskInfo) => (
                        <Table.Row key={t.id}>
                          <Table.Cell className="font-mono text-xs">{t.id}</Table.Cell>
                          <Table.Cell>{t.name}</Table.Cell>
                          <Table.Cell>{t.worker ?? '—'}</Table.Cell>
                          <Table.Cell>{t.eta ?? '—'}</Table.Cell>
                        </Table.Row>
                      ))}
                    </Table.Body>
                  </Table>
                )}
              </Card>

              {/* Overdue tasks */}
              <Card className="border-amber-200 dark:border-amber-800">
                <h2 className="mb-3 text-lg font-semibold text-amber-700 dark:text-amber-400">Overdue</h2>
                {status.overdue_tasks.length === 0 ? (
                  <p className="text-sm text-gray-500 dark:text-gray-400">None</p>
                ) : (
                  <Table>
                    <Table.Head>
                      <Table.HeadCell>Task ID</Table.HeadCell>
                      <Table.HeadCell>Name</Table.HeadCell>
                      <Table.HeadCell>Worker</Table.HeadCell>
                      <Table.HeadCell>ETA</Table.HeadCell>
                    </Table.Head>
                    <Table.Body>
                      {status.overdue_tasks.map((t: TaskInfo) => (
                        <Table.Row key={t.id}>
                          <Table.Cell className="font-mono text-xs">{t.id}</Table.Cell>
                          <Table.Cell>{t.name}</Table.Cell>
                          <Table.Cell>{t.worker ?? '—'}</Table.Cell>
                          <Table.Cell>{t.eta ?? '—'}</Table.Cell>
                        </Table.Row>
                      ))}
                    </Table.Body>
                  </Table>
                )}
              </Card>

              {/* Long-running tasks */}
              <Card className="border-orange-200 dark:border-orange-800">
                <h2 className="mb-3 text-lg font-semibold text-orange-700 dark:text-orange-400">Long-running</h2>
                {status.long_running_tasks.length === 0 ? (
                  <p className="text-sm text-gray-500 dark:text-gray-400">None</p>
                ) : (
                  <Table>
                    <Table.Head>
                      <Table.HeadCell>Task ID</Table.HeadCell>
                      <Table.HeadCell>Name</Table.HeadCell>
                      <Table.HeadCell>Worker</Table.HeadCell>
                      <Table.HeadCell>Runtime</Table.HeadCell>
                      <Table.HeadCell></Table.HeadCell>
                    </Table.Head>
                    <Table.Body>
                      {status.long_running_tasks.map((t: TaskInfo) => (
                        <Table.Row key={t.id}>
                          <Table.Cell className="font-mono text-xs">{t.id}</Table.Cell>
                          <Table.Cell>{t.name}</Table.Cell>
                          <Table.Cell>{t.worker ?? '—'}</Table.Cell>
                          <Table.Cell>{formatRuntime(t.runtime, t.time_started)}</Table.Cell>
                          <Table.Cell>
                            <Button
                              size="xs"
                              color="failure"
                              onClick={() => handleRevoke(t.id)}
                              disabled={actionLoading === t.id}
                            >
                              {actionLoading === t.id ? <Spinner size="sm" /> : <HiX className="h-4 w-4" />}
                            </Button>
                          </Table.Cell>
                        </Table.Row>
                      ))}
                    </Table.Body>
                  </Table>
                )}
              </Card>
            </div>
          )}
        </main>
      </div>

      <Modal show={purgeModalOpen} onClose={() => setPurgeModalOpen(false)} size="md">
        <Modal.Header>Flush task queues</Modal.Header>
        <Modal.Body>
          <p className="text-sm text-gray-600 dark:text-gray-400">
            Permanently remove all messages from task queues (celery, sequential, parallel). This cannot be undone.
          </p>
        </Modal.Body>
        <Modal.Footer>
          <Button color="gray" onClick={() => setPurgeModalOpen(false)}>Cancel</Button>
          <Button color="failure" onClick={handlePurge}>Flush</Button>
        </Modal.Footer>
      </Modal>
    </div>
  );
}
