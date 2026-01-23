/**
 * CAKE traffic shaping configuration types
 */

export interface CakeConfig {
  enable: boolean;
  aggressiveness: 'auto' | 'conservative' | 'moderate' | 'aggressive';
  uploadBandwidth: string | null;
  downloadBandwidth: string | null;
}

export interface CakeConfigUpdate {
  enable?: boolean;
  aggressiveness?: 'auto' | 'conservative' | 'moderate' | 'aggressive';
  uploadBandwidth?: string | null;
  downloadBandwidth?: string | null;
}
