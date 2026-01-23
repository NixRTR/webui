/**
 * Dynamic DNS configuration types
 */

export interface DynDnsConfig {
  enable: boolean;
  provider: string;
  domain: string;
  subdomain: string;
  domainId: number;
  recordId: number;
  checkInterval: string;
}

export interface DynDnsConfigUpdate {
  enable?: boolean;
  provider?: string;
  domain?: string;
  subdomain?: string;
  domainId?: number;
  recordId?: number;
  checkInterval?: string;
}
