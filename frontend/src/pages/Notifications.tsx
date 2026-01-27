import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Label,
  Modal,
  Select,
  Spinner,
  Table,
  TextInput,
  Textarea,
  ToggleSwitch,
} from 'flowbite-react';
import { HiCheckCircle, HiXCircle, HiInformationCircle } from 'react-icons/hi';
import { Sidebar } from '../components/layout/Sidebar';
import { Navbar } from '../components/layout/Navbar';
import { useMetrics } from '../hooks/useMetrics';
import { apiClient } from '../api/client';
import type {
  NotificationRule,
  NotificationParameterMetadata,
  NotificationHistoryRecord,
  NotificationRuleCreate,
  ComparisonOperator,
  AppriseServiceInfo,
} from '../types/notifications';
import type { AppriseConfig } from '../types/apprise-config';
import { AppriseUrlGenerator } from '../components/AppriseUrlGenerator';

interface NotificationRuleFormState {
  id?: number;
  name: string;
  enabled: boolean;
  parameter_type: string;
  parameter_config: Record<string, string>;
  threshold_info: string;
  threshold_warning: string;
  threshold_failure: string;
  comparison_operator: ComparisonOperator;
  duration_seconds: number;
  cooldown_seconds: number;
  apprise_service_indices: number[];
  message_template: string;
}

interface HistoryModalState {
  open: boolean;
  items: NotificationHistoryRecord[];
  ruleName: string;
}

const DEFAULT_TEMPLATE = '{{ parameter_name }} is {{ current_value }} ({{ current_level | upper }})';

const emptyForm: NotificationRuleFormState = {
  name: '',
  enabled: true,
  parameter_type: '',
  parameter_config: {},
  threshold_info: '',
  threshold_warning: '',
  threshold_failure: '',
  comparison_operator: 'gt',
  duration_seconds: 60,
  cooldown_seconds: 300,
  apprise_service_indices: [],
  message_template: DEFAULT_TEMPLATE,
};

// Parameter categories for wizard
interface ParameterCategory {
  id: string;
  label: string;
  paramType?: string;
  subOptions?: string[];
  requiresSubSelection?: boolean;
}

const PARAMETER_CATEGORIES: ParameterCategory[] = [
  { id: 'cpu', label: 'CPU Usage', paramType: 'cpu_percent' },
  { id: 'memory', label: 'Memory Usage', paramType: 'memory_percent' },
  { id: 'load', label: 'Load Average', subOptions: ['1m', '5m', '15m'] },
  { id: 'bandwidth', label: 'Bandwidth Usage', requiresSubSelection: true },
  { id: 'temperature', label: 'Temperature', requiresSubSelection: true },
  { id: 'service', label: 'Service Status', requiresSubSelection: true },
  { id: 'speedtest', label: 'Speedtest', subOptions: ['download', 'upload', 'ping'] },
];

// Map wizard selections to parameter types
const getParameterType = (category: string, subSelection: Record<string, string>): string => {
  switch (category) {
    case 'cpu':
      return 'cpu_percent';
    case 'memory':
      return 'memory_percent';
    case 'load':
      const period = subSelection.loadPeriod;
      if (period === '1m') return 'load_avg_1m';
      if (period === '5m') return 'load_avg_5m';
      if (period === '15m') return 'load_avg_15m';
      return 'load_avg_1m';
    case 'bandwidth':
      const direction = subSelection.bandwidthDirection;
      if (direction === 'download') return 'interface_rx_bytes';
      if (direction === 'upload') return 'interface_tx_bytes';
      return 'interface_rx_bytes';
    case 'temperature':
      return 'temperature_c';
    case 'service':
      return 'service_status';
    case 'speedtest':
      const speedtestType = subSelection.speedtestType;
      if (speedtestType === 'download') return 'speedtest_download';
      if (speedtestType === 'upload') return 'speedtest_upload';
      if (speedtestType === 'ping') return 'speedtest_ping';
      return 'speedtest_download';
    default:
      return '';
  }
};

