-- Migration: Rename device_overrides.nickname to hostname
-- Date: 2026-01-28
-- Description: Replace nickname with hostname so device display name is the editable hostname (syncs to DHCP/dynamic DNS).
-- Idempotent: only renames if column nickname exists (e.g. already applied or table created with hostname).

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'device_overrides' AND column_name = 'nickname'
  ) THEN
    ALTER TABLE device_overrides RENAME COLUMN nickname TO hostname;
  END IF;
END
$$;
