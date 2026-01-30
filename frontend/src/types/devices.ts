/**
 * Device and port scanning types
 */

/** Single device (same shape as one item from GET /api/devices/all; hostname is effective) */
export interface NetworkDevice {
  network: string;
  ip_address: string;
  mac_address: string;
  hostname: string;
  vendor: string | null;
  is_dhcp: boolean;
  is_static: boolean;
  is_online: boolean;
  last_seen: string;
  favorite?: boolean;
}

/** IP address seen for a device (MAC) with last seen time */
export interface IpHistoryEntry {
  ip_address: string;
  last_seen: string;
}

export type PortScanStatus = 'pending' | 'in_progress' | 'completed' | 'failed';

export interface PortInfo {
  port: number;
  state: string;
  service_name: string | null;
  service_version: string | null;
  service_product: string | null;
  service_extrainfo: string | null;
  protocol: string;
}

export interface PortScanResult {
  scan_id: number;
  mac_address: string;
  ip_address: string;
  scan_status: PortScanStatus;
  scan_started_at: string;
  scan_completed_at: string | null;
  error_message: string | null;
  ports: PortInfo[];
}

export interface PortScanTriggerResponse {
  status: string;
  message: string;
}
