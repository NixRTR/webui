/**
 * Device Details page - Device info, open ports, IP address history (keyed by MAC)
 */
import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { Card, Table, Button, Badge } from 'flowbite-react';
import { Sidebar } from '../components/layout/Sidebar';
import { Navbar } from '../components/layout/Navbar';
import { useMetrics } from '../hooks/useMetrics';
import { apiClient } from '../api/client';
import type { NetworkDevice, PortScanResult, IpHistoryEntry } from '../types/devices';

const PORT_SCAN_POLL_INTERVAL_MS = 3000;
const PORT_SCAN_POLL_MAX_ATTEMPTS = 60;

export function DeviceDetails() {
  const { macAddress } = useParams<{ macAddress: string }>();
  const token = localStorage.getItem('access_token');
  const username = localStorage.getItem('username') || 'Unknown';
  const navigate = useNavigate();
  const [device, setDevice] = useState<NetworkDevice | null>(null);
  const [deviceError, setDeviceError] = useState<string | null>(null);
  const [portScan, setPortScan] = useState<PortScanResult | null>(null);
  const [portScanError, setPortScanError] = useState<string | null>(null);
  const [ipHistory, setIpHistory] = useState<IpHistoryEntry[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [scanning, setScanning] = useState(false);
  const { connectionStatus } = useMetrics(token);

  const handleLogout = async () => {
    await apiClient.logout();
    navigate('/login');
  };

  const fetchDevice = useCallback(async () => {
    if (!token || !macAddress) return;
    setDeviceError(null);
    try {
      const data = await apiClient.getDeviceByMac(macAddress);
      setDevice(data);
    } catch (err: unknown) {
      setDevice(null);
      setDeviceError(err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { status?: number } }).response?.status === 404
          ? 'Device not found'
          : 'Failed to load device'
        : 'Failed to load device');
    }
  }, [token, macAddress]);

  const fetchPortScan = useCallback(async () => {
    if (!token || !macAddress) return;
    setPortScanError(null);
    try {
      const data = await apiClient.getDevicePortScan(macAddress);
      setPortScan(data);
    } catch (err: unknown) {
      const status = err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { status?: number } }).response?.status
        : undefined;
      if (status === 404) {
        setPortScan(null);
        setPortScanError(null);
      } else {
        setPortScan(null);
        setPortScanError('Failed to load port scan');
      }
    }
  }, [token, macAddress]);

  const fetchIpHistory = useCallback(async () => {
    if (!token || !macAddress) return;
    try {
      const data = await apiClient.getDeviceIpHistory(macAddress);
      setIpHistory(data);
    } catch {
      setIpHistory([]);
    }
  }, [token, macAddress]);

  useEffect(() => {
    fetchDevice();
  }, [fetchDevice]);

  useEffect(() => {
    if (!macAddress) return;
    fetchPortScan();
    fetchIpHistory();
  }, [macAddress, fetchPortScan, fetchIpHistory]);

  const triggerPortScan = async () => {
    if (!token || !macAddress || scanning) return;
    setScanning(true);
    try {
      await apiClient.triggerDevicePortScan(macAddress);
      let attempts = 0;
      const poll = async () => {
        try {
          const data = await apiClient.getDevicePortScan(macAddress);
          setPortScan(data);
          if (data.scan_status === 'pending' || data.scan_status === 'in_progress') {
            if (attempts < PORT_SCAN_POLL_MAX_ATTEMPTS) {
              attempts += 1;
              setTimeout(poll, PORT_SCAN_POLL_INTERVAL_MS);
            } else {
              setScanning(false);
            }
          } else {
            setScanning(false);
          }
        } catch {
          if (attempts < PORT_SCAN_POLL_MAX_ATTEMPTS) {
            attempts += 1;
            setTimeout(poll, PORT_SCAN_POLL_INTERVAL_MS);
          } else {
            setScanning(false);
          }
        }
      };
      setTimeout(poll, PORT_SCAN_POLL_INTERVAL_MS);
    } catch {
      setScanning(false);
    }
  };

  if (deviceError && !device) {
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
          <main className="flex-1 overflow-y-auto p-4 md:p-6 bg-gray-50 dark:bg-gray-900">
            <div className="mb-4 text-sm text-gray-600 dark:text-gray-400">
              <Link to="/devices" className="hover:text-gray-900 dark:hover:text-gray-100">Devices</Link>
              <span className="mx-2">›</span>
              <span className="text-gray-900 dark:text-gray-100">Device details</span>
            </div>
            <Card>
              <p className="text-gray-600 dark:text-gray-400">{deviceError}</p>
              <Button color="gray" onClick={() => navigate('/devices')}>Back to devices</Button>
            </Card>
          </main>
        </div>
      </div>
    );
  }

  if (!device) {
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
          <main className="flex-1 overflow-y-auto p-4 md:p-6 bg-gray-50 dark:bg-gray-900 flex items-center justify-center">
            <div className="text-center">
              <div className="inline-block animate-spin rounded-full h-10 w-10 border-b-2 border-gray-900 dark:border-gray-100" />
              <p className="mt-2 text-gray-600 dark:text-gray-400">Loading device...</p>
            </div>
          </main>
        </div>
      </div>
    );
  }

  const displayName = device.hostname || device.ip_address || device.mac_address;

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
        <main className="flex-1 overflow-y-auto p-4 md:p-6 bg-gray-50 dark:bg-gray-900">
          <div className="mb-4 text-sm text-gray-600 dark:text-gray-400">
            <Link to="/devices" className="hover:text-gray-900 dark:hover:text-gray-100">Devices</Link>
            <span className="mx-2">›</span>
            <span className="text-gray-900 dark:text-gray-100">{displayName}</span>
            <span className="mx-2">›</span>
            <span className="text-gray-900 dark:text-gray-100">Device details</span>
          </div>

          <div className="mb-4 flex flex-wrap gap-2 items-center">
            <h1 className="text-2xl md:text-3xl font-bold">Device details</h1>
            <Button size="sm" color="gray" as={Link} to={`/devices/${device.ip_address}`}>
              View usage
            </Button>
          </div>

          {/* Device information card */}
          <Card className="mb-6">
            <h2 className="text-lg font-semibold mb-4">Device information</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
              <div className="flex justify-between md:block">
                <span className="text-gray-500">MAC address</span>
                <span className="font-mono ml-2">{device.mac_address}</span>
              </div>
              <div className="flex justify-between md:block">
                <span className="text-gray-500">Current IP</span>
                <span className="font-mono ml-2">{device.ip_address}</span>
              </div>
              <div className="flex justify-between md:block">
                <span className="text-gray-500">Hostname</span>
                <span className="ml-2">{device.hostname || '—'}</span>
              </div>
              <div className="flex justify-between md:block">
                <span className="text-gray-500">Vendor</span>
                <span className="ml-2">{device.vendor || '—'}</span>
              </div>
              <div className="flex justify-between md:block">
                <span className="text-gray-500">Network</span>
                <Badge color={device.network === 'homelab' ? 'info' : 'purple'} size="sm" className="ml-2">
                  {device.network.toUpperCase()}
                </Badge>
              </div>
              <div className="flex justify-between md:block">
                <span className="text-gray-500">Status</span>
                <Badge color={device.is_online ? 'success' : 'gray'} size="sm" className="ml-2">
                  {device.is_online ? 'Online' : 'Offline'}
                </Badge>
              </div>
              <div className="flex justify-between md:block">
                <span className="text-gray-500">Type</span>
                <Badge
                  color={device.is_dhcp ? (device.is_static ? 'success' : 'warning') : 'gray'}
                  size="sm"
                  className="ml-2"
                >
                  {device.is_static ? 'Static DHCP' : device.is_dhcp ? 'Dynamic' : 'Static IP'}
                </Badge>
              </div>
              <div className="flex justify-between md:block">
                <span className="text-gray-500">Last seen</span>
                <span className="ml-2">{new Date(device.last_seen).toLocaleString()}</span>
              </div>
              {device.favorite && (
                <div className="flex justify-between md:block">
                  <span className="text-gray-500">Favorite</span>
                  <Badge color="warning" size="sm" className="ml-2">★</Badge>
                </div>
              )}
            </div>
          </Card>

          {/* Open ports */}
          <Card className="mb-6">
            <div className="flex flex-wrap justify-between items-center gap-2 mb-4">
              <h2 className="text-lg font-semibold">Open ports</h2>
              <Button
                size="sm"
                color="gray"
                onClick={triggerPortScan}
                isProcessing={scanning}
                disabled={scanning}
              >
                {scanning ? 'Scanning...' : portScan ? 'Scan ports' : 'Scan ports'}
              </Button>
            </div>
            {portScanError && (
              <p className="text-sm text-red-600 dark:text-red-400 mb-2">{portScanError}</p>
            )}
            {!portScan && !portScanError ? (
              <p className="text-gray-600 dark:text-gray-400">No scan yet. Click &quot;Scan ports&quot; to run a port scan.</p>
            ) : portScan ? (
              <div>
                <div className="mb-4 flex flex-wrap items-center gap-2">
                  <Badge
                    color={
                      portScan.scan_status === 'completed' ? 'success' :
                      portScan.scan_status === 'failed' ? 'failure' :
                      portScan.scan_status === 'in_progress' ? 'warning' : 'gray'
                    }
                  >
                    {portScan.scan_status.toUpperCase()}
                  </Badge>
                  <span className="text-sm text-gray-600 dark:text-gray-400">
                    Started: {new Date(portScan.scan_started_at).toLocaleString()}
                  </span>
                  {portScan.scan_completed_at && (
                    <span className="text-sm text-gray-600 dark:text-gray-400">
                      Completed: {new Date(portScan.scan_completed_at).toLocaleString()}
                    </span>
                  )}
                </div>
                {portScan.error_message && (
                  <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded">
                    <p className="text-sm text-red-800 dark:text-red-200">
                      <strong>Error:</strong> {portScan.error_message}
                    </p>
                  </div>
                )}
                {portScan.ports.length > 0 ? (
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
                        {portScan.ports.map((port, idx) => (
                          <Table.Row key={idx}>
                            <Table.Cell className="font-mono">{port.port}</Table.Cell>
                            <Table.Cell className="uppercase">{port.protocol}</Table.Cell>
                            <Table.Cell>
                              <Badge
                                color={
                                  port.state === 'open' ? 'success' :
                                  port.state === 'closed' ? 'gray' :
                                  port.state === 'filtered' ? 'warning' : 'gray'
                                }
                                size="sm"
                              >
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
                ) : portScan.scan_status === 'completed' ? (
                  <p className="text-gray-600 dark:text-gray-400">No open ports found</p>
                ) : (
                  <p className="text-gray-600 dark:text-gray-400">Scan in progress or no results yet</p>
                )}
              </div>
            ) : null}
          </Card>

          {/* IP address history */}
          <Card>
            <h2 className="text-lg font-semibold mb-4">IP address history</h2>
            {ipHistory.length === 0 ? (
              <p className="text-gray-600 dark:text-gray-400">No history (current IP only, or no port scans yet)</p>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <Table.Head>
                    <Table.HeadCell>IP address</Table.HeadCell>
                    <Table.HeadCell>Last seen</Table.HeadCell>
                  </Table.Head>
                  <Table.Body>
                    {ipHistory.map((entry, idx) => (
                      <Table.Row key={idx}>
                        <Table.Cell className="font-mono">{entry.ip_address}</Table.Cell>
                        <Table.Cell>{new Date(entry.last_seen).toLocaleString()}</Table.Cell>
                      </Table.Row>
                    ))}
                  </Table.Body>
                </Table>
              </div>
            )}
          </Card>
        </main>
      </div>
    </div>
  );
}
