/**
 * CAKE Traffic Shaping Configuration Page
 */
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Button, TextInput, Label, Select, Alert } from 'flowbite-react';
import { Sidebar } from '../components/layout/Sidebar';
import { Navbar } from '../components/layout/Navbar';
import { useMetrics } from '../hooks/useMetrics';
import { apiClient } from '../api/client';
import { HiTrendingUp } from 'react-icons/hi';
import type { CakeConfig, CakeConfigUpdate } from '../types/cake';

export function CakeConfig() {
  const token = localStorage.getItem('access_token');
  const username = localStorage.getItem('username') || 'Unknown';
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  
  // Form state
  const [enable, setEnable] = useState(false);
  const [aggressiveness, setAggressiveness] = useState<'auto' | 'conservative' | 'moderate' | 'aggressive'>('auto');
  const [uploadBandwidth, setUploadBandwidth] = useState('');
  const [downloadBandwidth, setDownloadBandwidth] = useState('');
  
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
      const data = await apiClient.getCakeConfig();
      setEnable(data.enable);
      setAggressiveness(data.aggressiveness);
      setUploadBandwidth(data.uploadBandwidth || '');
      setDownloadBandwidth(data.downloadBandwidth || '');
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load CAKE configuration');
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(null);
    
    try {
      const update: CakeConfigUpdate = {
        enable,
        aggressiveness,
        uploadBandwidth: uploadBandwidth || null,
        downloadBandwidth: downloadBandwidth || null,
      };
      
      await apiClient.updateCakeConfig(update);
      setSuccess('CAKE configuration saved successfully');
      await fetchConfig();
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Failed to save CAKE configuration');
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
              <HiTrendingUp className="w-8 h-8 mr-3 text-blue-600 dark:text-blue-400" />
              <h1 className="text-3xl font-bold text-gray-900 dark:text-white">CAKE Traffic Shaping</h1>
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
                    Enable CAKE
                  </Label>
                  <Select id="enable" value={enable ? 'true' : 'false'} onChange={(e) => setEnable(e.target.value === 'true')}>
                    <option value="true">Enabled</option>
                    <option value="false">Disabled</option>
                  </Select>
                </div>

                <div>
                  <Label htmlFor="aggressiveness" className="mb-2 block">
                    Aggressiveness
                  </Label>
                  <Select id="aggressiveness" value={aggressiveness} onChange={(e) => setAggressiveness(e.target.value as any)}>
                    <option value="auto">Auto (Recommended)</option>
                    <option value="conservative">Conservative</option>
                    <option value="moderate">Moderate</option>
                    <option value="aggressive">Aggressive</option>
                  </Select>
                  <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                    Controls how aggressively CAKE shapes traffic to reduce latency
                  </p>
                </div>

                <div>
                  <Label htmlFor="uploadBandwidth" className="mb-2 block">
                    Upload Bandwidth (Optional)
                  </Label>
                  <TextInput
                    id="uploadBandwidth"
                    type="text"
                    placeholder="e.g., 190Mbit"
                    value={uploadBandwidth}
                    onChange={(e) => setUploadBandwidth(e.target.value)}
                  />
                  <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                    Set to ~95% of your actual upload speed (e.g., 190Mbit for 200Mbit)
                  </p>
                </div>

                <div>
                  <Label htmlFor="downloadBandwidth" className="mb-2 block">
                    Download Bandwidth (Optional)
                  </Label>
                  <TextInput
                    id="downloadBandwidth"
                    type="text"
                    placeholder="e.g., 475Mbit"
                    value={downloadBandwidth}
                    onChange={(e) => setDownloadBandwidth(e.target.value)}
                  />
                  <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                    Set to ~95% of your actual download speed (e.g., 475Mbit for 500Mbit)
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
