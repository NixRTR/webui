/**
 * API client with Axios
 */
import axios, { AxiosInstance } from 'axios';
import type { LoginRequest, LoginResponse, HistoricalDataPoint } from '../types/metrics';
import type {
  NotificationRule,
  NotificationRuleCreate,
  NotificationRuleUpdate,
  NotificationHistory,
  NotificationParameterMetadata,
  NotificationTestResponse,
  AppriseServiceInfo,
  AppriseService,
  AppriseServiceCreate,
  AppriseServiceUpdate,
} from '../types/notifications';
import type {
  DnsZone,
  DnsZoneCreate,
  DnsZoneUpdate,
  DnsRecord,
  DnsRecordCreate,
  DnsRecordUpdate,
  DynamicDnsEntry,
} from '../types/dns';
import type {
  DhcpNetwork,
  DhcpNetworkCreate,
  DhcpNetworkUpdate,
  DhcpReservation,
  DhcpReservationCreate,
  DhcpReservationUpdate,
} from '../types/dhcp';
import type {
  CakeConfig,
  CakeConfigUpdate,
} from '../types/cake';
import type {
  AppriseConfig,
  AppriseConfigUpdate,
} from '../types/apprise-config';
import type {
  DynDnsConfig,
  DynDnsConfigUpdate,
} from '../types/dyndns';
import type {
  PortForwardingRule,
  PortForwardingRuleCreate,
  PortForwardingRuleUpdate,
} from '../types/port-forwarding';
import type {
  BlocklistsConfig,
  BlocklistsConfigUpdate,
} from '../types/blocklists';
import type {
  WhitelistConfig,
  WhitelistConfigUpdate,
} from '../types/whitelist';
import type {
  NetworkDevice,
  IpHistoryEntry,
  PortScanResult,
  PortScanTriggerResponse,
} from '../types/devices';
import type {
  WorkerStatusResponse,
  PurgeQueuesResponse,
  TriggerTestTaskResponse,
} from '../types/worker-status';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

class APIClient {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE_URL,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Add request interceptor to inject JWT token
    this.client.interceptors.request.use(
      (config) => {
        const token = localStorage.getItem('access_token');
        if (token) {
          config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
      },
      (error) => Promise.reject(error)
    );

    // Add response interceptor to handle errors
    this.client.interceptors.response.use(
      (response) => response,
      (error) => {
        if (error.response?.status === 401) {
          // Token expired or invalid
          localStorage.removeItem('access_token');
          localStorage.removeItem('username');
          window.location.href = '/login';
        }
        return Promise.reject(error);
      }
    );
  }

  // Authentication
  async login(credentials: LoginRequest): Promise<LoginResponse> {
    const response = await this.client.post<LoginResponse>('/api/auth/login', credentials);
    return response.data;
  }

  async logout(): Promise<void> {
    await this.client.post('/api/auth/logout');
    localStorage.removeItem('access_token');
    localStorage.removeItem('username');
  }

  async getCurrentUser(): Promise<{ username: string }> {
    const response = await this.client.get<{ username: string }>('/api/auth/me');
    return response.data;
  }

  // Historical data
  async getSystemHistory(
    start?: Date,
    end?: Date,
    interval?: number
  ): Promise<HistoricalDataPoint[]> {
    const params: Record<string, string> = {};
    if (start) params.start = start.toISOString();
    if (end) params.end = end.toISOString();
    if (interval) params.interval = interval.toString();

    const response = await this.client.get<HistoricalDataPoint[]>('/api/history/system', {
      params,
    });
    return response.data;
  }

  async getInterfaceHistory(
    interfaceName: string,
    start?: Date,
    end?: Date,
    interval?: number
  ): Promise<HistoricalDataPoint[]> {
    const params: Record<string, string> = {};
    if (start) params.start = start.toISOString();
    if (end) params.end = end.toISOString();
    if (interval) params.interval = interval.toString();

    const response = await this.client.get<HistoricalDataPoint[]>(
      `/api/history/interface/${interfaceName}`,
      { params }
    );
    return response.data;
  }

  async getBandwidthHistory(
    network: string,
    period: '1h' | '24h' | '7d' | '30d' = '1h'
  ): Promise<HistoricalDataPoint[]> {
    const response = await this.client.get<HistoricalDataPoint[]>(
      `/api/history/bandwidth/${network}`,
      { params: { period } }
    );
    return response.data;
  }

