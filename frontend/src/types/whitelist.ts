/**
 * DNS Whitelist configuration types
 */

export interface WhitelistConfig {
  domains: string[];
}

export interface WhitelistConfigUpdate {
  domains?: string[];
}
