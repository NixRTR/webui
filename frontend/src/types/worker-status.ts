/**
 * Worker status (Celery) API types
 */

export interface TaskInfo {
  id: string;
  name: string;
  worker: string | null;
  args: unknown[];
  kwargs: Record<string, unknown>;
  time_started: number | null;
  runtime: number | null;
  eta: string | null;
  delivery_info: Record<string, unknown> | null;
}

export interface QueueStats {
  name: string;
  broker_length: number;
  reserved_count: number;
  active_count: number;
}

export interface WorkerStatusResponse {
  queues: QueueStats[];
  active_tasks: TaskInfo[];
  reserved_tasks: TaskInfo[];
  scheduled_tasks: TaskInfo[];
  overdue_tasks: TaskInfo[];
  long_running_tasks: TaskInfo[];
}

export interface PurgeQueuesResponse {
  purged: number;
}

export interface TriggerTestTaskResponse {
  task_id: string;
}