  // Health check
  async healthCheck(): Promise<{ status: string; active_connections: number }> {
    const response = await this.client.get<{ status: string; active_connections: number }>(
      '/api/health'
    );
    return response.data;
  }

  // Client bandwidth
  async getCurrentClientBandwidth(): Promise<any[]> {
    const response = await this.client.get('/api/bandwidth/clients/current');
    return response.data;
  }

  async getClientBandwidthHistory(
    macAddress: string,
    range: string = '1h',
    interval: string = 'raw'
  ): Promise<any> {
    const response = await this.client.get(`/api/bandwidth/clients/${macAddress}`, {
      params: { range, interval },
    });
    return response.data;
  }

  async getBulkClientBandwidthHistory(
    range: string = '1h',
    interval: string = 'raw'
  ): Promise<Record<string, any>> {
    const response = await this.client.get('/api/bandwidth/clients/history/bulk', {
      params: { range, interval },
    });
    return response.data;
  }

  async getCurrentInterfaceStats(): Promise<Record<string, any>> {
    const response = await this.client.get('/api/bandwidth/interfaces/current');
    return response.data;
  }

  async getInterfaceTotals(timeRange: string = '1h'): Promise<Record<string, any>> {
    const response = await this.client.get('/api/bandwidth/interfaces/totals', {
      params: { range: timeRange },
    });
    return response.data;
  }

  // Client connections
  async getClientConnections(
    clientIp: string,
    timeRange: string = '1h'
  ): Promise<any[]> {
    const response = await this.client.get(`/api/bandwidth/connections/${clientIp}/current`, {
      params: { range: timeRange },
    });
    return response.data;
  }

  async getConnectionHistory(
    clientIp: string,
    remoteIp: string,
    remotePort: number,
    timeRange: string = '1h',
    interval: string = 'raw'
  ): Promise<any> {
    const response = await this.client.get(`/api/bandwidth/connections/${clientIp}/history`, {
      params: {
        remote_ip: remoteIp,
        remote_port: remotePort,
        range: timeRange,
        interval,
      },
    });
    return response.data;
  }

  // System info
  async getFastfetch(): Promise<{ text: string }> {
    const response = await this.client.get<{ text: string }>('/api/system/fastfetch');
    return response.data;
  }

  // GitHub stats
  async getGitHubStats(): Promise<{ stars: number; forks: number }> {
    const response = await this.client.get<{ stars: number; forks: number }>('/api/system/github-stats');
    return response.data;
  }

  // Documentation
  async getDocumentation(): Promise<{ content: string }> {
    const response = await this.client.get<{ content: string }>('/api/system/documentation');
    return response.data;
  }

  // CAKE Traffic Shaping
  async getCakeStatus(): Promise<{ enabled: boolean; interface?: string }> {
    const response = await this.client.get<{ enabled: boolean; interface?: string }>('/api/cake/status');
    return response.data;
  }

  async getCurrentCakeStats(): Promise<any> {
    const response = await this.client.get('/api/cake/current');
    return response.data;
  }

  // Notification rules
  async getNotificationRules(): Promise<NotificationRule[]> {
    const response = await this.client.get<NotificationRule[]>('/api/notifications/rules');
    return response.data;
  }

  async getNotificationParameters(): Promise<NotificationParameterMetadata[]> {
    const response = await this.client.get<NotificationParameterMetadata[]>('/api/notifications/parameters');
    return response.data;
  }

  async createNotificationRule(payload: NotificationRuleCreate): Promise<NotificationRule> {
    const response = await this.client.post<NotificationRule>('/api/notifications/rules', payload);
    return response.data;
  }

  async updateNotificationRule(ruleId: number, payload: NotificationRuleUpdate): Promise<NotificationRule> {
    const response = await this.client.put<NotificationRule>(`/api/notifications/rules/${ruleId}`, payload);
    return response.data;
  }

  async deleteNotificationRule(ruleId: number): Promise<void> {
    await this.client.delete(`/api/notifications/rules/${ruleId}`);
  }

