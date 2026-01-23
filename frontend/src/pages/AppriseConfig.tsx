/**
 * Apprise Configuration Page
 */
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Button, TextInput, Label, Select, Alert } from 'flowbite-react';
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
      const update: AppriseConfigUpdate = {
        enable,
        port,
        attachSize,
        // Services configuration would be added here
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
