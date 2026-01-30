/**
 * DHCP Management Page
 */
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Button, TextInput, Label, Select, Badge, Alert, Modal, Table, Checkbox } from 'flowbite-react';
import { Sidebar } from '../components/layout/Sidebar';
import { Navbar } from '../components/layout/Navbar';
import { useMetrics } from '../hooks/useMetrics';
import { apiClient } from '../api/client';
import { HiServer, HiPencil, HiTrash, HiPlus, HiInformationCircle, HiPlay, HiStop, HiRefresh } from 'react-icons/hi';
import type { DhcpNetwork, DhcpNetworkCreate, DhcpNetworkUpdate, DhcpReservation, DhcpReservationCreate, DhcpReservationUpdate } from '../types/dhcp';

export function Dhcp() {
  const token = localStorage.getItem('access_token');
  const username = localStorage.getItem('username') || 'Unknown';
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [networks, setNetworks] = useState<DhcpNetwork[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dhcpServiceStatuses, setDhcpServiceStatuses] = useState<Record<string, { is_active: boolean; is_enabled: boolean; exists: boolean }>>({});
  const [controllingDhcpService, setControllingDhcpService] = useState<string | null>(null);
  
  // Network modal state
  const [networkModalOpen, setNetworkModalOpen] = useState(false);
  const [editingNetwork, setEditingNetwork] = useState<DhcpNetwork | null>(null);
  const [networkNetwork, setNetworkNetwork] = useState<'homelab' | 'lan'>('homelab');
  const [networkEnabled, setNetworkEnabled] = useState(true);
  const [networkStart, setNetworkStart] = useState('');
  const [networkEnd, setNetworkEnd] = useState('');
  const [networkLeaseTime, setNetworkLeaseTime] = useState('1h');
  const [networkDnsServers, setNetworkDnsServers] = useState('');
  const [networkDynamicDomain, setNetworkDynamicDomain] = useState('');
  const [saving, setSaving] = useState(false);
  const [networkError, setNetworkError] = useState<string | null>(null);
  
  // Reservation modal state
  const [reservationsViewModalOpen, setReservationsViewModalOpen] = useState(false);
  const [reservationEditModalOpen, setReservationEditModalOpen] = useState(false);
  const [selectedNetwork, setSelectedNetwork] = useState<DhcpNetwork | null>(null);
  const [reservations, setReservations] = useState<DhcpReservation[]>([]);
  const [editingReservation, setEditingReservation] = useState<DhcpReservation | null>(null);
  const [reservationHostname, setReservationHostname] = useState('');
  const [reservationHwAddress, setReservationHwAddress] = useState('');
  const [reservationIpAddress, setReservationIpAddress] = useState('');
  const [reservationComment, setReservationComment] = useState('');
  const [reservationEnabled, setReservationEnabled] = useState(true);
  const [reservationError, setReservationError] = useState<string | null>(null);
  
  // Delete confirmation
  const [deleteNetworkModalOpen, setDeleteNetworkModalOpen] = useState(false);
  const [deleteReservationModalOpen, setDeleteReservationModalOpen] = useState(false);
  const [networkToDelete, setNetworkToDelete] = useState<DhcpNetwork | null>(null);
  const [reservationToDelete, setReservationToDelete] = useState<DhcpReservation | null>(null);
  
  const { connectionStatus } = useMetrics(token);

  useEffect(() => {
    if (!token) {
      navigate('/login');
      return;
    }
    fetchNetworks();
    fetchDhcpServiceStatuses();
  }, [token, navigate]);

  const fetchDhcpServiceStatuses = async () => {
    try {
      const [homelabStatus, lanStatus] = await Promise.all([
        apiClient.getDhcpServiceStatus('homelab'),
        apiClient.getDhcpServiceStatus('lan'),
      ]);
      setDhcpServiceStatuses({
        homelab: homelabStatus,
        lan: lanStatus,
      });
    } catch (err: any) {
      console.error('Failed to fetch DHCP service statuses:', err);
    }
  };

  const handleDhcpServiceControl = async (network: 'homelab' | 'lan', action: 'start' | 'stop' | 'restart' | 'reload') => {
    const serviceKey = `${network}-${action}`;
    setControllingDhcpService(serviceKey);
    try {
      await apiClient.controlDhcpService(network, action);
      // Refresh service status after a short delay
      setTimeout(() => {
        fetchDhcpServiceStatuses();
      }, 1000);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || `Failed to ${action} DHCP service for ${network}`);
    } finally {
      setControllingDhcpService(null);
    }
  };

  const fetchNetworks = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.getDhcpNetworks();
      setNetworks(data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load DHCP networks');
    } finally {
      setLoading(false);
    }
  };

  const fetchReservations = async (network: string) => {
    try {
      const data = await apiClient.getDhcpReservations(network);
      setReservations(data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load DHCP reservations');
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('username');
    navigate('/login');
  };

  const openNetworkModal = (network?: DhcpNetwork, networkType?: 'homelab' | 'lan') => {
    if (network) {
      setEditingNetwork(network);
      setNetworkNetwork(network.network);
      setNetworkEnabled(network.enabled);
      setNetworkStart(network.start);
      setNetworkEnd(network.end);
      setNetworkLeaseTime(network.lease_time);
      setNetworkDnsServers(network.dns_servers?.join(', ') || '');
      setNetworkDynamicDomain(network.dynamic_domain || '');
    } else {
      setEditingNetwork(null);
      setNetworkNetwork(networkType || 'homelab');
      setNetworkEnabled(true);
      setNetworkStart('');
      setNetworkEnd('');
      setNetworkLeaseTime('1h');
      setNetworkDnsServers('');
      setNetworkDynamicDomain('');
    }
    setNetworkError(null);
    setNetworkModalOpen(true);
  };

  const closeNetworkModal = () => {
    setNetworkModalOpen(false);
    setEditingNetwork(null);
    setNetworkError(null);
  };

  const handleSaveNetwork = async () => {
    setNetworkError(null);
    setSaving(true);
    
    try {
      if (!networkStart.trim() || !networkEnd.trim()) {
        setNetworkError('Start and end IP addresses are required');
        setSaving(false);
        return;
      }
      
      const dnsServersList = networkDnsServers.trim()
        ? networkDnsServers.split(',').map(s => s.trim()).filter(s => s)
        : null;
      
      if (editingNetwork) {
        const update: DhcpNetworkUpdate = {
          enabled: networkEnabled,
          start: networkStart.trim(),
          end: networkEnd.trim(),
          lease_time: networkLeaseTime.trim(),
          dns_servers: dnsServersList,
          dynamic_domain: networkDynamicDomain.trim() || null,
        };
        await apiClient.updateDhcpNetwork(editingNetwork.network, update);
      } else {
        const create: DhcpNetworkCreate = {
          network: networkNetwork,
          enabled: networkEnabled,
          start: networkStart.trim(),
          end: networkEnd.trim(),
          lease_time: networkLeaseTime.trim(),
          dns_servers: dnsServersList,
          dynamic_domain: networkDynamicDomain.trim() || null,
        };
        await apiClient.createDhcpNetwork(create);
      }
      
      await fetchNetworks();
      closeNetworkModal();
    } catch (err: any) {
      const errorMessage = err?.response?.data?.detail || err.message || 'Failed to save network';
      // Check if error indicates networks must be configured in router-config.nix
      if (errorMessage.includes('router-config.nix') || errorMessage.includes('cannot be')) {
        setNetworkError('DHCP networks cannot be managed via WebUI. They must be configured in router-config.nix. Only reservations can be managed through the WebUI.');
      } else {
        setNetworkError(errorMessage);
      }
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteNetwork = async () => {
    if (!networkToDelete) return;
    
    try {
      await apiClient.deleteDhcpNetwork(networkToDelete.network);
      await fetchNetworks();
      setDeleteNetworkModalOpen(false);
      setNetworkToDelete(null);
    } catch (err: any) {
      const errorMessage = err?.response?.data?.detail || err.message || 'Failed to delete network';
      // Check if error indicates networks must be configured in router-config.nix
      if (errorMessage.includes('router-config.nix') || errorMessage.includes('cannot be')) {
        setError('DHCP networks cannot be deleted via WebUI. They must be removed from router-config.nix. Only reservations can be managed through the WebUI.');
      } else {
        setError(errorMessage);
      }
    }
  };

  const openReservationsView = async (network: DhcpNetwork) => {
    setSelectedNetwork(network);
    await fetchReservations(network.network);
    setReservationsViewModalOpen(true);
  };

  const closeReservationsView = () => {
    setReservationsViewModalOpen(false);
    setSelectedNetwork(null);
    setReservations([]);
  };

  const openReservationEditModal = (reservation?: DhcpReservation) => {
    if (reservation) {
      setEditingReservation(reservation);
      setReservationHostname(reservation.hostname);
      setReservationHwAddress(reservation.hw_address);
      setReservationIpAddress(reservation.ip_address);
      setReservationComment(reservation.comment || '');
      setReservationEnabled(reservation.enabled);
    } else {
      setEditingReservation(null);
      setReservationHostname('');
      setReservationHwAddress('');
      setReservationIpAddress('');
      setReservationComment('');
      setReservationEnabled(true);
    }
    setReservationError(null);
    setReservationEditModalOpen(true);
  };

  const closeReservationEditModal = () => {
    setReservationEditModalOpen(false);
    setEditingReservation(null);
    setReservationError(null);
    if (selectedNetwork) {
      fetchReservations(selectedNetwork.network);
    }
  };

  const handleSaveReservation = async () => {
    if (!selectedNetwork) return;
    
    setReservationError(null);
    setSaving(true);
    
    try {
      if (!reservationHostname.trim()) {
        setReservationError('Hostname is required');
        setSaving(false);
        return;
      }
      
      if (!reservationHwAddress.trim()) {
        setReservationError('MAC address is required');
        setSaving(false);
        return;
      }
      
      if (!reservationIpAddress.trim()) {
        setReservationError('IP address is required');
        setSaving(false);
        return;
      }
      
      if (editingReservation) {
        const update: DhcpReservationUpdate = {
          hostname: reservationHostname.trim(),
          hw_address: reservationHwAddress.trim(),
          ip_address: reservationIpAddress.trim(),
          comment: reservationComment.trim() || null,
          enabled: reservationEnabled,
        };
        await apiClient.updateDhcpReservation(editingReservation.hw_address, selectedNetwork.network, update);
      } else {
        const create: DhcpReservationCreate = {
          hostname: reservationHostname.trim(),
          hw_address: reservationHwAddress.trim(),
          ip_address: reservationIpAddress.trim(),
          comment: reservationComment.trim() || null,
          enabled: reservationEnabled,
        };
        await apiClient.createDhcpReservation(selectedNetwork.network, create);
      }
      
      await fetchReservations(selectedNetwork.network);
      closeReservationEditModal();
    } catch (err: any) {
      setReservationError(err?.response?.data?.detail || err.message || 'Failed to save reservation');
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteReservation = async () => {
    if (!reservationToDelete || !selectedNetwork) return;
    
    try {
      await apiClient.deleteDhcpReservation(reservationToDelete.hw_address, selectedNetwork.network);
      await fetchReservations(selectedNetwork.network);
      setDeleteReservationModalOpen(false);
      setReservationToDelete(null);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Failed to delete reservation');
    }
  };

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600 dark:text-gray-400">Loading DHCP networks...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen">
      <Sidebar onLogout={handleLogout} isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />
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
                <HiServer className="w-8 h-8 text-gray-900 dark:text-white" />
                <h1 className="text-3xl font-bold text-gray-900 dark:text-white">DHCP Management</h1>
              </div>
            </div>

            {error && (
              <Alert color="failure" className="mb-6" onDismiss={() => setError(null)}>
                {error}
              </Alert>
            )}

            {/* HOMELAB Section */}
            <Card className="mb-6">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-4">
                  <h2 className="text-2xl font-semibold text-gray-900 dark:text-white">HOMELAB</h2>
                  {(() => {
                    const status = dhcpServiceStatuses['homelab'];
                    const serviceKey = 'homelab-';
                    const isControlling = controllingDhcpService?.startsWith(serviceKey);
                    return (
                      <div className="flex gap-2 items-center flex-wrap">
                        {status && (
                          <Badge color={status.is_active ? "success" : "gray"} size="sm">
                            {status.is_active ? "Running" : status.is_enabled ? "Stopped" : "Disabled"}
                          </Badge>
                        )}
                        <Button
                          size="xs"
                          color="success"
                          onClick={() => handleDhcpServiceControl('homelab', 'start')}
                          disabled={isControlling || (status?.is_active ?? false)}
                          title="Start Service"
                        >
                          <HiPlay className="w-4 h-4" />
                        </Button>
                        <Button
                          size="xs"
                          color="failure"
                          onClick={() => handleDhcpServiceControl('homelab', 'stop')}
                          disabled={isControlling || !(status?.is_active ?? false)}
                          title="Stop Service"
                        >
                          <HiStop className="w-4 h-4" />
                        </Button>
                        <Button
                          size="xs"
                          color="warning"
                          onClick={() => handleDhcpServiceControl('homelab', 'reload')}
                          disabled={isControlling || !(status?.is_active ?? false)}
                          title="Reload Service"
                        >
                          <HiRefresh className="w-4 h-4" />
                        </Button>
                        <Button
                          size="xs"
                          color="purple"
                          onClick={() => handleDhcpServiceControl('homelab', 'restart')}
                          disabled={isControlling}
                          title="Restart Service"
                        >
                          <HiRefresh className="w-4 h-4" />
                        </Button>
                      </div>
                    );
                  })()}
                </div>
              </div>
              
              {(() => {
                const homelabNetwork = networks.find(n => n.network === 'homelab');
                return !homelabNetwork ? (
                  <Alert color="info" icon={HiInformationCircle}>
                    No DHCP network configured for HOMELAB.
                  </Alert>
                ) : (
                  <>
                    {/* Desktop Table View */}
                    <div className="hidden min-[1000px]:block overflow-x-auto">
                      <Table>
                        <Table.Head>
                          <Table.HeadCell>IP Range</Table.HeadCell>
                          <Table.HeadCell>Lease Time</Table.HeadCell>
                          <Table.HeadCell>DNS Servers</Table.HeadCell>
                          <Table.HeadCell>Dynamic Domain</Table.HeadCell>
                          <Table.HeadCell>Status</Table.HeadCell>
                          <Table.HeadCell>Actions</Table.HeadCell>
                        </Table.Head>
                        <Table.Body className="divide-y">
                          <Table.Row key={homelabNetwork.id} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                            <Table.Cell className="font-mono text-sm text-gray-900 dark:text-white">
                              {homelabNetwork.start} - {homelabNetwork.end}
                            </Table.Cell>
                            <Table.Cell className="text-gray-500 dark:text-gray-400">
                              {homelabNetwork.lease_time}
                            </Table.Cell>
                            <Table.Cell className="text-gray-500 dark:text-gray-400">
                              {homelabNetwork.dns_servers?.join(', ') || '-'}
                            </Table.Cell>
                            <Table.Cell className="text-gray-500 dark:text-gray-400">
                              {homelabNetwork.dynamic_domain || '-'}
                            </Table.Cell>
                            <Table.Cell>
                              <Badge color={homelabNetwork.enabled ? "success" : "gray"}>
                                {homelabNetwork.enabled ? "Enabled" : "Disabled"}
                              </Badge>
                            </Table.Cell>
                            <Table.Cell>
                              <div className="flex gap-2 flex-wrap">
                                <Button
                                  size="xs"
                                  color="blue"
                                  onClick={() => openReservationsView(homelabNetwork)}
                                >
                                  Reservations
                                </Button>
                                <Button
                                  size="xs"
                                  color="gray"
                                  onClick={() => openNetworkModal(homelabNetwork)}
                                >
                                  <HiPencil className="w-4 h-4" />
                                </Button>
                                <Button
                                  size="xs"
                                  color="failure"
                                  onClick={() => {
                                    setNetworkToDelete(homelabNetwork);
                                    setDeleteNetworkModalOpen(true);
                                  }}
                                >
                                  <HiTrash className="w-4 h-4" />
                                </Button>
                              </div>
                            </Table.Cell>
                          </Table.Row>
                        </Table.Body>
                      </Table>
                    </div>

                    {/* Mobile/Tablet Card View */}
                    <div className="min-[1000px]:hidden">
                      <div className="p-4 rounded-lg border bg-white border-gray-200 dark:bg-gray-800 dark:border-gray-700">
                        {/* Header Row */}
                        <div className="flex justify-between items-start mb-3">
                          <div className="flex-1">
                            <div className="font-mono text-sm text-gray-900 dark:text-white">
                              {homelabNetwork.start} - {homelabNetwork.end}
                            </div>
                          </div>
                          <Badge color={homelabNetwork.enabled ? "success" : "gray"} size="sm">
                            {homelabNetwork.enabled ? "Enabled" : "Disabled"}
                          </Badge>
                        </div>

                        {/* Details Grid */}
                        <div className="space-y-2 text-sm mb-4">
                          <div className="flex justify-between">
                            <span className="text-gray-500 dark:text-gray-400">Lease Time:</span>
                            <span className="text-gray-900 dark:text-gray-100">{homelabNetwork.lease_time}</span>
                          </div>
                          
                          {homelabNetwork.dns_servers && homelabNetwork.dns_servers.length > 0 && (
                            <div className="flex justify-between">
                              <span className="text-gray-500 dark:text-gray-400">DNS Servers:</span>
                              <span className="text-gray-900 dark:text-gray-100 font-mono text-xs">{homelabNetwork.dns_servers.join(', ')}</span>
                            </div>
                          )}
                          
                          {homelabNetwork.dynamic_domain && (
                            <div className="flex justify-between">
                              <span className="text-gray-500 dark:text-gray-400">Dynamic Domain:</span>
                              <span className="text-gray-900 dark:text-gray-100">{homelabNetwork.dynamic_domain}</span>
                            </div>
                          )}
                        </div>

                        {/* Action Buttons */}
                        <div className="pt-3 border-t border-gray-200 dark:border-gray-700">
                          <div className="flex gap-2 flex-wrap">
                            <Button
                              size="xs"
                              color="blue"
                              onClick={() => openReservationsView(homelabNetwork)}
                              className="flex-1 min-w-[100px]"
                            >
                              Reservations
                            </Button>
                            <Button
                              size="xs"
                              color="gray"
                              onClick={() => openNetworkModal(homelabNetwork)}
                              className="flex-1 min-w-[80px]"
                            >
                              <HiPencil className="w-4 h-4" />
                            </Button>
                            <Button
                              size="xs"
                              color="failure"
                              onClick={() => {
                                setNetworkToDelete(homelabNetwork);
                                setDeleteNetworkModalOpen(true);
                              }}
                              className="flex-1 min-w-[80px]"
                            >
                              <HiTrash className="w-4 h-4" />
                            </Button>
                          </div>
                        </div>
                      </div>
                    </div>
                  </>
                );
              })()}
            </Card>

            {/* LAN Section */}
            <Card>
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-4">
                  <h2 className="text-2xl font-semibold text-gray-900 dark:text-white">LAN</h2>
                  {(() => {
                    const status = dhcpServiceStatuses['lan'];
                    const serviceKey = 'lan-';
                    const isControlling = controllingDhcpService?.startsWith(serviceKey);
                    return (
                      <div className="flex gap-2 items-center flex-wrap">
                        {status && (
                          <Badge color={status.is_active ? "success" : "gray"} size="sm">
                            {status.is_active ? "Running" : status.is_enabled ? "Stopped" : "Disabled"}
                          </Badge>
                        )}
                        <Button
                          size="xs"
                          color="success"
                          onClick={() => handleDhcpServiceControl('lan', 'start')}
                          disabled={isControlling || (status?.is_active ?? false)}
                          title="Start Service"
                        >
                          <HiPlay className="w-4 h-4" />
                        </Button>
                        <Button
                          size="xs"
                          color="failure"
                          onClick={() => handleDhcpServiceControl('lan', 'stop')}
                          disabled={isControlling || !(status?.is_active ?? false)}
                          title="Stop Service"
                        >
                          <HiStop className="w-4 h-4" />
                        </Button>
                        <Button
                          size="xs"
                          color="warning"
                          onClick={() => handleDhcpServiceControl('lan', 'reload')}
                          disabled={isControlling || !(status?.is_active ?? false)}
                          title="Reload Service"
                        >
                          <HiRefresh className="w-4 h-4" />
                        </Button>
                        <Button
                          size="xs"
                          color="purple"
                          onClick={() => handleDhcpServiceControl('lan', 'restart')}
                          disabled={isControlling}
                          title="Restart Service"
                        >
                          <HiRefresh className="w-4 h-4" />
                        </Button>
                      </div>
                    );
                  })()}
                </div>
              </div>
              
              {(() => {
                const lanNetwork = networks.find(n => n.network === 'lan');
                return !lanNetwork ? (
                  <Alert color="info" icon={HiInformationCircle}>
                    No DHCP network configured for LAN.
                  </Alert>
                ) : (
                  <>
                    {/* Desktop Table View */}
                    <div className="hidden min-[1000px]:block overflow-x-auto">
                      <Table>
                        <Table.Head>
                          <Table.HeadCell>IP Range</Table.HeadCell>
                          <Table.HeadCell>Lease Time</Table.HeadCell>
                          <Table.HeadCell>DNS Servers</Table.HeadCell>
                          <Table.HeadCell>Dynamic Domain</Table.HeadCell>
                          <Table.HeadCell>Status</Table.HeadCell>
                          <Table.HeadCell>Actions</Table.HeadCell>
                        </Table.Head>
                        <Table.Body className="divide-y">
                          <Table.Row key={lanNetwork.id} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                            <Table.Cell className="font-mono text-sm text-gray-900 dark:text-white">
                              {lanNetwork.start} - {lanNetwork.end}
                            </Table.Cell>
                            <Table.Cell className="text-gray-500 dark:text-gray-400">
                              {lanNetwork.lease_time}
                            </Table.Cell>
                            <Table.Cell className="text-gray-500 dark:text-gray-400">
                              {lanNetwork.dns_servers?.join(', ') || '-'}
                            </Table.Cell>
                            <Table.Cell className="text-gray-500 dark:text-gray-400">
                              {lanNetwork.dynamic_domain || '-'}
                            </Table.Cell>
                            <Table.Cell>
                              <Badge color={lanNetwork.enabled ? "success" : "gray"}>
                                {lanNetwork.enabled ? "Enabled" : "Disabled"}
                              </Badge>
                            </Table.Cell>
                            <Table.Cell>
                              <div className="flex gap-2 flex-wrap">
                                <Button
                                  size="xs"
                                  color="blue"
                                  onClick={() => openReservationsView(lanNetwork)}
                                >
                                  Reservations
                                </Button>
                                <Button
                                  size="xs"
                                  color="gray"
                                  onClick={() => openNetworkModal(lanNetwork)}
                                >
                                  <HiPencil className="w-4 h-4" />
                                </Button>
                                <Button
                                  size="xs"
                                  color="failure"
                                  onClick={() => {
                                    setNetworkToDelete(lanNetwork);
                                    setDeleteNetworkModalOpen(true);
                                  }}
                                >
                                  <HiTrash className="w-4 h-4" />
                                </Button>
                              </div>
                            </Table.Cell>
                          </Table.Row>
                        </Table.Body>
                      </Table>
                    </div>

                    {/* Mobile/Tablet Card View */}
                    <div className="min-[1000px]:hidden">
                      <div className="p-4 rounded-lg border bg-white border-gray-200 dark:bg-gray-800 dark:border-gray-700">
                        {/* Header Row */}
                        <div className="flex justify-between items-start mb-3">
                          <div className="flex-1">
                            <div className="font-mono text-sm text-gray-900 dark:text-white">
                              {lanNetwork.start} - {lanNetwork.end}
                            </div>
                          </div>
                          <Badge color={lanNetwork.enabled ? "success" : "gray"} size="sm">
                            {lanNetwork.enabled ? "Enabled" : "Disabled"}
                          </Badge>
                        </div>

                        {/* Details Grid */}
                        <div className="space-y-2 text-sm mb-4">
                          <div className="flex justify-between">
                            <span className="text-gray-500 dark:text-gray-400">Lease Time:</span>
                            <span className="text-gray-900 dark:text-gray-100">{lanNetwork.lease_time}</span>
                          </div>
                          
                          {lanNetwork.dns_servers && lanNetwork.dns_servers.length > 0 && (
                            <div className="flex justify-between">
                              <span className="text-gray-500 dark:text-gray-400">DNS Servers:</span>
                              <span className="text-gray-900 dark:text-gray-100 font-mono text-xs">{lanNetwork.dns_servers.join(', ')}</span>
                            </div>
                          )}
                          
                          {lanNetwork.dynamic_domain && (
                            <div className="flex justify-between">
                              <span className="text-gray-500 dark:text-gray-400">Dynamic Domain:</span>
                              <span className="text-gray-900 dark:text-gray-100">{lanNetwork.dynamic_domain}</span>
                            </div>
                          )}
                        </div>

                        {/* Action Buttons */}
                        <div className="pt-3 border-t border-gray-200 dark:border-gray-700">
                          <div className="flex gap-2 flex-wrap">
                            <Button
                              size="xs"
                              color="blue"
                              onClick={() => openReservationsView(lanNetwork)}
                              className="flex-1 min-w-[100px]"
                            >
                              Reservations
                            </Button>
                            <Button
                              size="xs"
                              color="gray"
                              onClick={() => openNetworkModal(lanNetwork)}
                              className="flex-1 min-w-[80px]"
                            >
                              <HiPencil className="w-4 h-4" />
                            </Button>
                            <Button
                              size="xs"
                              color="failure"
                              onClick={() => {
                                setNetworkToDelete(lanNetwork);
                                setDeleteNetworkModalOpen(true);
                              }}
                              className="flex-1 min-w-[80px]"
                            >
                              <HiTrash className="w-4 h-4" />
                            </Button>
                          </div>
                        </div>
                      </div>
                    </div>
                  </>
                );
              })()}
            </Card>

            {/* Network Modal */}
            <Modal show={networkModalOpen} onClose={closeNetworkModal} size="lg">
              <Modal.Header>
                {editingNetwork ? 'Edit DHCP Network' : 'Create DHCP Network'}
              </Modal.Header>
              <Modal.Body className="max-h-[70vh] overflow-y-auto">
                <div className="space-y-4">
                  {networkError && (
                    <Alert color="failure">
                      {networkError}
                    </Alert>
                  )}
                  {!editingNetwork && (
                    <div>
                      <Label htmlFor="networkNetwork" value="Network *" />
                      <Select
                        id="networkNetwork"
                        value={networkNetwork}
                        onChange={(e) => setNetworkNetwork(e.target.value as 'homelab' | 'lan')}
                        className="mt-1"
                        required
                      >
                        <option value="homelab">HOMELAB</option>
                        <option value="lan">LAN</option>
                      </Select>
                    </div>
                  )}
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="networkEnabled"
                      checked={networkEnabled}
                      onChange={(e) => setNetworkEnabled(e.target.checked)}
                    />
                    <Label htmlFor="networkEnabled" value="Enabled" />
                  </div>
                  <div>
                    <Label htmlFor="networkStart" value="IP Range Start *" />
                    <TextInput
                      id="networkStart"
                      value={networkStart}
                      onChange={(e) => setNetworkStart(e.target.value)}
                      placeholder="192.168.2.100"
                      required
                      className="mt-1 font-mono"
                    />
                  </div>
                  <div>
                    <Label htmlFor="networkEnd" value="IP Range End *" />
                    <TextInput
                      id="networkEnd"
                      value={networkEnd}
                      onChange={(e) => setNetworkEnd(e.target.value)}
                      placeholder="192.168.2.200"
                      required
                      className="mt-1 font-mono"
                    />
                  </div>
                  <div>
                    <Label htmlFor="networkLeaseTime" value="Lease Time *" />
                    <TextInput
                      id="networkLeaseTime"
                      value={networkLeaseTime}
                      onChange={(e) => setNetworkLeaseTime(e.target.value)}
                      placeholder="1h, 1d, or 86400"
                      required
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <Label htmlFor="networkDnsServers" value="DNS Servers (comma-separated)" />
                    <TextInput
                      id="networkDnsServers"
                      value={networkDnsServers}
                      onChange={(e) => setNetworkDnsServers(e.target.value)}
                      placeholder="192.168.2.1, 8.8.8.8"
                      className="mt-1 font-mono"
                    />
                  </div>
                  <div>
                    <Label htmlFor="networkDynamicDomain" value="Dynamic DNS Domain (optional)" />
                    <TextInput
                      id="networkDynamicDomain"
                      value={networkDynamicDomain}
                      onChange={(e) => setNetworkDynamicDomain(e.target.value)}
                      placeholder="dhcp.homelab.local"
                      className="mt-1"
                    />
                  </div>
                </div>
              </Modal.Body>
              <Modal.Footer>
                <Button
                  color="blue"
                  onClick={handleSaveNetwork}
                  disabled={saving || !networkStart.trim() || !networkEnd.trim()}
                >
                  {saving ? 'Saving...' : editingNetwork ? 'Update' : 'Create'}
                </Button>
                <Button color="gray" onClick={closeNetworkModal}>
                  Cancel
                </Button>
              </Modal.Footer>
            </Modal>

            {/* Reservations View Modal */}
            <Modal show={reservationsViewModalOpen} onClose={closeReservationsView} size="6xl">
              <Modal.Header>
                {selectedNetwork ? `${selectedNetwork.network.toUpperCase()} DHCP Reservations` : 'DHCP Reservations'}
              </Modal.Header>
              <Modal.Body className="max-h-[80vh] overflow-y-auto">
                <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2 mb-4">
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                    Static IP Reservations ({reservations.length})
                  </h3>
                  <Button
                    size="sm"
                    color="blue"
                    onClick={() => openReservationEditModal()}
                  >
                    <HiPlus className="w-4 h-4 mr-1" />
                    New Reservation
                  </Button>
                </div>
                
                {reservations.length === 0 ? (
                  <Alert color="info" icon={HiInformationCircle}>
                    No reservations configured for this network.
                  </Alert>
                ) : (
                  <>
                    {/* Desktop Table View */}
                    <div className="hidden min-[1000px]:block overflow-x-auto">
                      <Table>
                        <Table.Head>
                          <Table.HeadCell>Hostname</Table.HeadCell>
                          <Table.HeadCell>MAC Address</Table.HeadCell>
                          <Table.HeadCell>IP Address</Table.HeadCell>
                          <Table.HeadCell>Comment</Table.HeadCell>
                          <Table.HeadCell>Status</Table.HeadCell>
                          <Table.HeadCell>Actions</Table.HeadCell>
                        </Table.Head>
                        <Table.Body className="divide-y">
                          {reservations.map((reservation) => (
                            <Table.Row key={reservation.id} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                              <Table.Cell className="font-medium text-gray-900 dark:text-white">
                                {reservation.hostname}
                              </Table.Cell>
                              <Table.Cell className="font-mono text-sm text-gray-500 dark:text-gray-400">
                                {reservation.hw_address}
                              </Table.Cell>
                              <Table.Cell className="font-mono text-sm text-gray-900 dark:text-white">
                                {reservation.ip_address}
                              </Table.Cell>
                              <Table.Cell className="text-gray-500 dark:text-gray-400">
                                {reservation.comment || '-'}
                              </Table.Cell>
                              <Table.Cell>
                                <Badge color={reservation.enabled ? "success" : "gray"}>
                                  {reservation.enabled ? "Enabled" : "Disabled"}
                                </Badge>
                              </Table.Cell>
                              <Table.Cell>
                                <div className="flex gap-2 flex-wrap">
                                  <Button
                                    size="xs"
                                    color="gray"
                                    onClick={() => openReservationEditModal(reservation)}
                                  >
                                    <HiPencil className="w-4 h-4" />
                                  </Button>
                                  <Button
                                    size="xs"
                                    color="failure"
                                    onClick={() => {
                                      setReservationToDelete(reservation);
                                      setDeleteReservationModalOpen(true);
                                    }}
                                  >
                                    <HiTrash className="w-4 h-4" />
                                  </Button>
                                </div>
                              </Table.Cell>
                            </Table.Row>
                          ))}
                        </Table.Body>
                      </Table>
                    </div>

                    {/* Mobile/Tablet Card View */}
                    <div className="min-[1000px]:hidden space-y-3">
                      {reservations.map((reservation) => (
                        <div
                          key={reservation.id}
                          className="p-3 rounded-lg border bg-white border-gray-200 dark:bg-gray-800 dark:border-gray-700"
                        >
                          <div className="flex justify-between items-start mb-2">
                            <div className="flex-1">
                              <div className="font-semibold text-gray-900 dark:text-white mb-1">
                                {reservation.hostname}
                              </div>
                              <Badge color={reservation.enabled ? "success" : "gray"} size="sm">
                                {reservation.enabled ? "Enabled" : "Disabled"}
                              </Badge>
                            </div>
                          </div>
                          
                          <div className="space-y-1 text-sm mb-3">
                            <div className="flex justify-between">
                              <span className="text-gray-500 dark:text-gray-400">MAC Address:</span>
                              <span className="font-mono text-xs text-gray-900 dark:text-gray-100 break-all">{reservation.hw_address}</span>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-gray-500 dark:text-gray-400">IP Address:</span>
                              <span className="font-mono text-xs text-gray-900 dark:text-gray-100">{reservation.ip_address}</span>
                            </div>
                            {reservation.comment && (
                              <div className="flex justify-between">
                                <span className="text-gray-500 dark:text-gray-400">Comment:</span>
                                <span className="text-gray-900 dark:text-gray-100 text-xs">{reservation.comment}</span>
                              </div>
                            )}
                          </div>

                          <div className="pt-2 border-t border-gray-200 dark:border-gray-700 flex gap-2">
                            <Button
                              size="xs"
                              color="gray"
                              onClick={() => openReservationEditModal(reservation)}
                              className="flex-1"
                            >
                              <HiPencil className="w-4 h-4" />
                            </Button>
                            <Button
                              size="xs"
                              color="failure"
                              onClick={() => {
                                setReservationToDelete(reservation);
                                setDeleteReservationModalOpen(true);
                              }}
                              className="flex-1"
                            >
                              <HiTrash className="w-4 h-4" />
                            </Button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </Modal.Body>
              <Modal.Footer>
                <Button color="gray" onClick={closeReservationsView}>
                  Close
                </Button>
              </Modal.Footer>
            </Modal>

            {/* Reservation Edit Modal */}
            <Modal show={reservationEditModalOpen} onClose={closeReservationEditModal} size="lg">
              <Modal.Header>
                {editingReservation ? 'Edit Reservation' : 'Create Reservation'}
              </Modal.Header>
              <Modal.Body className="max-h-[70vh] overflow-y-auto">
                <div className="space-y-4">
                  {reservationError && (
                    <Alert color="failure">
                      {reservationError}
                    </Alert>
                  )}
                  <div>
                    <Label htmlFor="reservationHostname" value="Hostname *" />
                    <TextInput
                      id="reservationHostname"
                      value={reservationHostname}
                      onChange={(e) => setReservationHostname(e.target.value)}
                      placeholder="desktop"
                      required
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <Label htmlFor="reservationHwAddress" value="MAC Address *" />
                    <TextInput
                      id="reservationHwAddress"
                      value={reservationHwAddress}
                      onChange={(e) => setReservationHwAddress(e.target.value)}
                      placeholder="11:22:33:44:55:66"
                      required
                      className="mt-1 font-mono"
                    />
                  </div>
                  <div>
                    <Label htmlFor="reservationIpAddress" value="IP Address *" />
                    <TextInput
                      id="reservationIpAddress"
                      value={reservationIpAddress}
                      onChange={(e) => setReservationIpAddress(e.target.value)}
                      placeholder="192.168.2.50"
                      required
                      className="mt-1 font-mono"
                    />
                  </div>
                  <div>
                    <Label htmlFor="reservationComment" value="Comment (optional)" />
                    <TextInput
                      id="reservationComment"
                      value={reservationComment}
                      onChange={(e) => setReservationComment(e.target.value)}
                      className="mt-1"
                    />
                  </div>
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="reservationEnabled"
                      checked={reservationEnabled}
                      onChange={(e) => setReservationEnabled(e.target.checked)}
                    />
                    <Label htmlFor="reservationEnabled" value="Enabled" />
                  </div>
                </div>
              </Modal.Body>
              <Modal.Footer>
                <Button
                  color="blue"
                  onClick={handleSaveReservation}
                  disabled={saving || !reservationHostname.trim() || !reservationHwAddress.trim() || !reservationIpAddress.trim()}
                >
                  {saving ? 'Saving...' : editingReservation ? 'Update' : 'Create'}
                </Button>
                <Button color="gray" onClick={closeReservationEditModal}>
                  Cancel
                </Button>
              </Modal.Footer>
            </Modal>

            {/* Delete Network Confirmation */}
            <Modal show={deleteNetworkModalOpen} onClose={() => setDeleteNetworkModalOpen(false)} size="md">
              <Modal.Header>Delete DHCP Network</Modal.Header>
              <Modal.Body>
                <p className="text-gray-700 dark:text-gray-300">
                  Are you sure you want to delete the DHCP network for <strong>{networkToDelete?.network}</strong>?
                  This will also delete all reservations for this network.
                </p>
              </Modal.Body>
              <Modal.Footer>
                <Button color="failure" onClick={handleDeleteNetwork}>
                  Delete
                </Button>
                <Button color="gray" onClick={() => setDeleteNetworkModalOpen(false)}>
                  Cancel
                </Button>
              </Modal.Footer>
            </Modal>

            {/* Delete Reservation Confirmation */}
            <Modal show={deleteReservationModalOpen} onClose={() => setDeleteReservationModalOpen(false)} size="md">
              <Modal.Header>Delete Reservation</Modal.Header>
              <Modal.Body>
                <p className="text-gray-700 dark:text-gray-300">
                  Are you sure you want to delete the reservation for <strong>{reservationToDelete?.hostname}</strong>?
                </p>
              </Modal.Body>
              <Modal.Footer>
                <Button color="failure" onClick={handleDeleteReservation}>
                  Delete
                </Button>
                <Button color="gray" onClick={() => setDeleteReservationModalOpen(false)}>
                  Cancel
                </Button>
              </Modal.Footer>
            </Modal>
          </div>
        </main>
      </div>
    </div>
  );
}

