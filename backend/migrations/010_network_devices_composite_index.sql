-- Migration: Add composite index on network_devices (network, last_seen)
-- Date: 2026-01-29
-- Description: Optimize queries that filter by network and last_seen (used in /api/devices/all)

CREATE INDEX IF NOT EXISTS idx_network_devices_network_last_seen 
ON network_devices (network, last_seen DESC);