  async getNotificationHistory(ruleId: number, limit: number = 50): Promise<NotificationHistory> {
    const response = await this.client.get<NotificationHistory>(`/api/notifications/rules/${ruleId}/history`, {
      params: { limit },
    });
    return response.data;
  }

  async testNotificationRule(ruleId: number): Promise<NotificationTestResponse> {
    const response = await this.client.post<NotificationTestResponse>(`/api/notifications/rules/${ruleId}/test`, {});
    return response.data;
  }

  // Apprise Notifications
  async getAppriseStatus(): Promise<{ enabled: boolean }> {
    const response = await this.client.get<{ enabled: boolean }>('/api/apprise/status');
    return response.data;
  }

  async getAppriseServices(): Promise<AppriseServiceInfo[]> {
    const response = await this.client.get<AppriseServiceInfo[]>('/api/apprise/services');
    return response.data;
  }

  async getAppriseService(id: number): Promise<AppriseService> {
    const response = await this.client.get<AppriseService>(`/api/apprise/services/${id}`);
    return response.data;
  }

  async createAppriseService(service: AppriseServiceCreate): Promise<AppriseService> {
    const response = await this.client.post<AppriseService>('/api/apprise/services', service);
    return response.data;
  }

  async updateAppriseService(id: number, service: AppriseServiceUpdate): Promise<AppriseService> {
    const response = await this.client.put<AppriseService>(`/api/apprise/services/${id}`, service);
    return response.data;
  }

  async deleteAppriseService(id: number): Promise<{ message: string }> {
    const response = await this.client.delete<{ message: string }>(`/api/apprise/services/${id}`);
    return response.data;
  }

  async testAppriseServiceById(serviceId: number): Promise<{ success: boolean; message: string; details?: string }> {
    const response = await this.client.post<{ success: boolean; message: string; details?: string }>(`/api/apprise/services/${serviceId}/test`);
    return response.data;
  }

  async sendAppriseNotification(
    body: string,
    title?: string,
    notificationType?: string
  ): Promise<{ success: boolean; message: string; details?: string }> {
    const response = await this.client.post<{ success: boolean; message: string; details?: string }>('/api/apprise/notify', {
      body,
      title,
      notification_type: notificationType,
    });
    return response.data;
  }

  async testAppriseService(serviceIndex: number): Promise<{ success: boolean; message: string; details?: string }> {
    const response = await this.client.post<{ success: boolean; message: string; details?: string }>(`/api/apprise/test/${serviceIndex}`);
    return response.data;
  }

  async testAppriseServiceByName(serviceName: string): Promise<{ success: boolean; message: string; details?: string }> {
    const response = await this.client.post<{ success: boolean; message: string; details?: string }>(`/api/apprise/config/test/${serviceName}`);
    return response.data;
  }

  async testAllAppriseServices(): Promise<{ success: boolean; message: string; details?: string }> {
    const response = await this.client.post<{ success: boolean; message: string; details?: string }>('/api/apprise/config/test-all');
    return response.data;
  }

  async sendAppriseNotificationToService(
    serviceIndex: number,
    body: string,
    title?: string,
    notificationType?: string
  ): Promise<{ success: boolean; message: string; details?: string }> {
    const response = await this.client.post<{ success: boolean; message: string; details?: string }>(
      `/api/apprise/send/${serviceIndex}`,
      {
        body,
        title,
        notification_type: notificationType,
      }
    );
    return response.data;
  }

  async sendAppriseNotificationToServiceById(
    serviceId: number,
    body: string,
    title?: string,
    notificationType?: string
  ): Promise<{ success: boolean; message: string; details?: string }> {
    const response = await this.client.post<{ success: boolean; message: string; details?: string }>(
      `/api/apprise/services/${serviceId}/send`,
      {
        body,
        title,
        notification_type: notificationType,
      }
    );
    return response.data;
  }

  async getCakeHistory(
    range: string = '1h',
    interfaceName?: string
  ): Promise<{ interface: string; data: any[] }> {
    const params: Record<string, string> = { range };
    if (interfaceName) params.interface = interfaceName;
    const response = await this.client.get<{ interface: string; data: any[] }>('/api/cake/history', {
      params,
    });
    return response.data;
  }

