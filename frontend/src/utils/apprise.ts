/**
 * Shared utilities for Apprise service handling
 */
import type { AppriseServiceInfoConfig } from '../types/notifications';
import type { AppriseConfig } from '../types/apprise-config';

/**
 * Format service name for display
 */
export function formatServiceName(name: string): string {
  const nameMap: Record<string, string> = {
    'homeAssistant': 'Home Assistant',
    'telegram': 'Telegram',
    'discord': 'Discord',
    'slack': 'Slack',
    'email': 'Email',
    'ntfy': 'ntfy'
  };
  return nameMap[name] || name.charAt(0).toUpperCase() + name.slice(1);
}

/**
 * Transform AppriseConfig services to AppriseServiceInfoConfig format
 * Uses service names as string IDs for config-based services
 */
export function transformConfigServices(
  config: AppriseConfig
): AppriseServiceInfoConfig[] {
  return Object.entries(config.services || {})
    .filter(([_, service]) => service.enable === true)
    .map(([name, service]) => ({
      id: name, // Use service name as ID (string)
      name: formatServiceName(name),
      description: null,
      enabled: service.enable,
      originalName: name // Store original name for API calls
    }));
}
