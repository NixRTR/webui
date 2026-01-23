/**
 * Dynamic DNS Configuration Page
 */
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Button, TextInput, Label, Select, Alert } from 'flowbite-react';
import { Sidebar } from '../components/layout/Sidebar';
import { Navbar } from '../components/layout/Navbar';
import { useMetrics } from '../hooks/useMetrics';
import { apiClient } from '../api/client';
import { HiRefresh } from 'react-icons/hi';
import type { DynDnsConfig, DynDnsConfigUpdate } from '../types/dyndns';

export function DynDnsConfig() {
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
  const [provider, setProvider] = useState('linode');
  const [domain, setDomain] = useState('');
  const [subdomain, setSubdomain] = useState('');
  const [domainId, setDomainId] = useState(0);
  const [recordId, setRecordId] = useState(0);
  const [checkInterval, setCheckInterval] = useState('5m');
  
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
      const data = await apiClient.getDynDnsConfig();
      setEnable(data.enable);
      setProvider(data.provider);
      setDomain(data.domain);
      setSubdomain(data.subdomain);
      setDomainId(data.domainId);
      setRecordId(data.recordId);
      setCheckInterval(data.checkInterval);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load Dynamic DNS configuration');
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(null);
    
    try {
      const update: DynDnsConfigUpdate = {
        enable,
        provider,
        domain,
        subdomain,
        domainId,
        recordId,
        checkInterval,
      };
      
      await apiClient.updateDynDnsConfig(update);
      setSuccess('Dynamic DNS configuration saved successfully');
      await fetchConfig();
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Failed to save Dynamic DNS configuration');
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
              <HiRefresh className="w-8 h-8 mr-3 text-blue-600 dark:text-blue-400" />
              <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Dynamic DNS</h1>
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
                    Enable Dynamic DNS
                  </Label>
                  <Select id="enable" value={enable ? 'true' : 'false'} onChange={(e) => setEnable(e.target.value === 'true')}>
                    <option value="true">Enabled</option>
                    <option value="false">Disabled</option>
                  </Select>
                </div>

                <div>
                  <Label htmlFor="provider" className="mb-2 block">
                    Provider
                  </Label>
                  <Select id="provider" value={provider} onChange={(e) => setProvider(e.target.value)}>
                    <option value="linode">Linode</option>
                  </Select>
                </div>

                <div>
                  <Label htmlFor="domain" className="mb-2 block">
                    Domain
                  </Label>
                  <TextInput
                    id="domain"
                    type="text"
                    placeholder="example.com"
                    value={domain}
                    onChange={(e) => setDomain(e.target.value)}
                  />
                </div>

                <div>
                  <Label htmlFor="subdomain" className="mb-2 block">
                    Subdomain (leave empty for root domain)
                  </Label>
                  <TextInput
                    id="subdomain"
                    type="text"
                    placeholder=""
                    value={subdomain}
                    onChange={(e) => setSubdomain(e.target.value)}
                  />
                </div>

                <div>
                  <Label htmlFor="domainId" className="mb-2 block">
                    Domain ID
                  </Label>
                  <TextInput
                    id="domainId"
                    type="number"
                    value={domainId}
                    onChange={(e) => setDomainId(parseInt(e.target.value) || 0)}
                  />
                </div>

                <div>
                  <Label htmlFor="recordId" className="mb-2 block">
                    Record ID
                  </Label>
                  <TextInput
                    id="recordId"
                    type="number"
                    value={recordId}
                    onChange={(e) => setRecordId(parseInt(e.target.value) || 0)}
                  />
                </div>

                <div>
                  <Label htmlFor="checkInterval" className="mb-2 block">
                    Check Interval
                  </Label>
                  <TextInput
                    id="checkInterval"
                    type="text"
                    placeholder="5m"
                    value={checkInterval}
                    onChange={(e) => setCheckInterval(e.target.value)}
                  />
                  <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                    How often to check and update the DNS record (e.g., 5m, 1h)
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