  // DNS Zone methods
  async getDnsZones(network?: 'homelab' | 'lan'): Promise<DnsZone[]> {
    const params: Record<string, string> = {};
    if (network) params.network = network;
    const response = await this.client.get<DnsZone[]>('/api/dns/zones', { params });
    return response.data;
  }

  async createDnsZone(zone: DnsZoneCreate): Promise<DnsZone> {
    const response = await this.client.post<DnsZone>('/api/dns/zones', zone);
    return response.data;
  }

  async getDnsZone(zoneName: string, network: string): Promise<DnsZone> {
    const encodedZoneName = encodeURIComponent(zoneName);
    const response = await this.client.get<DnsZone>(`/api/dns/zones/${encodedZoneName}`, {
      params: { network }
    });
    return response.data;
  }

  async updateDnsZone(zoneName: string, network: string, zone: DnsZoneUpdate): Promise<DnsZone> {
    const encodedZoneName = encodeURIComponent(zoneName);
    const response = await this.client.put<DnsZone>(`/api/dns/zones/${encodedZoneName}`, zone, {
      params: { network }
    });
    return response.data;
  }

  async deleteDnsZone(zoneName: string, network: string): Promise<{ message: string }> {
    const encodedZoneName = encodeURIComponent(zoneName);
    const response = await this.client.delete<{ message: string }>(`/api/dns/zones/${encodedZoneName}`, {
      params: { network }
    });
    return response.data;
  }

  // DNS Record methods
  async getDnsRecords(zoneName: string, network: string): Promise<DnsRecord[]> {
    const encodedZoneName = encodeURIComponent(zoneName);
    const response = await this.client.get<DnsRecord[]>(`/api/dns/zones/${encodedZoneName}/records`, {
      params: { network }
    });
    return response.data;
  }

  async createDnsRecord(zoneName: string, network: string, record: DnsRecordCreate): Promise<DnsRecord> {
    const encodedZoneName = encodeURIComponent(zoneName);
    const response = await this.client.post<DnsRecord>(`/api/dns/zones/${encodedZoneName}/records`, record, {
      params: { network }
    });
    return response.data;
  }

  async getDnsRecord(recordName: string, network: string, zoneName: string): Promise<DnsRecord> {
    const encodedRecordName = encodeURIComponent(recordName);
    const response = await this.client.get<DnsRecord>(`/api/dns/records/${encodedRecordName}`, {
      params: { network, zone_name: zoneName }
    });
    return response.data;
  }

  async updateDnsRecord(recordName: string, network: string, zoneName: string, record: DnsRecordUpdate): Promise<DnsRecord> {
    const encodedRecordName = encodeURIComponent(recordName);
    const response = await this.client.put<DnsRecord>(`/api/dns/records/${encodedRecordName}`, record, {
      params: { network, zone_name: zoneName }
    });
    return response.data;
  }

  async deleteDnsRecord(recordName: string, network: string, zoneName: string): Promise<{ message: string }> {
    const encodedRecordName = encodeURIComponent(recordName);
    const response = await this.client.delete<{ message: string }>(`/api/dns/records/${encodedRecordName}`, {
      params: { network, zone_name: zoneName }
    });
    return response.data;
  }

  async getDnsDynamicEntries(network: 'homelab' | 'lan'): Promise<DynamicDnsEntry[]> {
    const response = await this.client.get<DynamicDnsEntry[]>(`/api/dns/networks/${network}/dynamic-entries`);
    return response.data;
  }

  // DHCP Network methods
  async getDhcpNetworks(network?: 'homelab' | 'lan'): Promise<DhcpNetwork[]> {
    const params: Record<string, string> = {};
    if (network) params.network = network;
    const response = await this.client.get<DhcpNetwork[]>('/api/dhcp/networks', { params });
    return response.data;
  }

  async createDhcpNetwork(network: DhcpNetworkCreate): Promise<DhcpNetwork> {
    const response = await this.client.post<DhcpNetwork>('/api/dhcp/networks', network);
    return response.data;
  }

  async getDhcpNetwork(network: string): Promise<DhcpNetwork> {
    const response = await this.client.get<DhcpNetwork>(`/api/dhcp/networks/${network}`);
    return response.data;
  }

  async updateDhcpNetwork(network: string, networkUpdate: DhcpNetworkUpdate): Promise<DhcpNetwork> {
    const response = await this.client.put<DhcpNetwork>(`/api/dhcp/networks/${network}`, networkUpdate);
    return response.data;
  }

