/**
 * Apprise API configuration types
 */

export interface AppriseServiceConfig {
  enable: boolean;
  smtpHost?: string | null;
  smtpPort?: number | null;
  username?: string | null;
  to?: string | null;
  from?: string | null;
  host?: string | null;
  port?: number | null;
  useHttps?: boolean | null;
  chatId?: string | null;
  topic?: string | null;
  server?: string | null;
}

export interface AppriseConfig {
  enable: boolean;
  port: number;
  attachSize: number;
  services: Record<string, AppriseServiceConfig>;
}

export interface AppriseConfigUpdate {
  enable?: boolean;
  port?: number;
  attachSize?: number;
  services?: Record<string, AppriseServiceConfig>;
}
