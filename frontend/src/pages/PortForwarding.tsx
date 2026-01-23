/**
 * Port Forwarding Configuration Page
 */
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Button, TextInput, Label, Select, Alert, Table, Modal, Badge } from 'flowbite-react';
import { Sidebar } from '../components/layout/Sidebar';
import { Navbar } from '../components/layout/Navbar';
import { useMetrics } from '../hooks/useMetrics';
import { apiClient } from '../api/client';
import { HiArrowRight, HiPlus, HiPencil, HiTrash } from 'react-icons/hi';
import type { PortForwardingRule, PortForwardingRuleCreate, PortForwardingRuleUpdate } from '../types/port-forwarding';

export function PortForwarding() {
  const token = localStorage.getItem('access_token');
  const username = localStorage.getItem('username') || 'Unknown';
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [rules, setRules] = useState<PortForwardingRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  
  // Modal state
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<PortForwardingRule | null>(null);
  const [proto, setProto] = useState<'both' | 'tcp' | 'udp'>('both');
  const [externalPort, setExternalPort] = useState('');
  const [destination, setDestination] = useState('');
  const [destinationPort, setDestinationPort] = useState('');
  const [saving, setSaving] = useState(false);
  
  // Delete confirmation
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [ruleToDelete, setRuleToDelete] = useState<PortForwardingRule | null>(null);
  
  const { connectionStatus } = useMetrics(token);

  useEffect(() => {
    if (!token) {
      navigate('/login');
      return;
    }
    fetchRules();
  }, [token]);

  const fetchRules = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.getPortForwardingRules();
      setRules(data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load port forwarding rules');
    } finally {
      setLoading(false);
    }
  };

  const openModal = (rule?: PortForwardingRule) => {
    if (rule) {
      setEditingRule(rule);
      setProto(rule.proto);
      setExternalPort(rule.externalPort.toString());
      setDestination(rule.destination);
      setDestinationPort(rule.destinationPort.toString());
    } else {
      setEditingRule(null);
      setProto('both');
      setExternalPort('');
      setDestination('');
      setDestinationPort('');
    }
    setModalOpen(true);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(null);
    
    try {
      if (editingRule) {
        const update: PortForwardingRuleUpdate = {
          proto,
          externalPort: parseInt(externalPort),
          destination,
          destinationPort: parseInt(destinationPort),
        };
        await apiClient.updatePortForwardingRule(editingRule.index, update);
        setSuccess('Port forwarding rule updated successfully');
      } else {
        const create: PortForwardingRuleCreate = {
          proto,
          externalPort: parseInt(externalPort),
          destination,
          destinationPort: parseInt(destinationPort),
        };
        await apiClient.createPortForwardingRule(create);
        setSuccess('Port forwarding rule added successfully');
      }
      setModalOpen(false);
      await fetchRules();
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Failed to save port forwarding rule');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!ruleToDelete) return;
    
    try {
      await apiClient.deletePortForwardingRule(ruleToDelete.index);
      setSuccess('Port forwarding rule deleted successfully');
      setDeleteModalOpen(false);
      setRuleToDelete(null);
      await fetchRules();
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Failed to delete port forwarding rule');
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('username');
    navigate('/login');
  };

  if (loading) {
    return (
      <div className="flex h-screen bg-gray-50 dark:bg-gray-900">
        <Sidebar sidebarOpen={sidebarOpen} setSidebarOpen={setSidebarOpen} />
        <div className="flex-1 flex flex-col overflow-hidden">
          <Navbar username={username} onLogout={handleLogout} onMenuClick={() => setSidebarOpen(!sidebarOpen)} />
          <main className="flex-1 overflow-y-auto p-6">
            <div className="text-center text-gray-600 dark:text-gray-400">Loading...</div>
          </main>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-900">
      <Sidebar sidebarOpen={sidebarOpen} setSidebarOpen={setSidebarOpen} />
      <div className="flex-1 flex flex-col overflow-hidden">
        <Navbar username={username} onLogout={handleLogout} onMenuClick={() => setSidebarOpen(!sidebarOpen)} />
        <main className="flex-1 overflow-y-auto p-6">
          <div className="max-w-6xl mx-auto">
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center">
                <HiArrowRight className="w-8 h-8 mr-3 text-blue-600 dark:text-blue-400" />
                <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Port Forwarding</h1>
              </div>
              <Button onClick={() => openModal()}>
                <HiPlus className="w-5 h-5 mr-2" />
                Add Rule
              </Button>
            </div>

            {error && (
              <Alert color="failure" className="mb-4" onDismiss={() => setError(null)}>
                {error}
              </Alert>
            )}

            {success && (
              <Alert color="success" className="mb-4" onDismiss={() => setSuccess(null)}>
                {success}
              </Alert>
            )}

            <Card>
              {rules.length === 0 ? (
                <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                  No port forwarding rules configured. Click "Add Rule" to create one.
                </div>
              ) : (
                <Table>
                  <Table.Head>
                    <Table.HeadCell>Protocol</Table.HeadCell>
                    <Table.HeadCell>External Port</Table.HeadCell>
                    <Table.HeadCell>Destination</Table.HeadCell>
                    <Table.HeadCell>Destination Port</Table.HeadCell>
                    <Table.HeadCell>Actions</Table.HeadCell>
                  </Table.Head>
                  <Table.Body className="divide-y">
                    {rules.map((rule) => (
                      <Table.Row key={rule.index}>
                        <Table.Cell>
                          <Badge color="blue">{rule.proto.toUpperCase()}</Badge>
                        </Table.Cell>
                        <Table.Cell>{rule.externalPort}</Table.Cell>
                        <Table.Cell>{rule.destination}</Table.Cell>
                        <Table.Cell>{rule.destinationPort}</Table.Cell>
                        <Table.Cell>
                          <div className="flex space-x-2">
                            <Button size="xs" onClick={() => openModal(rule)}>
                              <HiPencil className="w-4 h-4" />
                            </Button>
                            <Button size="xs" color="failure" onClick={() => {
                              setRuleToDelete(rule);
                              setDeleteModalOpen(true);
                            }}>
                              <HiTrash className="w-4 h-4" />
                            </Button>
                          </div>
                        </Table.Cell>
                      </Table.Row>
                    ))}
                  </Table.Body>
                </Table>
              )}
            </Card>
          </div>
        </main>
      </div>

      {/* Add/Edit Modal */}
      <Modal show={modalOpen} onClose={() => setModalOpen(false)}>
        <Modal.Header>{editingRule ? 'Edit Port Forwarding Rule' : 'Add Port Forwarding Rule'}</Modal.Header>
        <Modal.Body>
          <div className="space-y-4">
            <div>
              <Label htmlFor="proto">Protocol</Label>
              <Select id="proto" value={proto} onChange={(e) => setProto(e.target.value as any)}>
                <option value="both">Both (TCP & UDP)</option>
                <option value="tcp">TCP</option>
                <option value="udp">UDP</option>
              </Select>
            </div>
            <div>
              <Label htmlFor="externalPort">External Port</Label>
              <TextInput
                id="externalPort"
                type="number"
                value={externalPort}
                onChange={(e) => setExternalPort(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="destination">Destination IP</Label>
              <TextInput
                id="destination"
                type="text"
                value={destination}
                onChange={(e) => setDestination(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="destinationPort">Destination Port</Label>
              <TextInput
                id="destinationPort"
                type="number"
                value={destinationPort}
                onChange={(e) => setDestinationPort(e.target.value)}
              />
            </div>
          </div>
        </Modal.Body>
        <Modal.Footer>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? 'Saving...' : 'Save'}
          </Button>
          <Button color="gray" onClick={() => setModalOpen(false)}>
            Cancel
          </Button>
        </Modal.Footer>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal show={deleteModalOpen} onClose={() => setDeleteModalOpen(false)} size="md">
        <Modal.Header>Delete Port Forwarding Rule</Modal.Header>
        <Modal.Body>
          <p>Are you sure you want to delete this port forwarding rule?</p>
          {ruleToDelete && (
            <div className="mt-4 p-3 bg-gray-100 dark:bg-gray-800 rounded">
              <p><strong>Protocol:</strong> {ruleToDelete.proto.toUpperCase()}</p>
              <p><strong>External Port:</strong> {ruleToDelete.externalPort}</p>
              <p><strong>Destination:</strong> {ruleToDelete.destination}:{ruleToDelete.destinationPort}</p>
            </div>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button color="failure" onClick={handleDelete}>
            Delete
          </Button>
          <Button color="gray" onClick={() => setDeleteModalOpen(false)}>
            Cancel
          </Button>
        </Modal.Footer>
      </Modal>
    </div>
  );
}