  async deleteDhcpNetwork(network: string): Promise<{ message: string }> {
    const response = await this.client.delete<{ message: string }>(`/api/dhcp/networks/${network}`);
    return response.data;
  }

  // DHCP Reservation methods
  async getDhcpSuggestIp(network: string, mac: string): Promise<{ ip_address: string | null }> {
    const response = await this.client.get<{ ip_address: string | null }>('/api/dhcp/suggest-ip', {
      params: { network, mac },
    });
    return response.data;
  }

  async getDhcpReservations(network: string): Promise<DhcpReservation[]> {
    const response = await this.client.get<DhcpReservation[]>(`/api/dhcp/networks/${network}/reservations`);
    return response.data;
  }

  async createDhcpReservation(network: string, reservation: DhcpReservationCreate): Promise<DhcpReservation> {
    const response = await this.client.post<DhcpReservation>(`/api/dhcp/networks/${network}/reservations`, reservation);
    return response.data;
  }

  async getDhcpReservation(hwAddress: string, network: string): Promise<DhcpReservation> {
    const encodedHwAddress = encodeURIComponent(hwAddress);
    const response = await this.client.get<DhcpReservation>(`/api/dhcp/reservations/${encodedHwAddress}`, {
      params: { network }
    });
    return response.data;
  }

  async updateDhcpReservation(hwAddress: string, network: string, reservation: DhcpReservationUpdate): Promise<DhcpReservation> {
    const encodedHwAddress = encodeURIComponent(hwAddress);
    const response = await this.client.put<DhcpReservation>(`/api/dhcp/reservations/${encodedHwAddress}`, reservation, {
      params: { network }
    });
    return response.data;
  }

  async deleteDhcpReservation(hwAddress: string, network: string): Promise<{ message: string }> {
    const encodedHwAddress = encodeURIComponent(hwAddress);
    const response = await this.client.delete<{ message: string }>(`/api/dhcp/reservations/${encodedHwAddress}`, {
      params: { network }
    });
    return response.data;
  }

  // DNS Service Control
  async getDnsServiceStatus(network: 'homelab' | 'lan'): Promise<{
    network: string;
    service_name: string;
    is_active: boolean;
    is_enabled: boolean;
    exists: boolean;
    pid?: number | null;
    memory_mb?: number | null;
    cpu_percent?: number | null;
  }> {
    const response = await this.client.get(`/api/dns/service-status/${network}`);
    return response.data;
  }

  async controlDnsService(network: 'homelab' | 'lan', action: 'start' | 'stop' | 'restart' | 'reload'): Promise<{ message: string }> {
    const response = await this.client.post(`/api/dns/service/${network}/${action}`);
    return response.data;
  }

  // DHCP Service Control
  async getDhcpServiceStatus(network: 'homelab' | 'lan'): Promise<{
    service_name: string;
    network: string;
    is_active: boolean;
    is_enabled: boolean;
    exists: boolean;
    pid?: number | null;
    memory_mb?: number | null;
    cpu_percent?: number | null;
  }> {
    const response = await this.client.get(`/api/dhcp/service-status/${network}`);
    return response.data;
  }

  async controlDhcpService(network: 'homelab' | 'lan', action: 'start' | 'stop' | 'restart' | 'reload'): Promise<{ message: string }> {
    const response = await this.client.post(`/api/dhcp/service/${network}/${action}`);
    return response.data;
  }

  // CAKE Configuration
  async getCakeConfig(): Promise<CakeConfig> {
    const response = await this.client.get<CakeConfig>('/api/cake/config');
    return response.data;
  }

  async updateCakeConfig(config: CakeConfigUpdate): Promise<CakeConfig> {
    const response = await this.client.put<CakeConfig>('/api/cake/config', config);
    return response.data;
  }

  // Apprise Configuration
  async getAppriseConfig(): Promise<AppriseConfig> {
    const response = await this.client.get<AppriseConfig>('/api/apprise/config');
    return response.data;
  }

  async updateAppriseConfig(config: AppriseConfigUpdate): Promise<AppriseConfig> {
    const response = await this.client.put<AppriseConfig>('/api/apprise/config', config);
    return response.data;
  }

