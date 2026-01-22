-- Migration 008: DNS and DHCP Configuration Change History
-- Tracks all configuration changes for audit and revert functionality
-- Retention policy: Keep at minimum the last 10 changes, plus all changes within 90 days

-- DNS configuration history table
CREATE TABLE IF NOT EXISTS dns_config_history (
    id SERIAL PRIMARY KEY,
    network VARCHAR(50) NOT NULL,  -- "homelab" or "lan"
    change_type VARCHAR(20) NOT NULL,  -- "create", "update", "delete"
    changed_by VARCHAR(255) NOT NULL,  -- Username who made the change
    timestamp TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    config_snapshot JSONB NOT NULL,  -- Full DNS configuration at time of change
    status VARCHAR(20) DEFAULT 'active' NOT NULL,  -- "active" or "reverted"
    reverted_by VARCHAR(255),  -- Username who reverted (if reverted)
    reverted_at TIMESTAMPTZ,  -- When reverted (if reverted)
    change_details JSONB  -- Additional details about what changed (zone_id, record_id, etc.)
);

-- DHCP configuration history table
CREATE TABLE IF NOT EXISTS dhcp_config_history (
    id SERIAL PRIMARY KEY,
    network VARCHAR(50) NOT NULL,  -- "homelab" or "lan"
    change_type VARCHAR(20) NOT NULL,  -- "create", "update", "delete"
    changed_by VARCHAR(255) NOT NULL,  -- Username who made the change
    timestamp TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    config_snapshot JSONB NOT NULL,  -- Full DHCP configuration at time of change
    status VARCHAR(20) DEFAULT 'active' NOT NULL,  -- "active" or "reverted"
    reverted_by VARCHAR(255),  -- Username who reverted (if reverted)
    reverted_at TIMESTAMPTZ,  -- When reverted (if reverted)
    change_details JSONB  -- Additional details about what changed (network_id, reservation_id, etc.)
);

-- Indexes for efficient querying
-- For retrieving last N changes per network
CREATE INDEX IF NOT EXISTS idx_dns_config_history_network_timestamp 
    ON dns_config_history(network, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_dhcp_config_history_network_timestamp 
    ON dhcp_config_history(network, timestamp DESC);

-- For cleanup queries (find records older than 90 days)
CREATE INDEX IF NOT EXISTS idx_dns_config_history_timestamp 
    ON dns_config_history(timestamp);

CREATE INDEX IF NOT EXISTS idx_dhcp_config_history_timestamp 
    ON dhcp_config_history(timestamp);

-- For filtering by status
CREATE INDEX IF NOT EXISTS idx_dns_config_history_status 
    ON dns_config_history(status);

CREATE INDEX IF NOT EXISTS idx_dhcp_config_history_status 
    ON dhcp_config_history(status);

-- Function to clean up old history records based on retention policy
-- Retention: Keep at minimum last 10 changes, plus all within 90 days
CREATE OR REPLACE FUNCTION cleanup_dns_config_history()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER := 0;
    cutoff_date TIMESTAMPTZ;
BEGIN
    cutoff_date := NOW() - INTERVAL '90 days';
    
    -- For each network, delete records that are:
    -- - Older than 90 days AND
    -- - Not in the last 10 changes
    WITH last_10_per_network AS (
        SELECT DISTINCT id
        FROM (
            SELECT id, network,
                   ROW_NUMBER() OVER (PARTITION BY network ORDER BY timestamp DESC) as rn
            FROM dns_config_history
        ) ranked
        WHERE rn <= 10
    ),
    recent_90_days AS (
        SELECT id
        FROM dns_config_history
        WHERE timestamp >= cutoff_date
    )
    DELETE FROM dns_config_history
    WHERE timestamp < cutoff_date
      AND id NOT IN (SELECT id FROM last_10_per_network)
      AND id NOT IN (SELECT id FROM recent_90_days);
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION cleanup_dhcp_config_history()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER := 0;
    cutoff_date TIMESTAMPTZ;
BEGIN
    cutoff_date := NOW() - INTERVAL '90 days';
    
    -- For each network, delete records that are:
    -- - Older than 90 days AND
    -- - Not in the last 10 changes
    WITH last_10_per_network AS (
        SELECT DISTINCT id
        FROM (
            SELECT id, network,
                   ROW_NUMBER() OVER (PARTITION BY network ORDER BY timestamp DESC) as rn
            FROM dhcp_config_history
        ) ranked
        WHERE rn <= 10
    ),
    recent_90_days AS (
        SELECT id
        FROM dhcp_config_history
        WHERE timestamp >= cutoff_date
    )
    DELETE FROM dhcp_config_history
    WHERE timestamp < cutoff_date
      AND id NOT IN (SELECT id FROM last_10_per_network)
      AND id NOT IN (SELECT id FROM recent_90_days);
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;
