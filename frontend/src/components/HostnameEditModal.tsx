/**
 * Hostname edit modal - used from Devices page and Settings/DNS Dynamic DNS section.
 * Shows hostname input and static "Full DNS name: hostname.domain" text.
 */
import { useState, useEffect } from 'react';
import { Modal, Button, TextInput, Label, Alert } from 'flowbite-react';
import { apiClient } from '../api/client';

export interface HostnameEditModalProps {
  show: boolean;
  onClose: () => void;
  currentHostname: string;
  dynamicDomain: string | null;
  network: 'homelab' | 'lan';
  macAddress: string;
  ipAddress?: string;
  onSaved: () => void;
}

export function HostnameEditModal({
  show,
  onClose,
  currentHostname,
  dynamicDomain,
  network,
  macAddress,
  ipAddress,
  onSaved,
}: HostnameEditModalProps) {
  const [hostname, setHostname] = useState(currentHostname);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (show) {
      setHostname(currentHostname);
      setError(null);
    }
  }, [show, currentHostname]);

  const fullDnsName = hostname.trim()
    ? dynamicDomain
      ? `${hostname.trim()}.${dynamicDomain}`
      : hostname.trim()
    : '';

  const handleSubmit = async () => {
    const value = hostname.trim();
    if (!value) {
      setError('Hostname is required.');
      return;
    }
    if (value.includes('.')) {
      setError('Use a short hostname without dots (the domain is added automatically).');
      return;
    }
    setError(null);
    setSaving(true);
    try {
      await apiClient.setDeviceHostname(macAddress, value, network, ipAddress);
      onSaved();
      onClose();
    } catch (err: unknown) {
      const message =
        err && typeof err === 'object' && 'response' in err && err.response && typeof err.response === 'object' && 'data' in err.response
          ? String((err.response as { data?: { detail?: string } }).data?.detail)
          : err instanceof Error
            ? err.message
            : 'Failed to save hostname';
      setError(message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal show={show} onClose={onClose} size="md">
      <Modal.Header>Edit hostname</Modal.Header>
      <Modal.Body>
        <div className="space-y-4">
          {error && (
            <Alert color="failure" onDismiss={() => setError(null)}>
              {error}
            </Alert>
          )}
          <div>
            <Label htmlFor="hostname" value="Hostname" />
            <TextInput
              id="hostname"
              value={hostname}
              onChange={(e) => setHostname(e.target.value)}
              placeholder="e.g. myserver"
              className="mt-1"
              disabled={saving}
            />
          </div>
          {fullDnsName && (
            <p className="text-sm text-gray-600 dark:text-gray-400">
              Full DNS name: <span className="font-mono text-gray-900 dark:text-white">{fullDnsName}</span>
            </p>
          )}
          {dynamicDomain == null || dynamicDomain === '' ? (
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Dynamic DNS is disabled for this network. The hostname will still be saved and used for the device.
            </p>
          ) : null}
        </div>
      </Modal.Body>
      <Modal.Footer>
        <Button color="blue" onClick={handleSubmit} disabled={saving || !hostname.trim()}>
          {saving ? 'Saving...' : 'Save'}
        </Button>
        <Button color="gray" onClick={onClose} disabled={saving}>
          Cancel
        </Button>
      </Modal.Footer>
    </Modal>
  );
}