  // Dynamic DNS Configuration
  async getDynDnsConfig(): Promise<DynDnsConfig> {
    const response = await this.client.get<DynDnsConfig>('/api/dyndns/config');
    return response.data;
  }

  async updateDynDnsConfig(config: DynDnsConfigUpdate): Promise<DynDnsConfig> {
    const response = await this.client.put<DynDnsConfig>('/api/dyndns/config', config);
    return response.data;
  }

  // Port Forwarding
  async getPortForwardingRules(): Promise<PortForwardingRule[]> {
    const response = await this.client.get<PortForwardingRule[]>('/api/port-forwarding');
    return response.data;
  }

  async createPortForwardingRule(rule: PortForwardingRuleCreate): Promise<PortForwardingRule> {
    const response = await this.client.post<PortForwardingRule>('/api/port-forwarding', rule);
    return response.data;
  }

  async updatePortForwardingRule(index: number, rule: PortForwardingRuleUpdate): Promise<PortForwardingRule> {
    const response = await this.client.put<PortForwardingRule>(`/api/port-forwarding/${index}`, rule);
    return response.data;
  }

  async deletePortForwardingRule(index: number): Promise<{ message: string }> {
    const response = await this.client.delete<{ message: string }>(`/api/port-forwarding/${index}`);
    return response.data;
  }

  // Blocklists
  async getBlocklists(network: 'homelab' | 'lan'): Promise<BlocklistsConfig> {
    const response = await this.client.get<BlocklistsConfig>(`/api/blocklists/${network}`);
    return response.data;
  }

  async updateBlocklists(network: 'homelab' | 'lan', config: BlocklistsConfigUpdate): Promise<BlocklistsConfig> {
    const response = await this.client.put<BlocklistsConfig>(`/api/blocklists/${network}`, config);
    return response.data;
  }

  // Whitelist
  async getWhitelist(network: 'homelab' | 'lan'): Promise<WhitelistConfig> {
    const response = await this.client.get<WhitelistConfig>(`/api/whitelist/${network}`);
    return response.data;
  }

  async updateWhitelist(network: 'homelab' | 'lan', config: WhitelistConfigUpdate): Promise<WhitelistConfig> {
    const response = await this.client.put<WhitelistConfig>(`/api/whitelist/${network}`, config);
    return response.data;
  }

  // Device by MAC (for Device Details page)
  async getDeviceByMac(macAddress: string): Promise<NetworkDevice> {
    const response = await this.client.get<NetworkDevice>(`/api/devices/by-mac/${encodeURIComponent(macAddress)}`);
    return response.data;
  }

  async getDeviceIpHistory(macAddress: string): Promise<IpHistoryEntry[]> {
    const response = await this.client.get<IpHistoryEntry[]>(`/api/devices/by-mac/${encodeURIComponent(macAddress)}/ip-history`);
    return response.data;
  }

  // Device Port Scanning
  async getDevicePortScan(macAddress: string): Promise<PortScanResult> {
    const response = await this.client.get<PortScanResult>(`/api/devices/${encodeURIComponent(macAddress)}/ports`);
    return response.data;
  }

  async triggerDevicePortScan(macAddress: string): Promise<PortScanTriggerResponse> {
    const response = await this.client.post<PortScanTriggerResponse>(`/api/devices/${encodeURIComponent(macAddress)}/ports/scan`);
    return response.data;
  }

  // Worker Status (Celery)
  async getWorkerStatus(): Promise<WorkerStatusResponse> {
    const response = await this.client.get<WorkerStatusResponse>('/api/worker-status');
    return response.data;
  }

  async revokeTask(taskId: string, terminate: boolean = true): Promise<void> {
    await this.client.post(`/api/worker-status/tasks/${encodeURIComponent(taskId)}/revoke`, null, {
      params: { terminate },
    });
  }

  async purgeWorkerQueues(): Promise<PurgeQueuesResponse> {
    const response = await this.client.post<PurgeQueuesResponse>('/api/worker-status/queues/purge');
    return response.data;
  }

  async triggerWorkerTestTask(): Promise<TriggerTestTaskResponse> {
    const response = await this.client.post<TriggerTestTaskResponse>('/api/worker-status/test-task');
    return response.data;
  }
}

export const apiClient = new APIClient();