export function Notifications() {
  const token = localStorage.getItem('access_token');
  const username = localStorage.getItem('username') || 'Unknown';
  const { connectionStatus } = useMetrics(token);
  const navigate = useNavigate();

  const [rules, setRules] = useState<NotificationRule[]>([]);
  const [parameters, setParameters] = useState<NotificationParameterMetadata[]>([]);
  const [services, setServices] = useState<AppriseServiceInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [historyState, setHistoryState] = useState<HistoryModalState>({
    open: false,
    items: [],
    ruleName: '',
  });
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [formState, setFormState] = useState<NotificationRuleFormState>(emptyForm);
  const [formError, setFormError] = useState<string | null>(null);
  const [formSuccess, setFormSuccess] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);
  
  // Wizard state
  const [wizardStep, setWizardStep] = useState(0);
  const [wizardParameterCategory, setWizardParameterCategory] = useState<string | null>(null);
  const [wizardSubSelection, setWizardSubSelection] = useState<Record<string, string>>({});
  const [testNotificationResult, setTestNotificationResult] = useState<{ success: boolean; message: string } | null>(null);
  const [testingNotification, setTestingNotification] = useState(false);
  
  // Apprise service management state
  const [appriseServices, setAppriseServices] = useState<AppriseServiceInfo[]>([]);
  const [appriseEnabled, setAppriseEnabled] = useState(false);
  const [urlGeneratorModalOpen, setUrlGeneratorModalOpen] = useState(false);
  
  // Apprise notification form state
  const [notificationBody, setNotificationBody] = useState('');
  const [notificationTitle, setNotificationTitle] = useState('');
  const [notificationType, setNotificationType] = useState('info');
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState<{ success: boolean; message: string } | null>(null);
  
  // Send notification state - track status per service (using service names as keys)
  const [sendingServices, setSendingServices] = useState<Set<string>>(new Set());
  const [sendResults, setSendResults] = useState<Map<string, { success: boolean; message: string; details?: string }>>(new Map());

  const formatServiceName = (name: string): string => {
    const nameMap: Record<string, string> = {
      'homeAssistant': 'Home Assistant',
      'telegram': 'Telegram',
      'discord': 'Discord',
      'slack': 'Slack',
      'email': 'Email',
      'ntfy': 'ntfy'
    };
    return nameMap[name] || name.charAt(0).toUpperCase() + name.slice(1);
  };

  const transformConfigServices = (config: AppriseConfig): Array<AppriseServiceInfo & { id: string; originalName: string }> => {
    return Object.entries(config.services || {})
      .filter(([_, service]) => service.enable === true)
      .map(([name, service]) => ({
        id: name, // Use service name as ID (string) - stored separately from numeric id
        name: formatServiceName(name),
        description: null,
        enabled: service.enable,
        originalName: name // Store original name for API calls
      } as AppriseServiceInfo & { id: string; originalName: string }));
  };

  useEffect(() => {
    const bootstrap = async () => {
      try {
        setLoading(true);
        const [rulesData, paramsData, configData] = await Promise.all([
          apiClient.getNotificationRules(),
          apiClient.getNotificationParameters(),
          apiClient.getAppriseConfig(),
        ]);
        setRules(rulesData);
        setParameters(paramsData);
        const servicesList = transformConfigServices(configData);
        setServices(servicesList as any); // Cast to any since we're using string IDs for config services
      } catch (err: any) {
        setError(err?.response?.data?.detail || err.message || 'Failed to load notifications');
      } finally {
        setLoading(false);
      }
    };

    bootstrap();
    fetchAppriseStatus();
  }, []);

  const fetchAppriseStatus = async () => {
    try {
      const status = await apiClient.getAppriseStatus();
      setAppriseEnabled(status.enabled);
      
      const config = await apiClient.getAppriseConfig();
      const servicesList = transformConfigServices(config);
      setAppriseServices(servicesList);
    } catch (err: any) {
      setAppriseEnabled(false);
    }
  };


  // Wizard helper functions
  const getTotalSteps = (): number => {
    let steps = 5; // Base: category, thresholds, timing, template, test
    if (!wizardParameterCategory) return steps;
    
    if (wizardParameterCategory === 'load' || wizardParameterCategory === 'speedtest') {
      steps += 1; // Add sub-selection step
    }
    if (wizardParameterCategory === 'bandwidth') {
      steps += 2; // Interface + direction
    }
    if (wizardParameterCategory === 'temperature') {
      steps += 1; // Sensor selection
    }
    if (wizardParameterCategory === 'service') {
      steps += 2; // Service + state type
    }
    return steps;
  };

  const validateStep = (step: number): boolean => {
    // Step 0: Parameter category selection
    if (step === 0) {
      return wizardParameterCategory !== null;
    }
    
    if (!wizardParameterCategory) return false;
    
    // Calculate step offsets based on category
    let subSelectionSteps = 0;
    if (wizardParameterCategory === 'load' || wizardParameterCategory === 'speedtest' || 
        wizardParameterCategory === 'temperature') {
      subSelectionSteps = 1;
    } else if (wizardParameterCategory === 'bandwidth' || wizardParameterCategory === 'service') {
      subSelectionSteps = 2;
    }
    
    // Step 1: First sub-selection
    if (step === 1 && subSelectionSteps >= 1) {
      if (wizardParameterCategory === 'load') {
        return wizardSubSelection.loadPeriod !== undefined;
      }
      if (wizardParameterCategory === 'speedtest') {
        return wizardSubSelection.speedtestType !== undefined;
      }
      if (wizardParameterCategory === 'bandwidth') {
        return wizardSubSelection.bandwidthInterface !== undefined && wizardSubSelection.bandwidthInterface !== '';
      }
      if (wizardParameterCategory === 'temperature') {
        return wizardSubSelection.temperatureSensor !== undefined && wizardSubSelection.temperatureSensor !== '';
      }
      if (wizardParameterCategory === 'service') {
        return wizardSubSelection.serviceName !== undefined && wizardSubSelection.serviceName !== '';
      }
    }
    
    // Step 2: Second sub-selection (bandwidth/service only)
    if (step === 2 && subSelectionSteps === 2) {
      if (wizardParameterCategory === 'bandwidth') {
        return wizardSubSelection.bandwidthDirection !== undefined;
      }
      if (wizardParameterCategory === 'service') {
        return wizardSubSelection.serviceStateType !== undefined;
      }
    }
    
    // Thresholds step
    const thresholdsStep = subSelectionSteps + 1;
    if (step === thresholdsStep) {
      return formState.threshold_info !== '' || formState.threshold_warning !== '' || formState.threshold_failure !== '';
    }
    
    // Timing and Services step
    const timingStep = thresholdsStep + 1;
    if (step === timingStep) {
      return formState.apprise_service_indices.length > 0 && 
             formState.duration_seconds > 0 && 
             formState.cooldown_seconds >= 0;
    }
    
    // Template and Name step
    const templateStep = timingStep + 1;
    if (step === templateStep) {
      return formState.name.trim() !== '' && formState.message_template.trim() !== '';
    }
    
    // Final step: Test (always valid, optional)
    return true;
  };

  const openCreateModal = () => {
    setFormState(emptyForm);
    setFormError(null);
    setFormSuccess(null);
    setTestResult(null);
    setWizardStep(0);
    setWizardParameterCategory(null);
    setWizardSubSelection({});
    setTestNotificationResult(null);
    setFormOpen(true);
  };

  const handleLogout = async () => {
    await apiClient.logout();
    navigate('/login');
  };

  // Map parameter type back to wizard category and sub-selections
  const mapParameterTypeToWizard = (paramType: string, config: Record<string, any>, comparisonOp?: string, thresholdFailure?: string | number | null): { category: string; subSelection: Record<string, string> } => {
    const subSelection: Record<string, string> = {};
    let category = '';
    
    if (paramType === 'cpu_percent') {
      category = 'cpu';
    } else if (paramType === 'memory_percent') {
      category = 'memory';
    } else if (paramType.startsWith('load_avg_')) {
      category = 'load';
      const period = paramType.replace('load_avg_', '');
      subSelection.loadPeriod = period === '1m' ? '1m' : period === '5m' ? '5m' : '15m';
    } else if (paramType === 'interface_rx_bytes' || paramType === 'interface_tx_bytes') {
      category = 'bandwidth';
      subSelection.bandwidthInterface = config.interface || '';
      subSelection.bandwidthDirection = paramType === 'interface_rx_bytes' ? 'download' : 'upload';
    } else if (paramType === 'temperature_c') {
      category = 'temperature';
      subSelection.temperatureSensor = config.sensor_name || '';
    } else if (paramType === 'service_status') {
      category = 'service';
      subSelection.serviceName = config.service_name || '';
      // Determine state type from thresholds and comparison
      if (comparisonOp === 'gt' && thresholdFailure && Number(thresholdFailure) > 0) {
        subSelection.serviceStateType = 'up';
      } else if (comparisonOp === 'lt' && thresholdFailure && Number(thresholdFailure) < 1) {
        subSelection.serviceStateType = 'down';
      } else {
        subSelection.serviceStateType = 'change';
      }
    } else if (paramType.startsWith('speedtest_')) {
      category = 'speedtest';
      const type = paramType.replace('speedtest_', '');
      subSelection.speedtestType = type;
    }
    
    return { category, subSelection };
  };

  const openEditModal = (rule: NotificationRule) => {
    const { category, subSelection } = mapParameterTypeToWizard(
      rule.parameter_type, 
      rule.parameter_config || {},
      rule.comparison_operator,
      rule.threshold_failure
    );
    
    setFormState({
      id: rule.id,
      name: rule.name,
      enabled: rule.enabled,
      parameter_type: rule.parameter_type,
      parameter_config: Object.fromEntries(
        Object.entries(rule.parameter_config || {}).map(([key, value]) => [key, String(value ?? '')])
      ),
      threshold_info: rule.threshold_info !== null && rule.threshold_info !== undefined ? String(rule.threshold_info) : '',
      threshold_warning:
        rule.threshold_warning !== null && rule.threshold_warning !== undefined
          ? String(rule.threshold_warning)
          : '',
      threshold_failure:
        rule.threshold_failure !== null && rule.threshold_failure !== undefined
          ? String(rule.threshold_failure)
          : '',
      comparison_operator: rule.comparison_operator,
      duration_seconds: rule.duration_seconds,
      cooldown_seconds: rule.cooldown_seconds,
      apprise_service_indices: [...(rule.apprise_service_indices || [])],
      message_template: rule.message_template || DEFAULT_TEMPLATE,
    });
    setWizardStep(0);
    setWizardParameterCategory(category);
    setWizardSubSelection(subSelection);
    setTestNotificationResult(null);
    setFormError(null);
    setFormSuccess(null);
    setTestResult(null);
    setFormOpen(true);
  };

  const closeForm = () => {
    setFormOpen(false);
    setFormState(emptyForm);
    setFormError(null);
    setFormSuccess(null);
    setTestResult(null);
    setWizardStep(0);
    setWizardParameterCategory(null);
    setWizardSubSelection({});
    setTestNotificationResult(null);
  };

  const handleWizardNext = () => {
    if (validateStep(wizardStep)) {
      // Update formState.parameter_type when moving from category selection or completing sub-selections
      if (wizardParameterCategory) {
        // For categories without sub-selection (CPU, Memory), set immediately after category selection
        if ((wizardStep === 0 && (wizardParameterCategory === 'cpu' || wizardParameterCategory === 'memory')) ||
            // For categories with sub-selection, set after sub-selection is complete
            (wizardStep >= 1 && (wizardParameterCategory === 'load' || wizardParameterCategory === 'speedtest' || 
                                wizardParameterCategory === 'temperature' || 
                                (wizardParameterCategory === 'bandwidth' && wizardStep >= 2) ||
                                (wizardParameterCategory === 'service' && wizardStep >= 2)))) {
          const paramType = getParameterType(wizardParameterCategory, wizardSubSelection);
          if (paramType) {
            setFormState(prev => ({ ...prev, parameter_type: paramType }));
            
            // Set parameter_config based on selections
            const config: Record<string, string> = {};
            if (wizardParameterCategory === 'bandwidth' && wizardSubSelection.bandwidthInterface) {
              config.interface = wizardSubSelection.bandwidthInterface;
            }
            if (wizardParameterCategory === 'temperature' && wizardSubSelection.temperatureSensor) {
              config.sensor_name = wizardSubSelection.temperatureSensor;
            }
            if (wizardParameterCategory === 'service' && wizardSubSelection.serviceName) {
              config.service_name = wizardSubSelection.serviceName;
              // Set thresholds based on state type
              if (wizardSubSelection.serviceStateType === 'up') {
                setFormState(prev => ({ 
                  ...prev, 
                  comparison_operator: 'gt',
                  threshold_failure: '1',
                  threshold_warning: '',
                  threshold_info: ''
                }));
              } else if (wizardSubSelection.serviceStateType === 'down') {
                setFormState(prev => ({ 
                  ...prev, 
                  comparison_operator: 'lt',
                  threshold_failure: '0',
                  threshold_warning: '',
                  threshold_info: ''
                }));
              }
            }
            if (Object.keys(config).length > 0) {
              setFormState(prev => ({ ...prev, parameter_config: config }));
            }
          }
        }
      }
      
      const totalSteps = getTotalSteps();
      if (wizardStep < totalSteps - 1) {
        setWizardStep(wizardStep + 1);
      }
    }
  };

  const handleWizardPrev = () => {
    if (wizardStep > 0) {
      setWizardStep(wizardStep - 1);
    }
  };

  const handleInputChange = (field: keyof NotificationRuleFormState, value: string | number | boolean) => {
    setFormState((prev) => ({
      ...prev,
      [field]: value,
    }));
  };


  const handleServiceToggle = (serviceName: string) => {
    // For config services, map service name to its index in appriseServices array
    const serviceIndex = appriseServices.findIndex(s => {
      const id = (s as any).id;
      return id === serviceName || id?.toString() === serviceName || s.id?.toString() === serviceName;
    });
    if (serviceIndex === -1) return;
    
    setFormState((prev) => {
      const exists = prev.apprise_service_indices.includes(serviceIndex);
      const updated = exists
        ? prev.apprise_service_indices.filter((id) => id !== serviceIndex)
        : [...prev.apprise_service_indices, serviceIndex].sort((a, b) => a - b);
      return { ...prev, apprise_service_indices: updated };
    });
  };

  const toNumberOrUndefined = (value: string) => {
    if (value === '' || value === null || value === undefined) return undefined;
    const parsed = Number(value);
    return Number.isNaN(parsed) ? undefined : parsed;
  };

  const refreshRules = async () => {
    const data = await apiClient.getNotificationRules();
    setRules(data);
  };

  const handleSubmit = async () => {
    setFormError(null);
    setFormSuccess(null);

    // Ensure parameter type is resolved from wizard state
    if (!formState.parameter_type && wizardParameterCategory) {
      const paramType = getParameterType(wizardParameterCategory, wizardSubSelection);
      if (paramType) {
        setFormState(prev => ({ ...prev, parameter_type: paramType }));
        
        // Set parameter_config
        const config: Record<string, string> = {};
        if (wizardParameterCategory === 'bandwidth' && wizardSubSelection.bandwidthInterface) {
          config.interface = wizardSubSelection.bandwidthInterface;
        }
        if (wizardParameterCategory === 'temperature' && wizardSubSelection.temperatureSensor) {
          config.sensor_name = wizardSubSelection.temperatureSensor;
        }
        if (wizardParameterCategory === 'service' && wizardSubSelection.serviceName) {
          config.service_name = wizardSubSelection.serviceName;
        }
        if (Object.keys(config).length > 0) {
          setFormState(prev => ({ ...prev, parameter_config: config }));
        }
      }
    }

    if (!formState.parameter_type) {
      setFormError('Please select a parameter to monitor.');
      return;
    }

    const payload: NotificationRuleCreate = {
      name: formState.name,
      enabled: formState.enabled,
      parameter_type: formState.parameter_type,
      parameter_config: formState.parameter_config,
      threshold_info: toNumberOrUndefined(formState.threshold_info),
      threshold_warning: toNumberOrUndefined(formState.threshold_warning),
      threshold_failure: toNumberOrUndefined(formState.threshold_failure),
      comparison_operator: formState.comparison_operator,
      duration_seconds: formState.duration_seconds,
      cooldown_seconds: formState.cooldown_seconds,
      apprise_service_indices: formState.apprise_service_indices,
      message_template: formState.message_template || DEFAULT_TEMPLATE,
    };

    try {
      if (formState.id) {
        await apiClient.updateNotificationRule(formState.id, payload);
        setFormSuccess('Notification rule updated.');
      } else {
        await apiClient.createNotificationRule(payload);
        setFormSuccess('Notification rule created.');
      }
      await refreshRules();
      setTimeout(closeForm, 600);
    } catch (err: any) {
      setFormError(err?.response?.data?.detail || err.message || 'Failed to save notification rule');
    }
  };

  const handleToggleEnabled = async (rule: NotificationRule) => {
    await apiClient.updateNotificationRule(rule.id, { enabled: !rule.enabled });
    await refreshRules();
  };

  const handleDelete = async (rule: NotificationRule) => {
    if (!window.confirm(`Delete notification "${rule.name}"? This cannot be undone.`)) {
      return;
    }
    await apiClient.deleteNotificationRule(rule.id);
    await refreshRules();
  };

  const handleTest = async (rule: NotificationRule) => {
    setTestResult(null);
    try {
      const result = await apiClient.testNotificationRule(rule.id);
      if (result.success) {
        setTestResult(`Test sent (${result.level.toUpperCase()}): ${result.message}`);
      } else {
        setTestResult(result.error || 'Test failed to send');
      }
    } catch (err: any) {
      setTestResult(err?.response?.data?.detail || err.message || 'Test failed');
    }
  };

  const openHistory = async (rule: NotificationRule) => {
    try {
      const history = await apiClient.getNotificationHistory(rule.id);
      setHistoryState({
        open: true,
        items: history.items,
        ruleName: rule.name,
      });
    } catch (err: any) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load history');
    }
  };

  const formatTimestamp = (value?: string | null) => {
    if (!value) return '—';
    return new Date(value).toLocaleString();
  };

  // Apprise functions
  const handleSendNotification = async () => {
    if (!notificationBody.trim()) {
      setSendResult({ success: false, message: 'Message body is required' });
      return;
    }

    setSending(true);
    setSendResult(null);
    
    try {
      const result = await apiClient.sendAppriseNotification(
        notificationBody,
        notificationTitle || undefined,
        notificationType || undefined
      );
      setSendResult(result);
      if (result.success) {
        setNotificationBody('');
        setNotificationTitle('');
        setNotificationType('info');
      }
    } catch (err: any) {
      setSendResult({
        success: false,
        message: err.response?.data?.detail || err.message || 'Failed to send notification',
      });
    } finally {
      setSending(false);
    }
  };

  const handleSendToService = async (serviceName: string) => {
    if (!notificationBody.trim()) {
      setSendResults(prev => new Map(prev).set(serviceName, { success: false, message: 'Message body is required' }));
      return;
    }

    setSendingServices(prev => new Set(prev).add(serviceName));
    setSendResults(prev => {
      const newMap = new Map(prev);
      newMap.delete(serviceName);
      return newMap;
    });
    
    // Note: Config services don't have a direct send-by-name endpoint
    // For now, we'll use the general send endpoint which sends to all enabled services
    // In the future, this could be enhanced to support sending to specific config services
    try {
      const result = await apiClient.sendAppriseNotification(
        notificationBody,
        notificationTitle || undefined,
        notificationType || undefined
      );
      setSendResults(prev => new Map(prev).set(serviceName, result));
      
      if (!result.success) {
        const errorMsg = result.details 
          ? `${result.message}: ${result.details}`
          : result.message;
        setSendResults(prev => new Map(prev).set(serviceName, { success: false, message: errorMsg, details: result.details }));
      }
    } catch (err: any) {
      const errorMsg = err.response?.data?.detail || err.message || 'Failed to send notification';
      setSendResults(prev => new Map(prev).set(serviceName, {
        success: false,
        message: errorMsg,
      }));
    } finally {
      setSendingServices(prev => {
        const newSet = new Set(prev);
        newSet.delete(serviceName);
        return newSet;
      });
    }
  };

  const handleTestService = async (serviceName: string) => {
    setSendingServices(prev => new Set(prev).add(serviceName));
    try {
      const result = await apiClient.testAppriseServiceByName(serviceName);
      setSendResults(prev => new Map(prev).set(serviceName, result));
      if (!result.success) {
        setSendResults(prev => new Map(prev).set(serviceName, { success: false, message: result.message, details: result.details }));
      }
    } catch (err: any) {
      setSendResults(prev => new Map(prev).set(serviceName, { success: false, message: err.response?.data?.detail || err.message }));
    } finally {
      setSendingServices(prev => {
        const newSet = new Set(prev);
        newSet.delete(serviceName);
        return newSet;
      });
    }
  };


  // Available interfaces for bandwidth selection
  const availableInterfaces = ['br0', 'br1', 'ppp0', 'eth0', 'eth1', 'wlan0'];
  
  // Available services for service status (from MONITORED_SERVICES)
  const availableServices = [
    'dnsmasq-homelab',
    'dnsmasq-lan',
    'pppd-eno1',
    'linode-dyndns',
    'nginx',
    'router-webui-backend',
    'postgresql',
    'speedtest'
  ];

  // Step rendering functions
  const renderStepContent = () => {
    const totalSteps = getTotalSteps();
    
    // Step 0: Parameter Category Selection
    if (wizardStep === 0) {
      return (
        <div className="space-y-4">
          <h3 className="text-lg font-semibold">Select Parameter Type</h3>
          <p className="text-sm text-gray-600 dark:text-gray-400">
            Choose what you want to monitor for notifications
          </p>
          <div className="grid gap-4 md:grid-cols-2">
            {PARAMETER_CATEGORIES.map((category) => (
              <Card
                key={category.id}
                className={`cursor-pointer transition-all ${
                  wizardParameterCategory === category.id
                    ? 'ring-2 ring-blue-500 bg-blue-50 dark:bg-blue-900/20'
                    : 'hover:bg-gray-50 dark:hover:bg-gray-800'
                }`}
                onClick={() => setWizardParameterCategory(category.id)}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium">{category.label}</span>
                  {wizardParameterCategory === category.id && (
                    <HiCheckCircle className="w-5 h-5 text-blue-500" />
                  )}
                </div>
              </Card>
            ))}
          </div>
        </div>
      );
    }
    
    // Step 1: Sub-selection for Load Avg, Speedtest
    if (wizardStep === 1 && (wizardParameterCategory === 'load' || wizardParameterCategory === 'speedtest')) {
      const options = wizardParameterCategory === 'load' 
        ? ['1m', '5m', '15m']
        : ['download', 'upload', 'ping'];
      const key = wizardParameterCategory === 'load' ? 'loadPeriod' : 'speedtestType';
      const labels = wizardParameterCategory === 'load'
        ? { '1m': '1 Minute', '5m': '5 Minutes', '15m': '15 Minutes' }
        : { 'download': 'Download', 'upload': 'Upload', 'ping': 'Ping' };
      
      return (
        <div className="space-y-4">
          <h3 className="text-lg font-semibold">
            {wizardParameterCategory === 'load' ? 'Select Load Average Period' : 'Select Speedtest Metric'}
          </h3>
          <div className="space-y-2">
            {options.map((option) => (
              <label
                key={option}
                className={`flex items-center gap-3 p-4 border rounded-lg cursor-pointer transition-all ${
                  wizardSubSelection[key] === option
                    ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                    : 'border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800'
                }`}
              >
                <input
                  type="radio"
                  name={key}
                  value={option}
                  checked={wizardSubSelection[key] === option}
                  onChange={(e) => setWizardSubSelection(prev => ({ ...prev, [key]: e.target.value }))}
                  className="w-4 h-4 text-blue-600"
                />
                <span className="font-medium">{labels[option as keyof typeof labels] || option}</span>
              </label>
            ))}
          </div>
        </div>
      );
    }
    
    // Step 1: Interface selection for Bandwidth
    if (wizardStep === 1 && wizardParameterCategory === 'bandwidth') {
      return (
        <div className="space-y-4">
          <h3 className="text-lg font-semibold">Select Network Interface</h3>
          <Select
            value={wizardSubSelection.bandwidthInterface || ''}
            onChange={(e) => setWizardSubSelection(prev => ({ ...prev, bandwidthInterface: e.target.value }))}
          >
            <option value="">Select interface...</option>
            {availableInterfaces.map((iface) => (
              <option key={iface} value={iface}>
                {iface}
              </option>
            ))}
          </Select>
        </div>
      );
    }
    
    // Step 2: Direction selection for Bandwidth
    if (wizardStep === 2 && wizardParameterCategory === 'bandwidth') {
      return (
        <div className="space-y-4">
          <h3 className="text-lg font-semibold">Select Direction</h3>
          <div className="space-y-2">
            {['download', 'upload'].map((direction) => (
              <label
                key={direction}
                className={`flex items-center gap-3 p-4 border rounded-lg cursor-pointer transition-all ${
                  wizardSubSelection.bandwidthDirection === direction
                    ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                    : 'border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800'
                }`}
              >
                <input
                  type="radio"
                  name="bandwidthDirection"
                  value={direction}
                  checked={wizardSubSelection.bandwidthDirection === direction}
                  onChange={(e) => setWizardSubSelection(prev => ({ ...prev, bandwidthDirection: e.target.value }))}
                  className="w-4 h-4 text-blue-600"
                />
                <span className="font-medium capitalize">{direction}</span>
              </label>
            ))}
          </div>
        </div>
      );
    }
    
    // Step 1: Sensor selection for Temperature
    if (wizardStep === 1 && wizardParameterCategory === 'temperature') {
      return (
        <div className="space-y-4">
          <h3 className="text-lg font-semibold">Select Temperature Sensor</h3>
          <TextInput
            value={wizardSubSelection.temperatureSensor || ''}
            onChange={(e) => setWizardSubSelection(prev => ({ ...prev, temperatureSensor: e.target.value }))}
            placeholder="e.g., cpu_thermal, nvme0"
          />
          <p className="text-xs text-gray-500">Enter the sensor name to monitor</p>
        </div>
      );
    }
    
    // Step 1: Service selection for Service Status
    if (wizardStep === 1 && wizardParameterCategory === 'service') {
      return (
        <div className="space-y-4">
          <h3 className="text-lg font-semibold">Select Service</h3>
          <Select
            value={wizardSubSelection.serviceName || ''}
            onChange={(e) => setWizardSubSelection(prev => ({ ...prev, serviceName: e.target.value }))}
          >
            <option value="">Select service...</option>
            {availableServices.map((service) => (
              <option key={service} value={service}>
                {service}
              </option>
            ))}
          </Select>
        </div>
      );
    }
    
    // Step 2: State type selection for Service Status
    if (wizardStep === 2 && wizardParameterCategory === 'service') {
      return (
        <div className="space-y-4">
          <h3 className="text-lg font-semibold">Select Notification Trigger</h3>
          <div className="space-y-2">
            {[
              { value: 'change', label: 'Change of State', desc: 'Notify on any state change' },
              { value: 'up', label: 'Service Up', desc: 'Notify when service becomes active' },
              { value: 'down', label: 'Service Down', desc: 'Notify when service becomes inactive or fails' }
            ].map((option) => (
              <label
                key={option.value}
                className={`flex items-start gap-3 p-4 border rounded-lg cursor-pointer transition-all ${
                  wizardSubSelection.serviceStateType === option.value
                    ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                    : 'border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800'
                }`}
              >
                <input
                  type="radio"
                  name="serviceStateType"
                  value={option.value}
                  checked={wizardSubSelection.serviceStateType === option.value}
                  onChange={(e) => setWizardSubSelection(prev => ({ ...prev, serviceStateType: e.target.value }))}
                  className="w-4 h-4 text-blue-600 mt-1"
                />
                <div>
                  <span className="font-medium block">{option.label}</span>
                  <span className="text-xs text-gray-500">{option.desc}</span>
                </div>
              </label>
            ))}
          </div>
        </div>
      );
    }
    
    // Calculate which step we're on for thresholds/timing/template
    let stepOffset = 1;
    if (wizardParameterCategory === 'load' || wizardParameterCategory === 'speedtest' || 
        wizardParameterCategory === 'temperature') {
      stepOffset = 2;
    } else if (wizardParameterCategory === 'bandwidth' || wizardParameterCategory === 'service') {
      stepOffset = 3;
    }
    
    // Thresholds step
    if (wizardStep === stepOffset) {
      return (
        <div className="space-y-4">
          <h3 className="text-lg font-semibold">Set Thresholds</h3>
          <div>
            <Label value="Comparison Operator" />
            <Select
              value={formState.comparison_operator}
              onChange={(e) => handleInputChange('comparison_operator', e.target.value as ComparisonOperator)}
            >
              <option value="gt">Greater than (&gt;=)</option>
              <option value="lt">Less than (&lt;=)</option>
            </Select>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <div>
              <Label value="Info threshold (optional)" />
              <TextInput
                type="number"
                value={formState.threshold_info}
                onChange={(e) => handleInputChange('threshold_info', e.target.value)}
                placeholder="Optional"
              />
            </div>
            <div>
              <Label value="Warning threshold (optional)" />
              <TextInput
                type="number"
                value={formState.threshold_warning}
                onChange={(e) => handleInputChange('threshold_warning', e.target.value)}
                placeholder="Optional"
              />
            </div>
            <div>
              <Label value="Failure threshold (optional)" />
              <TextInput
                type="number"
                value={formState.threshold_failure}
                onChange={(e) => handleInputChange('threshold_failure', e.target.value)}
                placeholder="Optional"
              />
            </div>
          </div>
          <p className="text-xs text-gray-500">
            At least one threshold must be set. Lower severity thresholds are checked first.
          </p>
        </div>
      );
    }
    
    // Timing and Services step
    if (wizardStep === stepOffset + 1) {
      return (
        <div className="space-y-4">
          <h3 className="text-lg font-semibold">Timing and Notification Services</h3>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <Label value="Duration (seconds)" />
              <TextInput
                type="number"
                min={5}
                value={formState.duration_seconds}
                onChange={(e) => handleInputChange('duration_seconds', Number(e.target.value))}
              />
              <p className="text-xs text-gray-500 mt-1">How long the condition must persist</p>
            </div>
            <div>
              <Label value="Cooldown (seconds)" />
              <TextInput
                type="number"
                min={0}
                value={formState.cooldown_seconds}
                onChange={(e) => handleInputChange('cooldown_seconds', Number(e.target.value))}
              />
              <p className="text-xs text-gray-500 mt-1">Wait time between notifications</p>
            </div>
          </div>
          <div>
            <Label value="Notification Services" />
            {services.length === 0 ? (
              <p className="text-xs text-gray-500">No Apprise services configured.</p>
            ) : (
              <div className="grid gap-2 md:grid-cols-2 mt-2">
                {services.map((service, index) => (
                  <label key={service.id} className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={formState.apprise_service_indices.includes(index)}
                      onChange={() => handleServiceToggle((service as any).id || service.id.toString())}
                    />
                    <span className="font-semibold">{service.name}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>
      );
    }
    
    // Template and Name step
    if (wizardStep === stepOffset + 2) {
      const selectedParam = parameters.find(p => p.type === formState.parameter_type);
      return (
        <div className="space-y-4">
          <h3 className="text-lg font-semibold">Rule Name and Message Template</h3>
          <div>
            <Label value="Rule Name" />
            <TextInput
              value={formState.name}
              onChange={(e) => handleInputChange('name', e.target.value)}
              placeholder="e.g., CPU usage alerts"
            />
          </div>
          <div className="flex items-center gap-2">
            <ToggleSwitch
              checked={formState.enabled}
              onChange={(checked) => handleInputChange('enabled', checked)}
            />
            <Label value="Enabled" />
          </div>
          <div>
            <Label value="Message Template" />
            <Textarea
              rows={4}
              value={formState.message_template}
              onChange={(e) => handleInputChange('message_template', e.target.value)}
            />
            {selectedParam?.variables && selectedParam.variables.length > 0 && (
              <div className="mt-2">
                <p className="text-xs text-gray-500 mb-1">Available variables:</p>
                <div className="flex flex-wrap gap-1">
                  {selectedParam.variables.map((variable) => (
                    <Badge key={variable} color="info" className="text-xs">
                      {`{{ ${variable} }}`}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      );
    }
    
    // Test Notification step (final step)
    if (wizardStep === totalSteps - 1) {
      return (
        <div className="space-y-4">
          <h3 className="text-lg font-semibold">Test Notification (Optional)</h3>
          <p className="text-sm text-gray-600 dark:text-gray-400">
            Send a test notification to see what it will look like before creating the rule.
          </p>
          <Button
            color="purple"
            onClick={async () => {
              setTestingNotification(true);
              setTestNotificationResult(null);
              try {
                // For existing rules, test directly
                if (formState.id && formState.id > 0) {
                  const result = await apiClient.testNotificationRule(formState.id);
                  setTestNotificationResult({
                    success: result.success,
                    message: result.success 
                      ? `Test sent (${result.level.toUpperCase()}): ${result.message}`
                      : result.error || 'Test failed to send'
                  });
                } else {
                  // For new rules, we can't test directly, so show a preview
                  setTestNotificationResult({
                    success: true,
                    message: 'Preview: Rule would be created with the current settings. Create the rule to send actual test notifications.'
                  });
                }
              } catch (err: any) {
                setTestNotificationResult({
                  success: false,
                  message: err.response?.data?.detail || err.message || 'Failed to send test notification'
                });
              } finally {
                setTestingNotification(false);
              }
            }}
            disabled={testingNotification || formState.apprise_service_indices.length === 0}
          >
            {testingNotification ? 'Sending Test...' : 'Send Test Notification'}
          </Button>
          {testNotificationResult && (
            <Alert
              color={testNotificationResult.success ? 'success' : 'failure'}
              onDismiss={() => setTestNotificationResult(null)}
            >
              {testNotificationResult.message}
            </Alert>
          )}
          <p className="text-xs text-gray-500">
            You can proceed to create the rule without testing, or test first to verify the notification format.
          </p>
        </div>
      );
    }
    
    return <div>Unknown step</div>;
  };

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Spinner size="xl" />
      </div>
    );
  }

  return (
    <div className="flex h-screen">
      <Sidebar onLogout={handleLogout} isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Navbar
          hostname="nixos-router"
          username={username}
          connectionStatus={connectionStatus}
          onMenuClick={() => setSidebarOpen(!sidebarOpen)}
        />
        <main className="flex-1 overflow-y-auto bg-gray-50 p-6 dark:bg-gray-900">
          <div className="mx-auto flex max-w-7xl items-center justify-between pb-6">
            <div>
              <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Notifications</h1>
              <p className="text-sm text-gray-500">
                Automatically send Apprise notifications when monitored metrics cross thresholds.
              </p>
            </div>
            <Button onClick={openCreateModal}>New Rule</Button>
          </div>

          {error && (
            <Alert color="failure" className="mb-4" onDismiss={() => setError(null)}>
              {error}
            </Alert>
          )}

          <Card className="mb-6">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-xl font-semibold">Configured Rules</h2>
            </div>
            {rules.length === 0 ? (
              <p className="text-sm text-gray-500">No notifications configured yet. Click “New Rule” to begin.</p>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <Table.Head>
                    <Table.HeadCell>Name</Table.HeadCell>
                    <Table.HeadCell>Parameter</Table.HeadCell>
                    <Table.HeadCell>Thresholds</Table.HeadCell>
                    <Table.HeadCell>Status</Table.HeadCell>
                    <Table.HeadCell>Last Notification</Table.HeadCell>
                    <Table.HeadCell>Actions</Table.HeadCell>
                  </Table.Head>
                  <Table.Body className="divide-y">
                    {rules.map((rule) => (
                      <Table.Row key={rule.id} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                        <Table.Cell>
                          <div className="font-semibold text-gray-900 dark:text-white">{rule.name}</div>
                          <div className="text-xs text-gray-500">#{rule.id}</div>
                        </Table.Cell>
                        <Table.Cell>
                          <div className="text-sm font-medium">{rule.parameter_type}</div>
                          <div className="text-xs text-gray-500">
                            Duration {rule.duration_seconds}s · Cooldown {rule.cooldown_seconds}s
                          </div>
                        </Table.Cell>
                        <Table.Cell>
                          <div className="text-xs text-gray-500">
                            <span className="font-semibold">Info:</span>{' '}
                            {rule.threshold_info ?? '—'} · <span className="font-semibold">Warn:</span>{' '}
                            {rule.threshold_warning ?? '—'} · <span className="font-semibold">Fail:</span>{' '}
                            {rule.threshold_failure ?? '—'}
                          </div>
                        </Table.Cell>
                        <Table.Cell>
                          <div className="flex items-center gap-2">
                            <Badge color={rule.enabled ? 'success' : 'gray'}>
                              {rule.enabled ? 'Enabled' : 'Disabled'}
                            </Badge>
                            {rule.current_level && (
                              <Badge color={rule.current_level === 'failure' ? 'failure' : 'warning'}>
                                {rule.current_level.toUpperCase()}
                              </Badge>
                            )}
                          </div>
                        </Table.Cell>
                        <Table.Cell>
                          <div className="text-xs text-gray-500">
                            {formatTimestamp(rule.last_notification_at)}
                          </div>
                          <div className="text-xs text-gray-400">{rule.last_notification_level ?? ''}</div>
                        </Table.Cell>
                        <Table.Cell>
                          <div className="flex flex-wrap gap-2">
                            <Button size="xs" onClick={() => openEditModal(rule)}>
                              Edit
                            </Button>
                            <Button size="xs" color="light" onClick={() => handleToggleEnabled(rule)}>
                              {rule.enabled ? 'Disable' : 'Enable'}
                            </Button>
                            <Button size="xs" color="purple" onClick={() => handleTest(rule)}>
                              Test
                            </Button>
                            <Button size="xs" color="info" onClick={() => openHistory(rule)}>
                              History
                            </Button>
                            <Button size="xs" color="failure" onClick={() => handleDelete(rule)}>
                              Delete
                            </Button>
                          </div>
                        </Table.Cell>
                      </Table.Row>
                    ))}
                  </Table.Body>
                </Table>
              </div>
            )}
          </Card>

          {/* Apprise Service Management Sections */}
          {appriseEnabled && (
            <>
              {/* Configured Services Section */}
              <Card className="mb-6">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
                    Configured Services ({appriseServices.length})
                  </h2>
                  <Button
                    color="blue"
                    onClick={() => setUrlGeneratorModalOpen(true)}
                  >
                    New Service
                  </Button>
                </div>
                
                {sendResult && (
                  <Alert 
                    color={sendResult.success ? "success" : "failure"} 
                    icon={sendResult.success ? HiCheckCircle : HiXCircle}
                    className="mb-4"
                    onDismiss={() => setSendResult(null)}
                  >
                    {sendResult.message}
                  </Alert>
                )}
                
                {appriseServices.length === 0 ? (
                  <Alert color="info" icon={HiInformationCircle}>
                    No notification services are configured. Use the "New Service" button to create a service.
                  </Alert>
                ) : (
                  <Table>
                    <Table.Head>
                      <Table.HeadCell>Name</Table.HeadCell>
                      <Table.HeadCell>Description</Table.HeadCell>
                      <Table.HeadCell>Status</Table.HeadCell>
                      <Table.HeadCell>Actions</Table.HeadCell>
                    </Table.Head>
                    <Table.Body className="divide-y">
                      {appriseServices.map((service) => {
                        const serviceName = (service as any).id || service.id.toString();
                        const isSending = sendingServices.has(serviceName);
                        const sendResult = sendResults.get(serviceName);
                        
                        return (
                          <Table.Row key={service.id} className="bg-white dark:border-gray-700 dark:bg-gray-800">
                            <Table.Cell className="whitespace-nowrap font-medium text-gray-900 dark:text-white">
                              {service.name}
                            </Table.Cell>
                            <Table.Cell className="text-gray-500 dark:text-gray-400">
                              {service.description || '-'}
                            </Table.Cell>
                            <Table.Cell>
                              <Badge color={service.enabled ? "success" : "gray"}>
                                {service.enabled ? "Enabled" : "Disabled"}
                              </Badge>
                            </Table.Cell>
                            <Table.Cell>
                              <div className="flex gap-2">
                                <Button
                                  size="xs"
                                  color="blue"
                                  onClick={() => handleSendToService(serviceName)}
                                  disabled={isSending || !notificationBody.trim() || !service.enabled}
                                >
                                  {isSending ? 'Sending...' : sendResult?.success ? 'Send Again' : 'Send'}
                                </Button>
                                <Button
                                  size="xs"
                                  color="gray"
                                  onClick={() => handleTestService(serviceName)}
                                  disabled={!service.enabled}
                                >
                                  Test
                                </Button>
                              </div>
                            </Table.Cell>
                          </Table.Row>
                        );
                      })}
                    </Table.Body>
                  </Table>
                )}
              </Card>

              {/* Send Notification Section */}
              <Card className="mb-6">
                <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">Send Notification</h2>
                <div className="space-y-4">
                  <div>
                    <Label htmlFor="apprise-title" value="Title (optional)" />
                    <TextInput
                      id="apprise-title"
                      type="text"
                      placeholder="Notification title"
                      value={notificationTitle}
                      onChange={(e) => setNotificationTitle(e.target.value)}
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <Label htmlFor="apprise-body" value="Message Body *" />
                    <Textarea
                      id="apprise-body"
                      placeholder="Enter your notification message..."
                      value={notificationBody}
                      onChange={(e) => setNotificationBody(e.target.value)}
                      rows={4}
                      className="mt-1"
                      required
                    />
                  </div>
                  <div>
                    <Label htmlFor="apprise-type" value="Notification Type" />
                    <Select
                      id="apprise-type"
                      value={notificationType}
                      onChange={(e) => setNotificationType(e.target.value)}
                      className="mt-1"
                    >
                      <option value="info">Info</option>
                      <option value="success">Success</option>
                      <option value="warning">Warning</option>
                      <option value="failure">Failure</option>
                    </Select>
                  </div>
                  <Button
                    onClick={handleSendNotification}
                    disabled={sending || !notificationBody.trim()}
                    className="w-full sm:w-auto"
                  >
                    {sending ? 'Sending...' : 'Send to All Services'}
                  </Button>
                </div>
              </Card>

              {/* How It Works Section */}
              <Card>
                <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">How It Works</h2>
                <div className="space-y-3 text-gray-700 dark:text-gray-300">
                  <p>
                    Apprise is integrated into the NixOS Router WebUI backend, allowing you to send notifications
                    to multiple services configured in <code className="px-1 py-0.5 bg-gray-200 dark:bg-gray-700 rounded">router-config.nix</code>.
                  </p>
                  <p>
                    Notifications can be sent to all configured services simultaneously, or to individual services.
                  </p>
                  <p>
                    <strong>Notification Types:</strong>
                  </p>
                  <ul className="list-disc list-inside ml-4 space-y-1">
                    <li><strong>info</strong> - General information (default)</li>
                    <li><strong>success</strong> - Success messages</li>
                    <li><strong>warning</strong> - Warning messages</li>
                    <li><strong>failure</strong> - Error/failure messages</li>
                  </ul>
                </div>
              </Card>
            </>
          )}
        </main>
      </div>

      <Modal show={formOpen} size="4xl" onClose={closeForm}>
        <Modal.Header>
          {formState.id ? 'Edit Notification Rule' : 'Create Notification Rule'}
          <div className="mt-2 text-sm text-gray-500">
            Step {wizardStep + 1} of {getTotalSteps()}
          </div>
        </Modal.Header>
        <Modal.Body>
          <div className="space-y-4 max-h-[70vh] overflow-y-auto">
            {formError && (
              <Alert color="failure" onDismiss={() => setFormError(null)}>
                {formError}
              </Alert>
            )}
            {formSuccess && (
              <Alert color="success" onDismiss={() => setFormSuccess(null)}>
                {formSuccess}
              </Alert>
            )}
            {testResult && (
              <Alert color="info" onDismiss={() => setTestResult(null)}>
                {testResult}
              </Alert>
            )}
            
            {/* Step Progress Indicator */}
            <div className="mb-6">
              <div className="flex items-center justify-between">
                {Array.from({ length: getTotalSteps() }).map((_, index) => (
                  <div key={index} className="flex items-center flex-1">
                    <div
                      className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold ${
                        index === wizardStep
                          ? 'bg-blue-500 text-white'
                          : index < wizardStep
                          ? 'bg-green-500 text-white'
                          : 'bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-400'
                      }`}
                    >
                      {index < wizardStep ? '✓' : index + 1}
                    </div>
                    {index < getTotalSteps() - 1 && (
                      <div
                        className={`flex-1 h-1 mx-2 ${
                          index < wizardStep ? 'bg-green-500' : 'bg-gray-200 dark:bg-gray-700'
                        }`}
                      />
                    )}
                  </div>
                ))}
              </div>
            </div>
            
            {/* Step Content */}
            {renderStepContent()}
          </div>
        </Modal.Body>
        <Modal.Footer>
          <div className="flex justify-between w-full">
            <Button
              color="light"
              onClick={handleWizardPrev}
              disabled={wizardStep === 0}
            >
              Previous
            </Button>
            <div className="flex gap-2">
              <Button color="light" onClick={closeForm}>
                Cancel
              </Button>
              {wizardStep === getTotalSteps() - 1 ? (
                <Button
                  onClick={handleSubmit}
                  disabled={!validateStep(wizardStep)}
                >
                  {formState.id ? 'Save Changes' : 'Create Rule'}
                </Button>
              ) : (
                <Button
                  onClick={handleWizardNext}
                  disabled={!validateStep(wizardStep)}
                >
                  Next
                </Button>
              )}
            </div>
          </div>
        </Modal.Footer>
      </Modal>

      <Modal show={historyState.open} onClose={() => setHistoryState({ open: false, items: [], ruleName: '' })}>
        <Modal.Header>Notification History · {historyState.ruleName}</Modal.Header>
        <Modal.Body>
          {historyState.items.length === 0 ? (
            <p className="text-sm text-gray-500">No history recorded.</p>
          ) : (
            <div className="space-y-3">
              {historyState.items.map((item) => (
                <Card key={item.id}>
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-sm font-semibold">{formatTimestamp(item.timestamp)}</div>
                      <div className="text-xs text-gray-500">Value: {item.value}</div>
                    </div>
                    <Badge color={item.sent_successfully ? 'success' : 'failure'}>{item.level.toUpperCase()}</Badge>
                  </div>
                  {item.message && <p className="mt-2 text-sm text-gray-600">{item.message}</p>}
                </Card>
              ))}
            </div>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button color="light" onClick={() => setHistoryState({ open: false, items: [], ruleName: '' })}>
            Close
          </Button>
        </Modal.Footer>
      </Modal>

      {/* URL Generator Modal */}
      <Modal show={urlGeneratorModalOpen} onClose={() => setUrlGeneratorModalOpen(false)} size="6xl">
        <Modal.Header>Create New Apprise Service</Modal.Header>
        <Modal.Body className="max-h-[80vh] overflow-y-auto">
          <div>
            <AppriseUrlGenerator 
              onServiceSaved={() => {
                setUrlGeneratorModalOpen(false);
                fetchAppriseStatus();
              }}
            />
          </div>
        </Modal.Body>
      </Modal>

    </div>
  );
}

