/**
 * Device port scanning types
 */

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
