/**
 * Port Forwarding configuration types
 */

export interface PortForwardingRule {
  index: number;
  proto: 'both' | 'tcp' | 'udp';
  externalPort: number;
  destination: string;
  destinationPort: number;
}

export interface PortForwardingRuleCreate {
  proto: 'both' | 'tcp' | 'udp';
  externalPort: number;
  destination: string;
  destinationPort: number;
}

export interface PortForwardingRuleUpdate {
  proto?: 'both' | 'tcp' | 'udp';
  externalPort?: number;
  destination?: string;
  destinationPort?: number;
}
