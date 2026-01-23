/**
 * DNS Blocklists configuration types
 */

export interface BlocklistItem {
  enable: boolean;
  url: string;
  description: string;
  updateInterval: string;
}

export interface BlocklistsConfig {
  enable: boolean;
  blocklists: Record<string, BlocklistItem>;
}

export interface BlocklistsConfigUpdate {
  enable?: boolean;
  blocklists?: Record<string, BlocklistItem>;
}
