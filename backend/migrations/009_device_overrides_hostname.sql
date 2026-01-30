-- Migration: Rename device_overrides.nickname to hostname
-- Date: 2026-01-28
-- Description: Replace nickname with hostname so device display name is the editable hostname (syncs to DHCP/dynamic DNS).

ALTER TABLE device_overrides RENAME COLUMN nickname TO hostname;
