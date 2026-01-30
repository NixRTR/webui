/**
 * DNS Blocklists and Whitelist Configuration Page
 */
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Button, TextInput, Label, Select, Alert, Table, ToggleSwitch } from 'flowbite-react';
import { Sidebar } from '../components/layout/Sidebar';
import { Navbar } from '../components/layout/Navbar';
import { useMetrics } from '../hooks/useMetrics';
import { apiClient } from '../api/client';
import { HiShieldCheck, HiPlus, HiTrash } from 'react-icons/hi';
import type { BlocklistsConfig, BlocklistsConfigUpdate } from '../types/blocklists';
import type { WhitelistConfig, WhitelistConfigUpdate } from '../types/whitelist';

export function BlocklistsWhitelist() {
  const token = localStorage.getItem('access_token');
  const username = localStorage.getItem('username') || 'Unknown';
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  
  // Blocklists state
  const [blocklistsHomelab, setBlocklistsHomelab] = useState<BlocklistsConfig | null>(null);
  const [blocklistsLan, setBlocklistsLan] = useState<BlocklistsConfig | null>(null);
  
  // Whitelist state
  const [whitelistHomelab, setWhitelistHomelab] = useState<WhitelistConfig | null>(null);
  const [whitelistLan, setWhitelistLan] = useState<WhitelistConfig | null>(null);
  
  // New domain input
  const [newDomain, setNewDomain] = useState('');
  const [newDomainNetwork, setNewDomainNetwork] = useState<'homelab' | 'lan'>('homelab');
  
  const { connectionStatus } = useMetrics(token);

  useEffect(() => {
    if (!token) {
      navigate('/login');
      return;
    }
    fetchAll();
  }, [token, navigate]);

  const fetchAll = async () => {
    setLoading(true);
    setError(null);
    try {
      const [blHomelab, blLan, wlHomelab, wlLan] = await Promise.all([
        apiClient.getBlocklists('homelab'),
        apiClient.getBlocklists('lan'),
        apiClient.getWhitelist('homelab'),
        apiClient.getWhitelist('lan'),
      ]);
      setBlocklistsHomelab(blHomelab);
      setBlocklistsLan(blLan);
      setWhitelistHomelab(wlHomelab);
      setWhitelistLan(wlLan);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load configuration');
    } finally {
      setLoading(false);
    }
  };

  const handleBlocklistToggle = async (network: 'homelab' | 'lan', enable: boolean) => {
    setError(null);
    try {
      const current = network === 'homelab' ? blocklistsHomelab : blocklistsLan;
      if (!current) return;
      
      const update: BlocklistsConfigUpdate = {
        enable,
        blocklists: current.blocklists,
      };
      
      if (network === 'homelab') {
        await apiClient.updateBlocklists('homelab', update);
        setBlocklistsHomelab({ ...current, enable });
      } else {
        await apiClient.updateBlocklists('lan', update);
        setBlocklistsLan({ ...current, enable });
      }
      setSuccess(`Blocklists ${enable ? 'enabled' : 'disabled'} for ${network.toUpperCase()}`);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Failed to update blocklists');
    }
  };

  const handleBlocklistItemToggle = async (network: 'homelab' | 'lan', blocklistName: string, enable: boolean) => {
    setError(null);
    try {
      const current = network === 'homelab' ? blocklistsHomelab : blocklistsLan;
      if (!current) return;
      
      const updatedBlocklists = {
        ...current.blocklists,
        [blocklistName]: {
          ...current.blocklists[blocklistName],
          enable,
        },
      };
      
      const update: BlocklistsConfigUpdate = {
        enable: current.enable,
        blocklists: updatedBlocklists,
      };
      
      if (network === 'homelab') {
        await apiClient.updateBlocklists('homelab', update);
        setBlocklistsHomelab({ ...current, blocklists: updatedBlocklists });
      } else {
        await apiClient.updateBlocklists('lan', update);
        setBlocklistsLan({ ...current, blocklists: updatedBlocklists });
      }
      setSuccess(`Blocklist ${blocklistName} ${enable ? 'enabled' : 'disabled'} for ${network.toUpperCase()}`);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Failed to update blocklist');
    }
  };

  const handleAddDomain = async () => {
    if (!newDomain.trim()) {
      setError('Please enter a domain');
      return;
    }
    
    setError(null);
    try {
      const current = newDomainNetwork === 'homelab' ? whitelistHomelab : whitelistLan;
      if (!current) return;
      
      const updatedDomains = [...current.domains, newDomain.trim()];
      const update: WhitelistConfigUpdate = {
        domains: updatedDomains,
      };
      
      if (newDomainNetwork === 'homelab') {
        await apiClient.updateWhitelist('homelab', update);
        setWhitelistHomelab({ domains: updatedDomains });
      } else {
        await apiClient.updateWhitelist('lan', update);
        setWhitelistLan({ domains: updatedDomains });
      }
      setNewDomain('');
      setSuccess(`Domain added to ${newDomainNetwork.toUpperCase()} whitelist`);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Failed to add domain');
    }
  };

  const handleRemoveDomain = async (network: 'homelab' | 'lan', domain: string) => {
    setError(null);
    try {
      const current = network === 'homelab' ? whitelistHomelab : whitelistLan;
      if (!current) return;
      
      const updatedDomains = current.domains.filter(d => d !== domain);
      const update: WhitelistConfigUpdate = {
        domains: updatedDomains,
      };
      
      if (network === 'homelab') {
        await apiClient.updateWhitelist('homelab', update);
        setWhitelistHomelab({ domains: updatedDomains });
      } else {
        await apiClient.updateWhitelist('lan', update);
        setWhitelistLan({ domains: updatedDomains });
      }
      setSuccess(`Domain removed from ${network.toUpperCase()} whitelist`);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Failed to remove domain');
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
          <div className="max-w-6xl mx-auto space-y-6">
            <div className="flex items-center mb-6">
              <HiShieldCheck className="w-8 h-8 mr-3 text-blue-600 dark:text-blue-400" />
              <h1 className="text-3xl font-bold text-gray-900 dark:text-white">DNS Blocklists & Whitelist</h1>
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

            {/* Blocklists Section */}
            <Card>
              <h2 className="text-2xl font-bold mb-4">DNS Blocklists</h2>
              
              {/* HOMELAB Blocklists */}
              <div className="mb-6">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-xl font-semibold">HOMELAB</h3>
                  <div className="flex items-center space-x-2">
                    <Label>Master Enable</Label>
                    <ToggleSwitch
                      checked={blocklistsHomelab?.enable || false}
                      onChange={(checked) => handleBlocklistToggle('homelab', checked)}
                    />
                  </div>
                </div>
                {blocklistsHomelab && Object.keys(blocklistsHomelab.blocklists).length > 0 ? (
                  <Table>
                    <Table.Head>
                      <Table.HeadCell>Blocklist</Table.HeadCell>
                      <Table.HeadCell>Description</Table.HeadCell>
                      <Table.HeadCell>URL</Table.HeadCell>
                      <Table.HeadCell>Update Interval</Table.HeadCell>
                      <Table.HeadCell>Enabled</Table.HeadCell>
                    </Table.Head>
                    <Table.Body>
                      {Object.entries(blocklistsHomelab.blocklists).map(([name, item]) => (
                        <Table.Row key={name}>
                          <Table.Cell className="font-medium">{name}</Table.Cell>
                          <Table.Cell>{item.description}</Table.Cell>
                          <Table.Cell className="text-sm text-gray-500">{item.url}</Table.Cell>
                          <Table.Cell>{item.updateInterval}</Table.Cell>
                          <Table.Cell>
                            <ToggleSwitch
                              checked={item.enable}
                              onChange={(checked) => handleBlocklistItemToggle('homelab', name, checked)}
                            />
                          </Table.Cell>
                        </Table.Row>
                      ))}
                    </Table.Body>
                  </Table>
                ) : (
                  <p className="text-gray-500 dark:text-gray-400">No blocklists configured</p>
                )}
              </div>

              {/* LAN Blocklists */}
              <div>
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-xl font-semibold">LAN</h3>
                  <div className="flex items-center space-x-2">
                    <Label>Master Enable</Label>
                    <ToggleSwitch
                      checked={blocklistsLan?.enable || false}
                      onChange={(checked) => handleBlocklistToggle('lan', checked)}
                    />
                  </div>
                </div>
                {blocklistsLan && Object.keys(blocklistsLan.blocklists).length > 0 ? (
                  <Table>
                    <Table.Head>
                      <Table.HeadCell>Blocklist</Table.HeadCell>
                      <Table.HeadCell>Description</Table.HeadCell>
                      <Table.HeadCell>URL</Table.HeadCell>
                      <Table.HeadCell>Update Interval</Table.HeadCell>
                      <Table.HeadCell>Enabled</Table.HeadCell>
                    </Table.Head>
                    <Table.Body>
                      {Object.entries(blocklistsLan.blocklists).map(([name, item]) => (
                        <Table.Row key={name}>
                          <Table.Cell className="font-medium">{name}</Table.Cell>
                          <Table.Cell>{item.description}</Table.Cell>
                          <Table.Cell className="text-sm text-gray-500">{item.url}</Table.Cell>
                          <Table.Cell>{item.updateInterval}</Table.Cell>
                          <Table.Cell>
                            <ToggleSwitch
                              checked={item.enable}
                              onChange={(checked) => handleBlocklistItemToggle('lan', name, checked)}
                            />
                          </Table.Cell>
                        </Table.Row>
                      ))}
                    </Table.Body>
                  </Table>
                ) : (
                  <p className="text-gray-500 dark:text-gray-400">No blocklists configured</p>
                )}
              </div>
            </Card>

            {/* Whitelist Section */}
            <Card>
              <h2 className="text-2xl font-bold mb-4">DNS Whitelist</h2>
              
              {/* Add Domain */}
              <div className="mb-6 flex space-x-2">
                <TextInput
                  placeholder="example.com"
                  value={newDomain}
                  onChange={(e) => setNewDomain(e.target.value)}
                  className="flex-1"
                />
                <Select value={newDomainNetwork} onChange={(e) => setNewDomainNetwork(e.target.value as any)}>
                  <option value="homelab">HOMELAB</option>
                  <option value="lan">LAN</option>
                </Select>
                <Button onClick={handleAddDomain}>
                  <HiPlus className="w-5 h-5 mr-2" />
                  Add Domain
                </Button>
              </div>

              {/* HOMELAB Whitelist */}
              <div className="mb-6">
                <h3 className="text-xl font-semibold mb-3">HOMELAB</h3>
                {whitelistHomelab && whitelistHomelab.domains.length > 0 ? (
                  <div className="space-y-2">
                    {whitelistHomelab.domains.map((domain) => (
                      <div key={domain} className="flex items-center justify-between p-2 bg-gray-50 dark:bg-gray-800 rounded">
                        <span>{domain}</span>
                        <Button size="xs" color="failure" onClick={() => handleRemoveDomain('homelab', domain)}>
                          <HiTrash className="w-4 h-4" />
                        </Button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-gray-500 dark:text-gray-400">No domains whitelisted</p>
                )}
              </div>

              {/* LAN Whitelist */}
              <div>
                <h3 className="text-xl font-semibold mb-3">LAN</h3>
                {whitelistLan && whitelistLan.domains.length > 0 ? (
                  <div className="space-y-2">
                    {whitelistLan.domains.map((domain) => (
                      <div key={domain} className="flex items-center justify-between p-2 bg-gray-50 dark:bg-gray-800 rounded">
                        <span>{domain}</span>
                        <Button size="xs" color="failure" onClick={() => handleRemoveDomain('lan', domain)}>
                          <HiTrash className="w-4 h-4" />
                        </Button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-gray-500 dark:text-gray-400">No domains whitelisted</p>
                )}
              </div>
            </Card>
          </div>
        </main>
      </div>
    </div>
  );
}
