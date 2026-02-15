-- Add hosting_mode column to dns_zones table
-- hosting_mode: 'fully_hosted' (default) or 'partially_hosted'
-- fully_hosted: Only serve configured records; unlisted names get NXDOMAIN
-- partially_hosted: Serve configured records locally; forward unlisted to upstream

ALTER TABLE dns_zones ADD COLUMN hosting_mode TEXT NOT NULL DEFAULT 'fully_hosted';

-- Add check constraint to ensure valid values
ALTER TABLE dns_zones ADD CONSTRAINT dns_zones_hosting_mode_check 
    CHECK (hosting_mode IN ('fully_hosted', 'partially_hosted'));

-- Create index for faster queries by hosting mode
CREATE INDEX idx_dns_zones_hosting_mode ON dns_zones(hosting_mode);
