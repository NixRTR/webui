/**
 * Apprise Notifications Page
 */
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Button, TextInput, Label, Textarea, Select, Badge, Alert, Modal, Table } from 'flowbite-react';
import { Sidebar } from '../components/layout/Sidebar';
import { Navbar } from '../components/layout/Navbar';
import { useMetrics } from '../hooks/useMetrics';
import { apiClient } from '../api/client';
import { HiBell, HiCheckCircle, HiXCircle, HiInformationCircle } from 'react-icons/hi';
import { AppriseUrlGenerator } from '../components/AppriseUrlGenerator';
import type { AppriseServiceInfoConfig } from '../types/notifications';
import type { AppriseConfig } from '../types/apprise-config';
import { transformConfigServices } from '../utils/apprise';

export function Apprise() {
  const token = localStorage.getItem('access_token');
  const username = localStorage.getItem('username') || 'Unknown';
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [services, setServices] = useState<Array<AppriseServiceInfo & { id: string; originalName: string }>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [urlGeneratorModalOpen, setUrlGeneratorModalOpen] = useState(false);
  
  // Notification form state
  const [notificationBody, setNotificationBody] = useState('');
  const [notificationTitle, setNotificationTitle] = useState('');
  const [notificationType, setNotificationType] = useState('info');
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState<{ success: boolean; message: string } | null>(null);
  
  // Send notification state - track status per service index
  const [sendingServices, setSendingServices] = useState<Set<number>>(new Set());
  const [sendResults, setSendResults] = useState<Map<number, { success: boolean; message: string; details?: string }>>(new Map());
  
  const { connectionStatus } = useMetrics(token);

  useEffect(() => {
    fetchAppriseStatus();
  }, []);

  const fetchAppriseStatus = async () => {
    setLoading(true);
    setError(null);
    try {
      const status = await apiClient.getAppriseStatus();
      setEnabled(status.enabled);
      
      const config = await apiClient.getAppriseConfig();
      const servicesList = transformConfigServices(config);
      setServices(servicesList);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to fetch Apprise status');
      setEnabled(false);
    } finally {
      setLoading(false);
    }
  };

  const handleSendNotification = async () => {
    if (!notificationBody.trim()) {
      setSendResult({ success: false, message: 'Message body is required' });
      return;
    }

    setSending(true);
    setSendResult(null);
    
    try {
      const result = await apiClient.sendAppriseNotification(
        notificationBody,
        notificationTitle || undefined,
        notificationType || undefined
      );
      setSendResult(result);
      if (result.success) {
        setNotificationBody('');
        setNotificationTitle('');
        setNotificationType('info');
      }
    } catch (err: any) {
      setSendResult({
        success: false,
        message: err.response?.data?.detail || err.message || 'Failed to send notification',
      });
    } finally {
      setSending(false);
    }
  };

  const handleSendToService = async (serviceName: string) => {
    if (!notificationBody.trim()) {
      setSendResults(prev => new Map(prev).set(serviceName, { success: false, message: 'Message body is required' }));
      return;
    }

    setSendingServices(prev => new Set(prev).add(serviceName));
    setSendResults(prev => {
      const newMap = new Map(prev);
      newMap.delete(serviceName);
      return newMap;
    });
    
    try {
      // Use general send endpoint - config services are managed in Settings
      const result = await apiClient.sendAppriseNotification(
        notificationBody,
        notificationTitle || undefined,
        notificationType || undefined
      );
      setSendResults(prev => new Map(prev).set(serviceName, result));
      
      if (!result.success) {
        const errorMsg = result.details 
          ? `${result.message}: ${result.details}`
          : result.message;
        setSendResults(prev => new Map(prev).set(serviceName, { success: false, message: errorMsg, details: result.details }));
      }
    } catch (err: any) {
      const errorMsg = err.response?.data?.detail || err.message || 'Failed to send notification';
      setSendResults(prev => new Map(prev).set(serviceName, {
        success: false,
        message: errorMsg,
      }));
    } finally {
      setSendingServices(prev => {
        const newSet = new Set(prev);
        newSet.delete(serviceName);
        return newSet;
      });
    }
  };

  const handleTestService = async (serviceName: string) => {
    setSendingServices(prev => new Set(prev).add(serviceName));
    try {
      const result = await apiClient.testAppriseServiceByName(serviceName);
      setSendResults(prev => new Map(prev).set(serviceName, result));
      if (!result.success) {
        setSendResults(prev => new Map(prev).set(serviceName, { success: false, message: result.message, details: result.details }));
      }
    } catch (err: any) {
      setSendResults(prev => new Map(prev).set(serviceName, { success: false, message: err.response?.data?.detail || err.message }));
    } finally {
      setSendingServices(prev => {
        const newSet = new Set(prev);
        newSet.delete(serviceName);
        return newSet;
      });
    }
  };

  const handleLogout = async () => {
    await apiClient.logout();
    navigate('/login');
  };

  if (loading) {
    return (
      <div className="flex h-screen">
        <Sidebar 
          onLogout={handleLogout}
          isOpen={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
        />
        <div className="flex-1 flex flex-col overflow-hidden">
          <Navbar
            hostname="nixos-router"
            username={username}
            connectionStatus={connectionStatus}
            onMenuClick={() => setSidebarOpen(!sidebarOpen)}
          />
          <main className="flex-1 overflow-y-auto p-6 bg-gray-50 dark:bg-gray-900">
            <div className="text-center py-16 text-gray-500">
              Loading Apprise configuration...
            </div>
          </main>
        </div>
      </div>
    );
  }

  if (!enabled) {
    return (
      <div className="flex h-screen">
        <Sidebar 
          onLogout={handleLogout}
          isOpen={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
        />
        <div className="flex-1 flex flex-col overflow-hidden">
          <Navbar
            hostname="nixos-router"
            username={username}
            connectionStatus={connectionStatus}
            onMenuClick={() => setSidebarOpen(!sidebarOpen)}
          />
          <main className="flex-1 overflow-y-auto p-6 bg-gray-50 dark:bg-gray-900">
            <Alert color="warning" icon={HiInformationCircle}>
              <span className="font-medium">Apprise is not enabled.</span>
              <div className="mt-2 text-sm">
                To enable Apprise notifications, set <code className="px-1 py-0.5 bg-gray-200 dark:bg-gray-700 rounded">apprise.enable = true</code> in your <code className="px-1 py-0.5 bg-gray-200 dark:bg-gray-700 rounded">router-config.nix</code> file.
              </div>
            </Alert>
          </main>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen">
      <Sidebar 
        onLogout={handleLogout}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />
      
      <div className="flex-1 flex flex-col overflow-hidden">
        <Navbar
          hostname="nixos-router"
          username={username}
          connectionStatus={connectionStatus}
          onMenuClick={() => setSidebarOpen(!sidebarOpen)}
        />
        
        <main className="flex-1 overflow-y-auto p-6 bg-gray-50 dark:bg-gray-900">
          <div className="max-w-7xl mx-auto">
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <HiBell className="w-8 h-8 text-gray-900 dark:text-white" />
                <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Apprise Notifications</h1>
              </div>
              <Button
                color="blue"
                onClick={() => setUrlGeneratorModalOpen(true)}
              >
                New Service
              </Button>
            </div>

            {error && (
              <Alert color="failure" className="mb-6">
                {error}
              </Alert>
            )}

            {sendResult && (
              <Alert 
                color={sendResult.success ? "success" : "failure"} 
                icon={sendResult.success ? HiCheckCircle : HiXCircle}
                className="mb-6"
                onDismiss={() => setSendResult(null)}
              >
                {sendResult.message}
              </Alert>
            )}

            {/* Configured Services Section */}
            <Card className="mb-6">
              <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
                Configured Services ({services.length})
              </h2>
              
              {services.length === 0 ? (
                <Alert color="info" icon={HiInformationCircle}>
                  No notification services are configured. Use the URL Generator below to create a service.
                </Alert>
              ) : (
                <Table>
                  <Table.Head>
                    <Table.HeadCell>Name</Table.HeadCell>
                    <Table.HeadCell>Description</Table.HeadCell>
                    <Table.HeadCell>Status</Table.HeadCell>
                    <Table.HeadCell>Actions</Table.HeadCell>
                  </Table.Head>
                  <Table.Body className="divide-y">
                    {services.map((service) => {
                      const serviceName = service.originalName;
                      const isSending = sendingServices.has(serviceName);
                      const sendResult = sendResults.get(serviceName);
                      
                      return (
                        <Table.Row key={serviceName} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                          <Table.Cell className="whitespace-nowrap font-medium text-gray-900 dark:text-white">
                            {service.name}
                          </Table.Cell>
                          <Table.Cell className="text-gray-500 dark:text-gray-400">
                            {service.description || '-'}
                          </Table.Cell>
                          <Table.Cell>
                            <Badge color={service.enabled ? "success" : "gray"}>
                              {service.enabled ? "Enabled" : "Disabled"}
                            </Badge>
                          </Table.Cell>
                          <Table.Cell>
                            <div className="flex gap-2">
                              <Button
                                size="xs"
                                color="blue"
                                onClick={() => handleSendToService((service as any).originalName || service.name)}
                                disabled={sendingServices.has((service as any).originalName || service.name) || !notificationBody.trim() || !service.enabled}
                              >
                                {sendingServices.has((service as any).originalName || service.name) ? 'Sending...' : sendResults.get((service as any).originalName || service.name)?.success ? 'Send Again' : 'Send'}
                              </Button>
                              <Button
                                size="xs"
                                color="gray"
                                onClick={() => handleTestService((service as any).originalName || service.name)}
                                disabled={sendingServices.has((service as any).originalName || service.name) || !service.enabled}
                              >
                                Test
                              </Button>
                              {/* Edit and Delete disabled for config services - manage in Settings */}
                            </div>
                          </Table.Cell>
                        </Table.Row>
                      );
                    })}
                  </Table.Body>
                </Table>
              )}
            </Card>

            {/* Send Notification Section */}
            <Card className="mb-6">
              <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">Send Notification</h2>
              <div className="space-y-4">
                <div>
                  <Label htmlFor="title" value="Title (optional)" />
                  <TextInput
                    id="title"
                    type="text"
                    placeholder="Notification title"
                    value={notificationTitle}
                    onChange={(e) => setNotificationTitle(e.target.value)}
                    className="mt-1"
                  />
                </div>
                <div>
                  <Label htmlFor="body" value="Message Body *" />
                  <Textarea
                    id="body"
                    placeholder="Enter your notification message..."
                    value={notificationBody}
                    onChange={(e) => setNotificationBody(e.target.value)}
                    rows={4}
                    className="mt-1"
                    required
                  />
                </div>
                <div>
                  <Label htmlFor="type" value="Notification Type" />
                  <Select
                    id="type"
                    value={notificationType}
                    onChange={(e) => setNotificationType(e.target.value)}
                    className="mt-1"
                  >
                    <option value="info">Info</option>
                    <option value="success">Success</option>
                    <option value="warning">Warning</option>
                    <option value="failure">Failure</option>
                  </Select>
                </div>
                <Button
                  onClick={handleSendNotification}
                  disabled={sending || !notificationBody.trim()}
                  className="w-full sm:w-auto"
                >
                  {sending ? 'Sending...' : 'Send to All Services'}
                </Button>
              </div>
            </Card>

            {/* How It Works Section */}
            <Card>
              <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">How It Works</h2>
              <div className="space-y-3 text-gray-700 dark:text-gray-300">
                <p>
                  Apprise is integrated into the NixOS Router WebUI backend, allowing you to send notifications
                  to multiple services configured in <code className="px-1 py-0.5 bg-gray-200 dark:bg-gray-700 rounded">router-config.nix</code>.
                </p>
                <p>
                  Notifications can be sent to all configured services simultaneously, or to individual services.
                </p>
                <p>
                  <strong>Notification Types:</strong>
                </p>
                <ul className="list-disc list-inside ml-4 space-y-1">
                  <li><strong>info</strong> - General information (default)</li>
                  <li><strong>success</strong> - Success messages</li>
                  <li><strong>warning</strong> - Warning messages</li>
                  <li><strong>failure</strong> - Error/failure messages</li>
                </ul>
              </div>
            </Card>

            {/* URL Generator Modal */}
            <Modal show={urlGeneratorModalOpen} onClose={() => setUrlGeneratorModalOpen(false)} size="6xl">
              <Modal.Header>Create New Apprise Service</Modal.Header>
              <Modal.Body className="max-h-[80vh] overflow-y-auto">
                <div>
                  <AppriseUrlGenerator 
                    onServiceSaved={() => {
                      setUrlGeneratorModalOpen(false);
                      fetchAppriseStatus();
                    }}
                  />
                </div>
              </Modal.Body>
            </Modal>

          </div>
        </main>
      </div>
    </div>
  );
}

