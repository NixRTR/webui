/**
 * Apprise Configuration Page
 */
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Button, TextInput, Label, Select, Alert, ToggleSwitch } from 'flowbite-react';
import { Sidebar } from '../components/layout/Sidebar';
import { Navbar } from '../components/layout/Navbar';
import { useMetrics } from '../hooks/useMetrics';
import { apiClient } from '../api/client';
import { HiBell } from 'react-icons/hi';
import type { AppriseConfig, AppriseConfigUpdate } from '../types/apprise-config';

export function AppriseConfig() {
  const token = localStorage.getItem('access_token');
  const username = localStorage.getItem('username') || 'Unknown';
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  
  // Form state
  const [enable, setEnable] = useState(true);
  const [port, setPort] = useState(8001);
  const [attachSize, setAttachSize] = useState(0);
  const [services, setServices] = useState<Record<string, any>>({});
  
  // Test state
  const [testingService, setTestingService] = useState<string | null>(null);
  const [testingAll, setTestingAll] = useState(false);
  const [testResult, setTestResult] = useState<{ service?: string; success: boolean; message: string } | null>(null);
  
  const { connectionStatus } = useMetrics(token);

  useEffect(() => {
    if (!token) {
      navigate('/login');
      return;
    }
    fetchConfig();
  }, [token]);

  const fetchConfig = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.getAppriseConfig();
      setEnable(data.enable);
      setPort(data.port);
      setAttachSize(data.attachSize);
      
      // Initialize services - use loaded services or defaults
      const defaultServices: Record<string, any> = {
        email: { enable: false, smtpHost: 'smtp.gmail.com', smtpPort: 587, username: '', to: '', from: '' },
        homeAssistant: { enable: false, host: 'homeassistant.local', port: 8123, useHttps: false },
        discord: { enable: false },
        slack: { enable: false },
        telegram: { enable: false, chatId: '' },
        ntfy: { enable: false, topic: 'router-notifications', server: '' },
      };
      
      // Merge loaded services with defaults, ensuring all services are present
      const mergedServices: Record<string, any> = {};
      const serviceKeys = ['email', 'homeAssistant', 'discord', 'slack', 'telegram', 'ntfy'];
      
      serviceKeys.forEach(key => {
        if (data.services && data.services[key]) {
          // Use loaded service, filling in defaults for missing fields
          mergedServices[key] = { ...defaultServices[key], ...data.services[key] };
        } else {
          // Use default service
          mergedServices[key] = { ...defaultServices[key] };
        }
      });
      
      setServices(mergedServices);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load Apprise configuration');
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(null);
    
    try {
      // Prepare services for saving - include all services with their configured values
      const servicesToSave: Record<string, any> = {};
      
      // Email service
      if (services.email) {
        servicesToSave.email = {
          enable: services.email.enable || false,
          smtpHost: services.email.smtpHost || 'smtp.gmail.com',
          smtpPort: services.email.smtpPort || 587,
          username: services.email.username || '',
          to: services.email.to || '',
        };
        if (services.email.from) {
          servicesToSave.email.from = services.email.from;
        }
      }
      
      // Home Assistant service
      if (services.homeAssistant) {
        servicesToSave.homeAssistant = {
          enable: services.homeAssistant.enable || false,
          host: services.homeAssistant.host || 'homeassistant.local',
          port: services.homeAssistant.port || 8123,
        };
        if (services.homeAssistant.useHttps !== undefined && services.homeAssistant.useHttps !== null) {
          servicesToSave.homeAssistant.useHttps = services.homeAssistant.useHttps;
        }
      }
      
      // Discord service
      if (services.discord) {
        servicesToSave.discord = {
          enable: services.discord.enable || false,
        };
      }
      
      // Slack service
      if (services.slack) {
        servicesToSave.slack = {
          enable: services.slack.enable || false,
        };
      }
      
      // Telegram service
      if (services.telegram) {
        servicesToSave.telegram = {
          enable: services.telegram.enable || false,
          chatId: services.telegram.chatId || '',
        };
      }
      
      // ntfy service
      if (services.ntfy) {
        servicesToSave.ntfy = {
          enable: services.ntfy.enable || false,
          topic: services.ntfy.topic || 'router-notifications',
        };
        if (services.ntfy.server) {
          servicesToSave.ntfy.server = services.ntfy.server;
        }
      }
      
      const update: AppriseConfigUpdate = {
        enable,
        port,
        attachSize,
        services: servicesToSave,
      };
      
      await apiClient.updateAppriseConfig(update);
      setSuccess('Apprise configuration saved successfully');
      await fetchConfig();
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Failed to save Apprise configuration');
    } finally {
      setSaving(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('username');
    navigate('/login');
  };

  const handleTestService = async (serviceName: string) => {
    setTestingService(serviceName);
    setTestResult(null);
    setError(null);
    
    try {
      const result = await apiClient.testAppriseServiceByName(serviceName);
      setTestResult({
        service: serviceName,
        success: result.success,
        message: result.message || (result.success ? 'Test sent successfully' : 'Test failed')
      });
      
      if (result.success) {
        setSuccess(`Test notification sent to ${serviceName}`);
        setTimeout(() => setSuccess(null), 5000);
      } else {
        setError(`Failed to send test to ${serviceName}: ${result.message}`);
        setTimeout(() => setError(null), 5000);
      }
    } catch (err: any) {
      const errorMsg = err?.response?.data?.detail || err.message || 'Failed to send test notification';
      setTestResult({
        service: serviceName,
        success: false,
        message: errorMsg
      });
      setError(`Failed to send test to ${serviceName}: ${errorMsg}`);
      setTimeout(() => setError(null), 5000);
    } finally {
      setTestingService(null);
    }
  };

  const handleTestAll = async () => {
    setTestingAll(true);
    setTestResult(null);
    setError(null);
    
    try {
      const result = await apiClient.testAllAppriseServices();
      setTestResult({
        success: result.success,
        message: result.message || (result.success ? 'Test sent to all services' : 'Test failed')
      });
      
      if (result.success) {
        setSuccess('Test notification sent to all enabled services');
        setTimeout(() => setSuccess(null), 5000);
      } else {
        setError(`Failed to send test: ${result.message}`);
        setTimeout(() => setError(null), 5000);
      }
    } catch (err: any) {
      const errorMsg = err?.response?.data?.detail || err.message || 'Failed to send test notification';
      setTestResult({
        success: false,
        message: errorMsg
      });
      setError(`Failed to send test: ${errorMsg}`);
      setTimeout(() => setError(null), 5000);
    } finally {
      setTestingAll(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-screen bg-gray-50 dark:bg-gray-900">
        <Sidebar onLogout={handleLogout} isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />
        <div className="flex-1 flex flex-col overflow-hidden">
          <Navbar
            hostname="nixos-router"
            username={username}
            connectionStatus={connectionStatus}
            onMenuClick={() => setSidebarOpen(!sidebarOpen)}
          />
          <main className="flex-1 overflow-y-auto p-6">
            <div className="text-center text-gray-600 dark:text-gray-400">Loading...</div>
          </main>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-900">
      <Sidebar onLogout={handleLogout} isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="flex-1 flex flex-col overflow-hidden">
        <Navbar
          hostname="nixos-router"
          username={username}
          connectionStatus={connectionStatus}
          onMenuClick={() => setSidebarOpen(!sidebarOpen)}
        />
        <main className="flex-1 overflow-y-auto p-6">
          <div className="max-w-4xl mx-auto">
            <div className="flex items-center mb-6">
              <HiBell className="w-8 h-8 mr-3 text-blue-600 dark:text-blue-400" />
              <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Apprise Notifications</h1>
            </div>

            {error && (
              <Alert color="failure" className="mb-4" onDismiss={() => setError(null)}>
                {error}
              </Alert>
            )}

            {success && (
              <Alert color="success" className="mb-4" onDismiss={() => setSuccess(null)}>
                {success}
              </Alert>
            )}

            <Card>
              <div className="space-y-6">
                <div>
                  <Label htmlFor="enable" className="mb-2 block">
                    Enable Apprise
                  </Label>
                  <Select id="enable" value={enable ? 'true' : 'false'} onChange={(e) => setEnable(e.target.value === 'true')}>
                    <option value="true">Enabled</option>
                    <option value="false">Disabled</option>
                  </Select>
                </div>

                <div>
                  <Label htmlFor="port" className="mb-2 block">
                    Port
                  </Label>
                  <TextInput
                    id="port"
                    type="number"
                    value={port}
                    onChange={(e) => setPort(parseInt(e.target.value) || 8001)}
                  />
                </div>

                <div>
                  <Label htmlFor="attachSize" className="mb-2 block">
                    Maximum Attachment Size (MB)
                  </Label>
                  <TextInput
                    id="attachSize"
                    type="number"
                    value={attachSize}
                    onChange={(e) => setAttachSize(parseInt(e.target.value) || 0)}
                  />
                  <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                    Set to 0 to disable attachments
                  </p>
                </div>

                <div className="border-t border-gray-200 dark:border-gray-700 pt-6 mt-6">
                  <div className="flex items-center justify-between mb-4">
                    <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
                      Notification Services
                    </h2>
                    <Button
                      onClick={handleTestAll}
                      disabled={testingAll || !enable}
                      color="gray"
                      size="sm"
                    >
                      {testingAll ? 'Testing...' : 'Test All'}
                    </Button>
                  </div>
                  <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                    Configure individual notification services. Secrets (passwords, tokens) are stored in secrets/secrets.yaml.
                  </p>

                  <div className="space-y-4">
                    {/* Email Service */}
                    <Card>
                      <div className="flex items-center justify-between mb-4">
                        <h3 className="text-lg font-medium text-gray-900 dark:text-white">Email (SMTP)</h3>
                        <ToggleSwitch
                          checked={services.email?.enable || false}
                          onChange={(checked) => {
                            setServices({
                              ...services,
                              email: { ...services.email, enable: checked }
                            });
                          }}
                        />
                      </div>
                      {services.email?.enable && (
                        <div className="space-y-4">
                          <div>
                            <Label htmlFor="email-smtpHost">SMTP Host</Label>
                            <TextInput
                              id="email-smtpHost"
                              value={services.email?.smtpHost || ''}
                              onChange={(e) => {
                                setServices({
                                  ...services,
                                  email: { ...services.email, smtpHost: e.target.value }
                                });
                              }}
                              placeholder="smtp.gmail.com"
                            />
                          </div>
                          <div>
                            <Label htmlFor="email-smtpPort">SMTP Port</Label>
                            <TextInput
                              id="email-smtpPort"
                              type="number"
                              value={services.email?.smtpPort || ''}
                              onChange={(e) => {
                                setServices({
                                  ...services,
                                  email: { ...services.email, smtpPort: parseInt(e.target.value) || 587 }
                                });
                              }}
                              placeholder="587"
                            />
                          </div>
                          <div>
                            <Label htmlFor="email-username">Username</Label>
                            <TextInput
                              id="email-username"
                              value={services.email?.username || ''}
                              onChange={(e) => {
                                setServices({
                                  ...services,
                                  email: { ...services.email, username: e.target.value }
                                });
                              }}
                              placeholder="your-email@gmail.com"
                            />
                          </div>
                          <div>
                            <Label htmlFor="email-to">To</Label>
                            <TextInput
                              id="email-to"
                              value={services.email?.to || ''}
                              onChange={(e) => {
                                setServices({
                                  ...services,
                                  email: { ...services.email, to: e.target.value }
                                });
                              }}
                              placeholder="recipient@example.com"
                            />
                          </div>
                          <div>
                            <Label htmlFor="email-from">From (optional)</Label>
                            <TextInput
                              id="email-from"
                              value={services.email?.from || ''}
                              onChange={(e) => {
                                setServices({
                                  ...services,
                                  email: { ...services.email, from: e.target.value }
                                });
                              }}
                              placeholder="your-email@gmail.com"
                            />
                          </div>
                          <p className="text-xs text-gray-500 dark:text-gray-400">
                            Password stored in sops secrets as "apprise-email-password"
                          </p>
                        </div>
                      )}
                    </Card>

                    {/* Home Assistant Service */}
                    <Card>
                      <div className="flex items-center justify-between mb-4">
                        <h3 className="text-lg font-medium text-gray-900 dark:text-white">Home Assistant</h3>
                        <div className="flex items-center gap-2">
                          <Button
                            onClick={() => handleTestService('homeAssistant')}
                            disabled={testingService === 'homeAssistant' || !services.homeAssistant?.enable || !enable}
                            color="gray"
                            size="xs"
                          >
                            {testingService === 'homeAssistant' ? 'Testing...' : 'Test'}
                          </Button>
                          <ToggleSwitch
                            checked={services.homeAssistant?.enable || false}
                            onChange={(checked) => {
                              setServices({
                                ...services,
                                homeAssistant: { ...services.homeAssistant, enable: checked }
                              });
                            }}
                          />
                        </div>
                      </div>
                      {services.homeAssistant?.enable && (
                        <div className="space-y-4">
                          <div>
                            <Label htmlFor="ha-host">Host</Label>
                            <TextInput
                              id="ha-host"
                              value={services.homeAssistant?.host || ''}
                              onChange={(e) => {
                                setServices({
                                  ...services,
                                  homeAssistant: { ...services.homeAssistant, host: e.target.value }
                                });
                              }}
                              placeholder="homeassistant.local"
                            />
                          </div>
                          <div>
                            <Label htmlFor="ha-port">Port</Label>
                            <TextInput
                              id="ha-port"
                              type="number"
                              value={services.homeAssistant?.port || ''}
                              onChange={(e) => {
                                setServices({
                                  ...services,
                                  homeAssistant: { ...services.homeAssistant, port: parseInt(e.target.value) || 8123 }
                                });
                              }}
                              placeholder="8123"
                            />
                          </div>
                          <div className="flex items-center gap-2">
                            <ToggleSwitch
                              checked={services.homeAssistant?.useHttps || false}
                              onChange={(checked) => {
                                setServices({
                                  ...services,
                                  homeAssistant: { ...services.homeAssistant, useHttps: checked }
                                });
                              }}
                            />
                            <Label htmlFor="ha-useHttps">Use HTTPS</Label>
                          </div>
                          <p className="text-xs text-gray-500 dark:text-gray-400">
                            Access token stored in sops secrets as "apprise-homeassistant-token"
                          </p>
                        </div>
                      )}
                    </Card>

                    {/* Discord Service */}
                    <Card>
                      <div className="flex items-center justify-between mb-4">
                        <h3 className="text-lg font-medium text-gray-900 dark:text-white">Discord</h3>
                        <div className="flex items-center gap-2">
                          <Button
                            onClick={() => handleTestService('discord')}
                            disabled={testingService === 'discord' || !services.discord?.enable || !enable}
                            color="gray"
                            size="xs"
                          >
                            {testingService === 'discord' ? 'Testing...' : 'Test'}
                          </Button>
                          <ToggleSwitch
                            checked={services.discord?.enable || false}
                            onChange={(checked) => {
                              setServices({
                                ...services,
                                discord: { ...services.discord, enable: checked }
                              });
                            }}
                          />
                        </div>
                      </div>
                      {services.discord?.enable && (
                        <p className="text-xs text-gray-500 dark:text-gray-400">
                          Webhook ID and token stored in sops secrets:
                          <br />- "apprise-discord-webhook-id"
                          <br />- "apprise-discord-webhook-token"
                        </p>
                      )}
                    </Card>

                    {/* Slack Service */}
                    <Card>
                      <div className="flex items-center justify-between mb-4">
                        <h3 className="text-lg font-medium text-gray-900 dark:text-white">Slack</h3>
                        <div className="flex items-center gap-2">
                          <Button
                            onClick={() => handleTestService('slack')}
                            disabled={testingService === 'slack' || !services.slack?.enable || !enable}
                            color="gray"
                            size="xs"
                          >
                            {testingService === 'slack' ? 'Testing...' : 'Test'}
                          </Button>
                          <ToggleSwitch
                            checked={services.slack?.enable || false}
                            onChange={(checked) => {
                              setServices({
                                ...services,
                                slack: { ...services.slack, enable: checked }
                              });
                            }}
                          />
                        </div>
                      </div>
                      {services.slack?.enable && (
                        <p className="text-xs text-gray-500 dark:text-gray-400">
                          Tokens stored in sops secrets:
                          <br />- "apprise-slack-token-a"
                          <br />- "apprise-slack-token-b"
                          <br />- "apprise-slack-token-c"
                        </p>
                      )}
                    </Card>

                    {/* Telegram Service */}
                    <Card>
                      <div className="flex items-center justify-between mb-4">
                        <h3 className="text-lg font-medium text-gray-900 dark:text-white">Telegram</h3>
                        <div className="flex items-center gap-2">
                          <Button
                            onClick={() => handleTestService('telegram')}
                            disabled={testingService === 'telegram' || !services.telegram?.enable || !enable}
                            color="gray"
                            size="xs"
                          >
                            {testingService === 'telegram' ? 'Testing...' : 'Test'}
                          </Button>
                          <ToggleSwitch
                            checked={services.telegram?.enable || false}
                            onChange={(checked) => {
                              setServices({
                                ...services,
                                telegram: { ...services.telegram, enable: checked }
                              });
                            }}
                          />
                        </div>
                      </div>
                      {services.telegram?.enable && (
                        <div className="space-y-4">
                          <div>
                            <Label htmlFor="telegram-chatId">Chat ID</Label>
                            <TextInput
                              id="telegram-chatId"
                              value={services.telegram?.chatId || ''}
                              onChange={(e) => {
                                setServices({
                                  ...services,
                                  telegram: { ...services.telegram, chatId: e.target.value }
                                });
                              }}
                              placeholder="123456789"
                            />
                          </div>
                          <p className="text-xs text-gray-500 dark:text-gray-400">
                            Bot token stored in sops secrets as "apprise-telegram-bot-token"
                          </p>
                        </div>
                      )}
                    </Card>

                    {/* ntfy Service */}
                    <Card>
                      <div className="flex items-center justify-between mb-4">
                        <h3 className="text-lg font-medium text-gray-900 dark:text-white">ntfy</h3>
                        <div className="flex items-center gap-2">
                          <Button
                            onClick={() => handleTestService('ntfy')}
                            disabled={testingService === 'ntfy' || !services.ntfy?.enable || !enable}
                            color="gray"
                            size="xs"
                          >
                            {testingService === 'ntfy' ? 'Testing...' : 'Test'}
                          </Button>
                          <ToggleSwitch
                            checked={services.ntfy?.enable || false}
                            onChange={(checked) => {
                              setServices({
                                ...services,
                                ntfy: { ...services.ntfy, enable: checked }
                              });
                            }}
                          />
                        </div>
                      </div>
                      {services.ntfy?.enable && (
                        <div className="space-y-4">
                          <div>
                            <Label htmlFor="ntfy-topic">Topic</Label>
                            <TextInput
                              id="ntfy-topic"
                              value={services.ntfy?.topic || ''}
                              onChange={(e) => {
                                setServices({
                                  ...services,
                                  ntfy: { ...services.ntfy, topic: e.target.value }
                                });
                              }}
                              placeholder="router-notifications"
                            />
                          </div>
                          <div>
                            <Label htmlFor="ntfy-server">Server (optional)</Label>
                            <TextInput
                              id="ntfy-server"
                              value={services.ntfy?.server || ''}
                              onChange={(e) => {
                                setServices({
                                  ...services,
                                  ntfy: { ...services.ntfy, server: e.target.value }
                                });
                              }}
                              placeholder="https://ntfy.sh"
                            />
                          </div>
                          <p className="text-xs text-gray-500 dark:text-gray-400">
                            Username and password stored in sops secrets:
                            <br />- "apprise-ntfy-username"
                            <br />- "apprise-ntfy-password"
                          </p>
                        </div>
                      )}
                    </Card>
                  </div>
                </div>

                <div className="flex justify-end">
                  <Button onClick={handleSave} disabled={saving}>
                    {saving ? 'Saving...' : 'Save Configuration'}
                  </Button>
                </div>
              </div>
            </Card>
          </div>
        </main>
      </div>
    </div>
  );
}
