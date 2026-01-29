/**
 * Network Devices page - Shows all devices (DHCP and static)
 */
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Table, Badge, TextInput, Select, Button, Tooltip, Modal } from 'flowbite-react';
import { HiSearch, HiPencil, HiClock } from 'react-icons/hi';
import { Sidebar } from '../components/layout/Sidebar';
import { Navbar } from '../components/layout/Navbar';
import { useMetrics } from '../hooks/useMetrics';
import { apiClient } from '../api/client';
import type { PortScanResult, PortScanStatus } from '../types/devices';

interface NetworkDevice {
  network: string;
  ip_address: string;
  mac_address: string;
  hostname: string;
  nickname?: string | null;
  favorite?: boolean;
  vendor: string | null;
  is_dhcp: boolean;
  is_static: boolean;
  is_online: boolean;
  last_seen: string;
}

export function Clients() {
  const token = localStorage.getItem('access_token');
  const username = localStorage.getItem('username') || 'Unknown';
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [filterStatus, setFilterStatus] = useState('all'); // all, online, offline
  const [filterType, setFilterType] = useState('all'); // all, dhcp, static
  const [activeTab, setActiveTab] = useState<'all' | 'homelab' | 'lan'>('all'); // Tab selection
  const [devices, setDevices] = useState<NetworkDevice[]>([]);
  const [blockedV4, setBlockedV4] = useState<string[]>([]);
  const [blockedMacs, setBlockedMacs] = useState<string[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sortColumn, setSortColumn] = useState<string>('ip'); // Default to IP
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc');
  const [portScanModalOpen, setPortScanModalOpen] = useState(false);
  const [selectedDevicePorts, setSelectedDevicePorts] = useState<PortScanResult | null>(null);
  const [selectedDeviceMac, setSelectedDeviceMac] = useState<string | null>(null);
  const [portScanStatuses, setPortScanStatuses] = useState<Map<string, PortScanStatus>>(new Map());
  const [loadingPortScan, setLoadingPortScan] = useState(false);
  
  const { connectionStatus } = useMetrics(token);
  
  const handleLogout = async () => {
    await apiClient.logout();
    navigate('/login');
  };

  const fetchPortScan = async (macAddress: string) => {
    if (!token) return;
    try {
      setLoadingPortScan(true);
      setSelectedDeviceMac(macAddress);
      const result = await apiClient.getDevicePortScan(macAddress);
      setSelectedDevicePorts(result);
      setPortScanStatuses(prev => new Map(prev).set(macAddress.toLowerCase(), result.scan_status));
      setPortScanModalOpen(true);
    } catch (error: any) {
      if (error.response?.status === 404) {
        // No scan exists yet
        setSelectedDeviceMac(macAddress);
        setSelectedDevicePorts(null);
        setPortScanModalOpen(true);
      } else {
        console.error('Failed to fetch port scan:', error);
        alert('Failed to load port scan results');
      }
    } finally {
      setLoadingPortScan(false);
    }
  };

  const triggerPortScan = async (macAddress: string) => {
    if (!token) return;
    try {
      setLoadingPortScan(true);
      const response = await apiClient.triggerDevicePortScan(macAddress);
      if (response.status === 'queued' || response.status === 'in_progress') {
        setPortScanStatuses(prev => new Map(prev).set(macAddress.toLowerCase(), 'pending'));
        // Poll for results
        setTimeout(() => {
          fetchPortScan(macAddress);
        }, 2000);
      } else {
        alert(response.message || 'Failed to trigger scan');
      }
    } catch (error) {
      console.error('Failed to trigger port scan:', error);
      alert('Failed to trigger port scan');
    } finally {
      setLoadingPortScan(false);
    }
  };

  const getPortScanButton = (device: NetworkDevice) => {
    const macLower = device.mac_address.toLowerCase();
    const status = portScanStatuses.get(macLower);
    const isPendingOrInProgress = status === 'pending' || status === 'in_progress';
    const isCompleted = status === 'completed';
    const isFailed = status === 'failed';
    
    if (!device.is_online) {
      return (
        <Tooltip content="Device is offline">
          <Button size="xs" color="gray" disabled>
            Ports
          </Button>
        </Tooltip>
      );
    }

    if (isPendingOrInProgress) {
      return (
        <Tooltip content="Port scan in progress">
          <Button size="xs" color="gray" disabled>
            <HiClock className="w-3 h-3 mr-1" />
            Scanning...
          </Button>
        </Tooltip>
      );
    }

    if (isFailed) {
      return (
        <Tooltip content="Last scan failed - click to retry">
          <Button 
            size="xs" 
            color="failure" 
            onClick={() => triggerPortScan(device.mac_address)}
          >
            Ports (Failed)
          </Button>
        </Tooltip>
      );
    }

    return (
      <Tooltip content={isCompleted ? "View port scan results" : "Scan ports"}>
        <Button 
          size="xs" 
          color="gray" 
          onClick={() => {
            if (isCompleted) {
              fetchPortScan(device.mac_address);
            } else {
              triggerPortScan(device.mac_address);
            }
          }}
        >
          Ports{isCompleted && selectedDevicePorts ? ` (${selectedDevicePorts.ports.length})` : ''}
        </Button>
      </Tooltip>
    );
  };

  // Fetch devices every 10 seconds
  useEffect(() => {
    const fetchDevices = async () => {
      if (!token) return;
      
      try {
        const response = await fetch('/api/devices/all', {
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        });
        
        if (response.ok) {
          const data = await response.json();
          setDevices(data);
          
          // Fetch port scan statuses for online devices
          const onlineDevices = data.filter((d: NetworkDevice) => d.is_online);
          const statusMap = new Map<string, PortScanStatus>();
          
          // Fetch statuses in parallel (limit to 10 at a time to avoid overwhelming)
          const batchSize = 10;
          for (let i = 0; i < onlineDevices.length; i += batchSize) {
            const batch = onlineDevices.slice(i, i + batchSize);
            await Promise.allSettled(
              batch.map(async (device: NetworkDevice) => {
                try {
                  const scanResult = await apiClient.getDevicePortScan(device.mac_address);
                  statusMap.set(device.mac_address.toLowerCase(), scanResult.scan_status);
                } catch (error: any) {
                  // 404 means no scan exists, which is fine
                  if (error.response?.status !== 404) {
                    console.debug(`Failed to fetch port scan for ${device.mac_address}:`, error);
                  }
                }
              })
            );
          }
          
          setPortScanStatuses(statusMap);
        }
      } catch (error) {
        console.error('Failed to fetch devices:', error);
      }
    };
    
    fetchDevices();
    const interval = setInterval(fetchDevices, 10000);
    return () => clearInterval(interval);
  }, [token]);

  // Fetch blocked list every 10 seconds
  useEffect(() => {
    const fetchBlocked = async () => {
      if (!token) return;
      try {
        const response = await fetch('/api/devices/blocked', {
          headers: { 'Authorization': `Bearer ${token}` },
        });
        if (response.ok) {
          const data = await response.json();
          setBlockedV4(data.ipv4 || []);
          setBlockedMacs((data.macs || []).map((m: string) => m.toLowerCase()));
        }
      } catch (e) {
        // ignore
      }
    };
    fetchBlocked();
    const interval = setInterval(fetchBlocked, 10000);
    return () => clearInterval(interval);
  }, [token]);

  const isDeviceBlocked = (device: NetworkDevice) => {
    if (device.mac_address && blockedMacs.includes(device.mac_address.toLowerCase())) return true;
    return (device.ip_address && blockedV4.includes(device.ip_address));
  };

  const toggleFavorite = async (device: NetworkDevice) => {
    if (!token) return;
    const newFav = !device.favorite;
    // optimistic update
    setDevices(prev => prev.map(d => d.mac_address === device.mac_address ? { ...d, favorite: newFav } : d));
    try {
      await fetch('/api/devices/override', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ mac_address: device.mac_address, favorite: newFav }),
      });
      // Re-fetch to apply backend sorting (favorites first)
      const resp = await fetch('/api/devices/all', { headers: { 'Authorization': `Bearer ${token}` } });
      if (resp.ok) setDevices(await resp.json());
    } catch {
      // revert
      setDevices(prev => prev.map(d => d.mac_address === device.mac_address ? { ...d, favorite: !newFav } : d));
    }
  };

  const editNickname = async (device: NetworkDevice) => {
    if (!token) return;
    const currentName = device.nickname || '';
    const value = window.prompt('Set nickname for this device:', currentName);
    if (value === null) return;
    // optimistic
    setDevices(prev => prev.map(d => d.mac_address === device.mac_address ? { ...d, nickname: value } : d));
    try {
      await fetch('/api/devices/override', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ mac_address: device.mac_address, nickname: value }),
      });
      const resp = await fetch('/api/devices/all', { headers: { 'Authorization': `Bearer ${token}` } });
      if (resp.ok) setDevices(await resp.json());
    } catch {
      // ignore
    }
  };

  const handleBlockToggle = async (device: NetworkDevice) => {
    if (!token) return;
    const blocked = isDeviceBlocked(device);
    const url = blocked ? '/api/devices/unblock' : '/api/devices/block';
    const body: any = { mac_address: device.mac_address };
    if (device.ip_address && device.ip_address.includes('.')) body.ip_address = device.ip_address;
    // Optimistic UI
    if (blocked) {
      // Unblocking: remove from blocked lists
      if (device.ip_address) {
        setBlockedV4(prev => prev.filter(ip => ip !== device.ip_address));
      }
      setBlockedMacs(prev => prev.filter(m => m !== device.mac_address.toLowerCase()));
    } else {
      // Blocking: add to blocked lists
      // Always add MAC address (devices can be blocked by MAC alone)
      setBlockedMacs(prev => Array.from(new Set([...prev, device.mac_address.toLowerCase()])));
      // Only add IP if it exists
      if (body.ip_address) {
        setBlockedV4(prev => Array.from(new Set([...prev, body.ip_address])));
      }
    }
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
      });
      
      if (response.ok) {
        // Small delay to ensure backend has processed the change
        await new Promise(resolve => setTimeout(resolve, 100));
        
        // Refetch blocked list immediately after successful operation
        // This ensures the UI state matches the actual backend state
        const blockedResponse = await fetch('/api/devices/blocked', {
          headers: { 'Authorization': `Bearer ${token}` },
        });
        if (blockedResponse.ok) {
          const blockedData = await blockedResponse.json();
          setBlockedV4(blockedData.ipv4 || []);
          setBlockedMacs((blockedData.macs || []).map((m: string) => m.toLowerCase()));
        } else {
          // If refetch fails, keep optimistic update (better than reverting)
          console.warn('Failed to refetch blocked list after block/unblock operation');
        }
      } else {
        // API call failed, revert optimistic update
        if (blocked) {
          // Was unblocking, revert by re-adding to blocked lists
          if (device.ip_address) {
            setBlockedV4(prev => Array.from(new Set([...prev, device.ip_address])));
          }
          setBlockedMacs(prev => Array.from(new Set([...prev, device.mac_address.toLowerCase()])));
        } else {
          // Was blocking, revert by removing from blocked lists
          if (device.ip_address) {
            setBlockedV4(prev => prev.filter(ip => ip !== device.ip_address));
          }
          setBlockedMacs(prev => prev.filter(m => m !== device.mac_address.toLowerCase()));
        }
      }
    } catch (e) {
      // Network error, revert optimistic update
      if (blocked) {
        // Was unblocking, revert by re-adding to blocked lists
        if (device.ip_address) {
          setBlockedV4(prev => Array.from(new Set([...prev, device.ip_address])));
        }
        setBlockedMacs(prev => Array.from(new Set([...prev, device.mac_address.toLowerCase()])));
      } else {
        // Was blocking, revert by removing from blocked lists
        if (device.ip_address) {
          setBlockedV4(prev => prev.filter(ip => ip !== device.ip_address));
        }
        setBlockedMacs(prev => prev.filter(m => m !== device.mac_address.toLowerCase()));
      }
    }
  };

  const filteredDevices = devices.filter((device) => {
    // Search filter
    const matchesSearch = !search || (
      device.hostname?.toLowerCase().includes(search.toLowerCase()) ||
      device.ip_address.includes(search) ||
      device.mac_address.includes(search) ||
      device.vendor?.toLowerCase().includes(search.toLowerCase())
    );
    
    // Status filter
    const matchesStatus = filterStatus === 'all' || 
      (filterStatus === 'online' && device.is_online) ||
      (filterStatus === 'offline' && !device.is_online);
    
    // Type filter
    const matchesType = filterType === 'all' ||
      (filterType === 'dhcp' && device.is_dhcp) ||
      (filterType === 'static' && !device.is_dhcp);
    
    // Network filter (based on active tab)
    const matchesNetwork = activeTab === 'all' || device.network === activeTab;
    
    return matchesSearch && matchesStatus && matchesType && matchesNetwork;
  });

  // Calculate counts based on active tab
  const tabDevices = activeTab === 'all' 
    ? devices 
    : devices.filter(d => d.network === activeTab);
  
  const onlineCount = tabDevices.filter(d => d.is_online).length;
  const offlineCount = tabDevices.filter(d => !d.is_online).length;
  const totalCount = tabDevices.length;

  // Helper function to convert IP to sortable string (pad octets for proper numeric sorting)
  const getSortableIP = (ip: string): string => {
    return ip.split('.').map(octet => octet.padStart(3, '0')).join('.');
  };

  // Handle column sorting - click toggles between asc/desc
  const handleSort = (column: string) => {
    if (sortColumn === column) {
      // Toggle direction
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      // New column - always start with ascending
      setSortColumn(column);
      setSortDirection('asc');
    }
  };

  // Get sort indicator for a column
  const getSortIndicator = (column: string) => {
    if (sortColumn !== column) return null;
    return sortDirection === 'asc' ? ' ↑' : ' ↓';
  };

  // Get display name for device (nickname or hostname)
  const getDisplayName = (device: NetworkDevice): string => {
    return device.nickname || device.hostname || 'Unknown';
  };

  // Sort devices based on selected column
  const sortedDevices = [...filteredDevices].sort((a, b) => {
    let comparison = 0;
    
    switch (sortColumn) {
      case 'ip':
        const ipA = getSortableIP(a.ip_address);
        const ipB = getSortableIP(b.ip_address);
        comparison = ipA.localeCompare(ipB);
        break;
      case 'device':
        comparison = getDisplayName(a).toLowerCase().localeCompare(getDisplayName(b).toLowerCase());
        break;
      case 'mac':
        comparison = a.mac_address.localeCompare(b.mac_address);
        break;
      case 'vendor':
        // Nulls last
        const vendorA = a.vendor || '\uffff';
        const vendorB = b.vendor || '\uffff';
        comparison = vendorA.toLowerCase().localeCompare(vendorB.toLowerCase());
        break;
      case 'network':
        comparison = a.network.localeCompare(b.network);
        break;
      case 'status':
        // Online first when ascending
        comparison = (b.is_online ? 1 : 0) - (a.is_online ? 1 : 0);
        break;
      case 'type':
        // DHCP first when ascending
        comparison = (b.is_dhcp ? 1 : 0) - (a.is_dhcp ? 1 : 0);
        break;
      case 'lastSeen':
        const dateA = new Date(a.last_seen).getTime();
        const dateB = new Date(b.last_seen).getTime();
        comparison = dateA - dateB;
        break;
      default:
        // Default: sort by IP
        comparison = getSortableIP(a.ip_address).localeCompare(getSortableIP(b.ip_address));
    }

    return sortDirection === 'asc' ? comparison : -comparison;
  });

  // Helper function to format last seen date
  const formatLastSeen = (dateString: string): string => {
    const date = new Date(dateString);
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const itemDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    
    if (itemDate.getTime() === today.getTime()) {
      // Today - show time only
      return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
    } else {
      // Not today - show MM/DD/YY
      const month = (date.getMonth() + 1).toString().padStart(2, '0');
      const day = date.getDate().toString().padStart(2, '0');
      const year = date.getFullYear().toString().slice(-2);
      return `${month}/${day}/${year}`;
    }
  };

  // Helper function to truncate text with tooltip
  const TruncatedText = ({ text, maxLength = 20 }: { text: string; maxLength?: number }) => {
    if (text.length <= maxLength) {
      return <span>{text}</span>;
    }
    return (
      <Tooltip content={text} placement="top">
        <span className="cursor-help truncate block max-w-[200px]">{text}</span>
      </Tooltip>
    );
  };

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
        
        <main className="flex-1 overflow-y-auto p-4 md:p-6 bg-gray-50 dark:bg-gray-900">
          <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-4 md:mb-6 gap-3">
            <div className="flex flex-col gap-1">
              <h1 className="text-2xl md:text-3xl font-bold">Devices</h1>
              <p className="text-xs md:text-sm text-gray-500">
                Showing {sortedDevices.length} of {totalCount} devices
                {activeTab !== 'all' && ` (${activeTab.toUpperCase()} network)`}
                <span className="hidden sm:inline">{' • '}Auto-refreshing every 10 seconds</span>
              </p>
            </div>
            <div className="flex gap-2 md:gap-4">
              <Badge color="success" size="sm" className="md:text-base">{onlineCount} Online</Badge>
              <Badge color="gray" size="sm" className="md:text-base">{offlineCount} Offline</Badge>
              <Badge color="info" size="sm" className="md:text-base">{totalCount} Total</Badge>
            </div>
          </div>
          
          <Card>
            {/* Sticky section for tabs and filters on desktop */}
            <div className="min-[1000px]:sticky min-[1000px]:top-0 min-[1000px]:z-20 min-[1000px]:bg-white min-[1000px]:dark:bg-gray-800">
              {/* Network Tabs */}
              <div className="mb-4 border-b border-gray-200 dark:border-gray-700">
              <div className="flex space-x-1" role="tablist">
                <button
                  role="tab"
                  aria-selected={activeTab === 'all'}
                  onClick={() => setActiveTab('all')}
                  className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === 'all'
                      ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
                  }`}
                >
                  All Networks
                </button>
                <button
                  role="tab"
                  aria-selected={activeTab === 'homelab'}
                  onClick={() => setActiveTab('homelab')}
                  className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === 'homelab'
                      ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
                  }`}
                >
                  HOMELAB
                </button>
                <button
                  role="tab"
                  aria-selected={activeTab === 'lan'}
                  onClick={() => setActiveTab('lan')}
                  className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === 'lan'
                      ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
                  }`}
                >
                  LAN
                </button>
              </div>
            </div>

            {/* Filters - shared across all tabs */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
              <div>
                <TextInput
                  icon={HiSearch}
                  placeholder="Search..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              
              <div>
                <Select
                  value={filterStatus}
                  onChange={(e) => setFilterStatus(e.target.value)}
                >
                  <option value="all">All Status</option>
                  <option value="online">Online Only</option>
                  <option value="offline">Offline Only</option>
                </Select>
              </div>
              
              <div>
                <Select
                  value={filterType}
                  onChange={(e) => setFilterType(e.target.value)}
                >
                  <option value="all">All Types</option>
                  <option value="dhcp">DHCP Only</option>
                  <option value="static">Static Only</option>
                </Select>
              </div>
            </div>
            </div>
            {/* End sticky section */}

            {/* Legend for color indicators - only show below 1650px */}
            <div className="xl-custom:hidden mb-4 flex flex-wrap gap-4 text-xs text-gray-600 dark:text-gray-400">
              <div className="flex items-center gap-2">
                <span className="font-semibold">Network:</span>
                <div className="flex items-center gap-1">
                  <div className="w-3 h-3 rounded-full bg-blue-500"></div>
                  <span>HOMELAB</span>
                </div>
                <div className="flex items-center gap-1">
                  <div className="w-3 h-3 rounded-full bg-purple-500"></div>
                  <span>LAN</span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="font-semibold">Type:</span>
                <div className="flex items-center gap-1">
                  <div className="w-3 h-3 rounded-full bg-gray-500"></div>
                  <span>Static</span>
                </div>
                <div className="flex items-center gap-1">
                  <div className="w-3 h-3 rounded-full bg-yellow-500"></div>
                  <span>DHCP</span>
                </div>
              </div>
            </div>

            {/* Desktop Table View */}
            <div className="hidden min-[1000px]:block overflow-x-auto">
              <Table>
                <Table.Head>
                  <Table.HeadCell 
                    className="cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700"
                    onClick={() => handleSort('ip')}
                  >
                    IP Address{getSortIndicator('ip')}
                  </Table.HeadCell>
                  <Table.HeadCell 
                    className="cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700"
                    onClick={() => handleSort('device')}
                  >
                    Device{getSortIndicator('device')}
                  </Table.HeadCell>
                  <Table.HeadCell 
                    className="hidden lg:table-cell cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700"
                    onClick={() => handleSort('mac')}
                  >
                    MAC Address{getSortIndicator('mac')}
                  </Table.HeadCell>
                  <Table.HeadCell 
                    className="hidden xl:table-cell cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700"
                    onClick={() => handleSort('vendor')}
                  >
                    Vendor{getSortIndicator('vendor')}
                  </Table.HeadCell>
                  <Table.HeadCell 
                    className="w-12 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700"
                    onClick={() => handleSort('network')}
                  >
                    Network{getSortIndicator('network')}
                  </Table.HeadCell>
                  <Table.HeadCell 
                    className="w-12 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700"
                    onClick={() => handleSort('status')}
                  >
                    Status{getSortIndicator('status')}
                  </Table.HeadCell>
                  <Table.HeadCell 
                    className="w-12 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700"
                    onClick={() => handleSort('type')}
                  >
                    Type{getSortIndicator('type')}
                  </Table.HeadCell>
                  <Table.HeadCell 
                    className="w-24 cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700"
                    onClick={() => handleSort('lastSeen')}
                  >
                    Last Seen{getSortIndicator('lastSeen')}
                  </Table.HeadCell>
                  <Table.HeadCell>Actions</Table.HeadCell>
                </Table.Head>
                <Table.Body className="divide-y">
                  {sortedDevices.map((device) => (
                    <Table.Row key={device.mac_address} className={!device.is_online ? 'opacity-50' : ''}>
                      <Table.Cell className="font-mono text-sm">{device.ip_address}</Table.Cell>
                      <Table.Cell className="font-medium max-w-[200px]">
                        <div className="flex items-center gap-2">
                          <button
                            className="text-yellow-500 hover:text-yellow-400 flex-shrink-0"
                            title={device.favorite ? 'Unfavorite' : 'Favorite'}
                            onClick={() => toggleFavorite(device)}
                          >
                            {device.favorite ? '★' : '☆'}
                          </button>
                          <button
                            className="text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 flex-shrink-0"
                            title="Edit nickname"
                            onClick={() => editNickname(device)}
                          >
                            <HiPencil className="w-4 h-4" />
                          </button>
                          <TruncatedText text={device.nickname || device.hostname || 'Unknown'} maxLength={20} />
                        </div>
                      </Table.Cell>
                      <Table.Cell className="font-mono text-sm hidden lg:table-cell">
                        {device.mac_address}
                      </Table.Cell>
                      <Table.Cell className="text-sm text-gray-600 hidden xl:table-cell">
                        {device.vendor || '—'}
                      </Table.Cell>
                      <Table.Cell>
                        {/* Show text above 1650px, circle below */}
                        <div className="hidden xl-custom:block">
                          <Badge color={device.network === 'homelab' ? 'info' : 'purple'} size="sm">
                          {device.network.toUpperCase()}
                        </Badge>
                        </div>
                        <div className="xl-custom:hidden">
                          <Tooltip content={device.network.toUpperCase()} placement="top">
                            <div className={`w-3 h-3 rounded-full ${device.network === 'homelab' ? 'bg-blue-500' : 'bg-purple-500'}`}></div>
                          </Tooltip>
                        </div>
                      </Table.Cell>
                      <Table.Cell>
                        {/* Show text above 1650px, circle below */}
                        <div className="hidden xl-custom:block">
                        <Badge color={device.is_online ? 'success' : 'gray'} size="sm">
                            {device.is_online ? 'ONLINE' : 'OFFLINE'}
                        </Badge>
                        </div>
                        <div className="xl-custom:hidden">
                          <Tooltip content={device.is_online ? 'Online' : 'Offline'} placement="top">
                            <div className={`w-3 h-3 rounded-full ${device.is_online ? 'bg-green-500' : 'bg-gray-400'}`}></div>
                          </Tooltip>
                        </div>
                      </Table.Cell>
                      <Table.Cell>
                        {/* Show text above 1650px, circle below */}
                        <div className="hidden xl-custom:block">
                          <Badge color={device.is_dhcp ? 'warning' : 'gray'} size="sm">
                            {device.is_dhcp ? 'DHCP' : 'Static'}
                        </Badge>
                        </div>
                        <div className="xl-custom:hidden">
                          <Tooltip 
                            content={device.is_dhcp ? 'DHCP' : 'Static'} 
                            placement="top"
                          >
                            <div className={`w-3 h-3 rounded-full ${
                              device.is_dhcp ? 'bg-yellow-500' : 'bg-gray-500'
                            }`}></div>
                          </Tooltip>
                        </div>
                      </Table.Cell>
                      <Table.Cell className="text-sm whitespace-nowrap">
                        {formatLastSeen(device.last_seen)}
                      </Table.Cell>
                      <Table.Cell>
                        <div className="flex gap-1 flex-wrap">
                          <Button
                            size="xs"
                            color="gray"
                            onClick={() => navigate(`/devices/${device.ip_address}`)}
                          >
                            Details
                          </Button>
                        <Button
                          size="xs"
                          color={isDeviceBlocked(device) ? 'success' : 'failure'}
                          onClick={() => handleBlockToggle(device)}
                        >
                          {isDeviceBlocked(device) ? 'Enable' : 'Disable'}
                        </Button>
                        {getPortScanButton(device)}
                        </div>
                      </Table.Cell>
                    </Table.Row>
                  ))}
                </Table.Body>
              </Table>
            </div>

            {/* Mobile Card View */}
            <div className="min-[1000px]:hidden space-y-3">
              {sortedDevices.map((device) => (
                <div
                  key={device.mac_address}
                  className={`p-4 rounded-lg border ${
                    device.is_online 
                      ? 'bg-white border-gray-200 dark:bg-gray-800 dark:border-gray-700' 
                      : 'bg-gray-50 border-gray-200 dark:bg-gray-900 dark:border-gray-700 opacity-60'
                  }`}
                >
                  {/* Header Row */}
                  <div className="flex justify-between items-start mb-2">
                    <div className="flex-1">
                      <div className="font-semibold text-lg mb-1">
                        {device.hostname || 'Unknown'}
                      </div>
                      <div className="text-sm text-gray-600 dark:text-gray-400">
                        {device.ip_address}
                      </div>
                    </div>
                    <Badge color={device.is_online ? 'success' : 'gray'} size="sm">
                      {device.is_online ? '● Online' : '○ Offline'}
                    </Badge>
                  </div>

                  {/* Details Grid */}
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-gray-500">MAC:</span>
                      <span className="font-mono">{device.mac_address}</span>
                    </div>
                    
                    {device.vendor && (
                      <div className="flex justify-between">
                        <span className="text-gray-500">Vendor:</span>
                        <span className="text-gray-900 dark:text-gray-100">{device.vendor}</span>
                      </div>
                    )}
                    
                    <div className="flex justify-between items-center">
                      <span className="text-gray-500">Network:</span>
                      <Badge color={device.network === 'homelab' ? 'info' : 'purple'} size="sm">
                        {device.network.toUpperCase()}
                      </Badge>
                    </div>
                    
                    <div className="flex justify-between items-center">
                      <span className="text-gray-500">Nickname:</span>
                      <span className="text-gray-900 dark:text-gray-100">{device.nickname || '—'}</span>
                    </div>
                    
                    <div className="flex justify-between items-center">
                      <span className="text-gray-500">Type:</span>
                      <Badge color={device.is_dhcp ? (device.is_static ? 'success' : 'warning') : 'gray'} size="sm">
                        {device.is_static ? 'Static DHCP' : (device.is_dhcp ? 'Dynamic' : 'Static IP')}
                      </Badge>
                    </div>
                    
                    <div className="flex justify-between text-xs text-gray-500 pt-1 border-t border-gray-200 dark:border-gray-700">
                      <span>Last seen:</span>
                      <span>{new Date(device.last_seen).toLocaleString()}</span>
                    </div>
                    <div className="pt-3">
                      <div className="flex gap-2 mb-2">
                        <Button
                          size="xs"
                          color="gray"
                          onClick={() => navigate(`/devices/${device.ip_address}`)}
                          className="flex-1"
                        >
                          Details
                        </Button>
                      <Button
                        size="xs"
                        color={isDeviceBlocked(device) ? 'success' : 'failure'}
                        onClick={() => handleBlockToggle(device)}
                          className="flex-1"
                      >
                        {isDeviceBlocked(device) ? 'Enable' : 'Disable'}
                      </Button>
                      </div>
                      <div className="mt-2 flex gap-2">
                        <Button size="xs" color="light" className="flex-1" onClick={() => editNickname(device)}>Edit Nickname</Button>
                        <Button size="xs" color={device.favorite ? 'warning' : 'light'} onClick={() => toggleFavorite(device)}>
                          {device.favorite ? '★ Favorite' : '☆ Favorite'}
                        </Button>
                      </div>
                      <div className="mt-2">
                        {getPortScanButton(device)}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {sortedDevices.length === 0 && (
              <div className="text-center py-8 text-gray-500">
                No devices found matching your filters
              </div>
            )}
            
          </Card>

          {/* Port Scan Modal */}
          <Modal show={portScanModalOpen} onClose={() => {
            setPortScanModalOpen(false);
            setSelectedDevicePorts(null);
            setSelectedDeviceMac(null);
          }} size="xl">
            <Modal.Header>
              Port Scan Results
              {selectedDevicePorts ? (
                <span className="ml-2 text-sm text-gray-500">
                  {selectedDevicePorts.mac_address} ({selectedDevicePorts.ip_address})
                </span>
              ) : selectedDeviceMac ? (
                <span className="ml-2 text-sm text-gray-500">
                  {selectedDeviceMac}
                </span>
              ) : null}
            </Modal.Header>
            <Modal.Body>
              {loadingPortScan ? (
                <div className="text-center py-8">
                  <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 dark:border-gray-100"></div>
                  <p className="mt-2 text-gray-600 dark:text-gray-400">Loading port scan results...</p>
                </div>
              ) : selectedDevicePorts ? (
                <div>
                  <div className="mb-4 flex justify-between items-center">
                    <div>
                      <Badge color={
                        selectedDevicePorts.scan_status === 'completed' ? 'success' :
                        selectedDevicePorts.scan_status === 'failed' ? 'failure' :
                        selectedDevicePorts.scan_status === 'in_progress' ? 'warning' : 'gray'
                      }>
                        {selectedDevicePorts.scan_status.toUpperCase()}
                      </Badge>
                      <span className="ml-2 text-sm text-gray-600 dark:text-gray-400">
                        Started: {new Date(selectedDevicePorts.scan_started_at).toLocaleString()}
                      </span>
                      {selectedDevicePorts.scan_completed_at && (
                        <span className="ml-2 text-sm text-gray-600 dark:text-gray-400">
                          Completed: {new Date(selectedDevicePorts.scan_completed_at).toLocaleString()}
                        </span>
                      )}
                    </div>
                    <Button
                      size="xs"
                      color="gray"
                      onClick={() => {
                        if (selectedDevicePorts) {
                          triggerPortScan(selectedDevicePorts.mac_address);
                        }
                      }}
                    >
                      Refresh Scan
                    </Button>
                  </div>
                  
                  {selectedDevicePorts.error_message && (
                    <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded">
                      <p className="text-sm text-red-800 dark:text-red-200">
                        <strong>Error:</strong> {selectedDevicePorts.error_message}
                      </p>
                    </div>
                  )}

                  {selectedDevicePorts.ports.length > 0 ? (
                    <div className="overflow-x-auto">
                      <Table>
                        <Table.Head>
                          <Table.HeadCell>Port</Table.HeadCell>
                          <Table.HeadCell>Protocol</Table.HeadCell>
                          <Table.HeadCell>State</Table.HeadCell>
                          <Table.HeadCell>Service</Table.HeadCell>
                          <Table.HeadCell>Version</Table.HeadCell>
                          <Table.HeadCell>Product</Table.HeadCell>
                        </Table.Head>
                        <Table.Body>
                          {selectedDevicePorts.ports.map((port, idx) => (
                            <Table.Row key={idx}>
                              <Table.Cell className="font-mono">{port.port}</Table.Cell>
                              <Table.Cell className="uppercase">{port.protocol}</Table.Cell>
                              <Table.Cell>
                                <Badge color={
                                  port.state === 'open' ? 'success' :
                                  port.state === 'closed' ? 'gray' :
                                  port.state === 'filtered' ? 'warning' : 'gray'
                                } size="sm">
                                  {port.state}
                                </Badge>
                              </Table.Cell>
                              <Table.Cell>{port.service_name || '—'}</Table.Cell>
                              <Table.Cell>{port.service_version || '—'}</Table.Cell>
                              <Table.Cell>{port.service_product || '—'}</Table.Cell>
                            </Table.Row>
                          ))}
                        </Table.Body>
                      </Table>
                    </div>
                  ) : selectedDevicePorts.scan_status === 'completed' ? (
                    <p className="text-center py-4 text-gray-600 dark:text-gray-400">
                      No open ports found
                    </p>
                  ) : (
                    <p className="text-center py-4 text-gray-600 dark:text-gray-400">
                      Scan in progress or no results yet
                    </p>
                  )}
                </div>
              ) : (
                <div className="text-center py-8">
                  <p className="text-gray-600 dark:text-gray-400 mb-4">
                    No port scan results available for this device.
                  </p>
                  {selectedDeviceMac && (
                    <Button
                      color="gray"
                      onClick={async () => {
                        const device = devices.find(d => 
                          d.mac_address.toLowerCase() === selectedDeviceMac.toLowerCase() && d.is_online
                        );
                        if (device) {
                          await triggerPortScan(device.mac_address);
                        } else {
                          setPortScanModalOpen(false);
                        }
                      }}
                    >
                      Start Port Scan
                    </Button>
                  )}
                </div>
              )}
            </Modal.Body>
          </Modal>
        </main>
      </div>
    </div>
  );
}

