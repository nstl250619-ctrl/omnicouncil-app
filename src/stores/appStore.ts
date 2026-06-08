import { create } from 'zustand';

// ========== Types ==========

export type ConnectionStatus = 'connected' | 'disconnected' | 'reconnecting';
export type AIStatus = 'idle' | 'waiting' | 'streaming' | 'completed' | 'error';
export type TabId = 'responses' | 'comparison' | 'consensus' | 'conflict' | 'judge' | 'review' | 'debate' | 'history';

export type RuntimeState =
  | 'unknown'
  | 'initializing'
  | 'profile_loading'
  | 'session_checking'
  | 'ready'
  | 'degraded'
  | 'login_required'
  | 'recovering'
  | 'unavailable'
  | 'shutdown';

export interface RuntimeHealth {
  state: RuntimeState;
  browser_alive: boolean;
  page_alive: boolean;
  session_valid: boolean;
  last_heartbeat: number;
  recovery_attempts?: number;
  uptime_seconds?: number;
}

export interface RuntimeMetricsSnapshot {
  page_created: number;
  page_destroyed: number;
  page_lease_acquired: number;
  page_lease_released: number;
  page_busy_rejections: number;
  recovery_started: number;
  recovery_succeeded: number;
  recovery_failed: number;
  recovery_aborted_busy: number;
  session_expired: number;
  query_total: number;
  query_succeeded: number;
  query_failed: number;
  eviction_started: number;
  eviction_completed: number;
}

export interface AIResponseState {
  status: AIStatus;
  content: string;
  error: string | null;
  wordCount: number | null;
  elapsedMs: number | null;
}

export interface AIProviderInfo {
  provider_id: string;
  display_name: string;
  enabled: boolean;
  icon_color: string;
  icon_emoji: string;
}

export interface ToastEntry {
  id: number;
  message: string;
  severity: 'error' | 'warning' | 'success' | 'info';
  autoHideMs?: number;
}

// ========== error_code → user-friendly message mapping ==========

const ERROR_CODE_MESSAGES: Record<string, string> = {
  PAGE_BUSY: 'AI 页面正被其他查询独占，正在同步状态，请稍后重试...',
  RECOVERY_BUSY: 'AI 正在执行自动故障恢复，通道暂时锁定，请稍候...',
  RUNTIME_NOT_READY: 'AI 运行引擎正在初始化，请稍候...',
  CIRCUIT_OPEN: 'AI 连续失败过多，熔断器已触发，请稍后重试...',
  RATE_LIMITED: '请求过于频繁，已被限流，请稍后重试...',
  RUNTIME_NOT_FOUND: 'AI 运行时未找到，请检查平台配置...',
  ADAPTER_NOT_FOUND: 'AI 适配器未找到，请检查平台配置...',
  RUNTIME_ERROR: 'AI 运行时异常，请稍后重试...',
  INTERNAL_ERROR: '内部错误，请稍后重试...',
};

function resolveErrorMessage(errorCode: string | undefined, fallback: string): string {
  if (errorCode && ERROR_CODE_MESSAGES[errorCode]) {
    return ERROR_CODE_MESSAGES[errorCode];
  }
  return fallback;
}

// ========== Toast ID counter ==========

let _toastId = 0;

// ========== AppState interface ==========

export interface AppState {
  // Connection
  connectionStatus: ConnectionStatus;

  // Available providers from backend
  aiList: AIProviderInfo[];

  // Auth status per AI
  authStatus: Record<string, { status: string; message: string }>;

  // Runtime health per AI (from /api/runtime/health)
  runtimeHealthMap: Record<string, RuntimeHealth>;

  // Runtime metrics per AI (from /metrics/runtime)
  runtimeMetricsMap: Record<string, RuntimeMetricsSnapshot>;

  // Toast notifications
  toasts: ToastEntry[];

  // Current task
  currentTaskId: string | null;
  query: string;
  selectedAIs: string[];

  // Per-AI responses
  responses: Record<string, AIResponseState>;

  // Analysis results
  comparison: Record<string, unknown> | null;
  consensus: Record<string, unknown> | null;
  conflict: Record<string, unknown> | null;

  // UI state
  activeTab: TabId;

  // Actions
  setConnectionStatus: (status: ConnectionStatus) => void;
  submitQuery: (query: string, aiIds: string[]) => void;
  cancelTask: () => void;
  setActiveTab: (tab: TabId) => void;
  handleMessage: (msg: { type: string; data: Record<string, unknown> }) => void;
  resetResponses: () => void;
  updateRuntimeHealth: (aiId: string, health: RuntimeHealth) => void;
  setRuntimeHealthMap: (healthMap: Record<string, RuntimeHealth>) => void;
  setRuntimeMetricsMap: (metricsMap: Record<string, RuntimeMetricsSnapshot>) => void;
  addToast: (message: string, severity?: ToastEntry['severity'], autoHideMs?: number) => void;
  removeToast: (id: number) => void;
}

// ========== Initial State ==========

const createInitialResponse = (): AIResponseState => ({
  status: 'idle',
  content: '',
  error: null,
  wordCount: null,
  elapsedMs: null,
});

// ========== Store ==========

export const useAppStore = create<AppState>((set, get) => ({
  // Initial values
  connectionStatus: 'disconnected',
  aiList: [],
  authStatus: {},
  runtimeHealthMap: {},
  runtimeMetricsMap: {},
  toasts: [],
  currentTaskId: null,
  query: '',
  selectedAIs: ['deepseek', 'qianwen'],
  responses: {},
  comparison: null,
  consensus: null,
  conflict: null,
  activeTab: 'responses',

  // Actions
  setConnectionStatus: (status) => set({ connectionStatus: status }),

  addToast: (message, severity = 'info', autoHideMs = 5000) => {
    const id = ++_toastId;
    set((state) => ({
      toasts: [...state.toasts, { id, message, severity, autoHideMs }],
    }));
    if (autoHideMs > 0) {
      setTimeout(() => {
        get().removeToast(id);
      }, autoHideMs);
    }
  },

  removeToast: (id) => {
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    }));
  },

  submitQuery: (query, aiIds) => {
    // Guard: don't re-submit while a task is in progress
    const state = get();
    const hasRunning = Object.values(state.responses).some(
      (r) => r.status === 'waiting' || r.status === 'streaming'
    );
    if (hasRunning) {
      // P3: show toast instead of silent discard
      get().addToast('请等待当前 AI 任务执行完成再提交新查询', 'warning', 3000);
      return;
    }

    const responses: Record<string, AIResponseState> = {};
    aiIds.forEach((id) => {
      responses[id] = { ...createInitialResponse(), status: 'waiting' };
    });

    set({
      query,
      selectedAIs: aiIds,
      responses,
      currentTaskId: null,
      comparison: null,
      consensus: null,
      conflict: null,
      activeTab: 'responses',
    });
  },

  cancelTask: () => {
    set({ currentTaskId: null });
  },

  updateRuntimeHealth: (aiId, health) => {
    set((state) => ({
      runtimeHealthMap: {
        ...state.runtimeHealthMap,
        [aiId]: health,
      },
    }));
  },

  setRuntimeHealthMap: (healthMap) => {
    set({ runtimeHealthMap: healthMap });
  },

  setRuntimeMetricsMap: (metricsMap) => {
    set({ runtimeMetricsMap: metricsMap });
  },

  setActiveTab: (tab) => set({ activeTab: tab }),

  resetResponses: () => {
    const responses: Record<string, AIResponseState> = {};
    get().selectedAIs.forEach((id) => {
      responses[id] = createInitialResponse();
    });
    set({ responses });
  },

  handleMessage: (msg) => {
    const { type, data } = msg;

    // WebSocket event isolation: only handle events for the task we initiated
    // This prevents broadcasts from other clients (multi-tool, scripts) from
    // corrupting our state
    switch (type) {
      case 'progress':
        set({ currentTaskId: data.task_id as string });
        break;

      case 'ai_started':
        // Event isolation: only handle events for our own task
        if (data.task_id && get().currentTaskId && data.task_id !== get().currentTaskId) break;
        set((state) => ({
          responses: {
            ...state.responses,
            [data.ai_id as string]: {
              ...state.responses[data.ai_id as string],
              status: 'streaming',
            },
          },
        }));
        break;

      case 'token':
        set((state) => {
          const aiId = data.ai_id as string;
          const current = state.responses[aiId];
          if (!current) return state;
          return {
            responses: {
              ...state.responses,
              [aiId]: {
                ...current,
                content: current.content + (data.token as string),
                status: 'streaming',
              },
            },
          };
        });
        break;

      case 'ai_completed':
        if (data.task_id && get().currentTaskId && data.task_id !== get().currentTaskId) break;
        set((state) => ({
          responses: {
            ...state.responses,
            [data.ai_id as string]: {
              status: 'completed',
              content: (data.full_text as string) || '',  // Prevent undefined crash
              error: null,
              wordCount: data.word_count as number,
              elapsedMs: data.elapsed_ms as number,
            },
          },
        }));
        break;

      case 'ai_failed': {
        // P0: parse error_code and map to user-friendly message
        const errorCode = data.error_code as string | undefined;
        const rawError = (data.error as string) || '未知错误';
        const friendlyMessage = resolveErrorMessage(errorCode, rawError);

        set((state) => ({
          responses: {
            ...state.responses,
            [data.ai_id as string]: {
              ...state.responses[data.ai_id as string],
              status: 'error',
              error: friendlyMessage,
            },
          },
        }));
        break;
      }

      case 'all_completed':
        set({ currentTaskId: data.task_id as string });
        break;

      case 'comparison_ready':
        set({ comparison: data.comparison_context as Record<string, unknown> });
        break;

      case 'consensus_ready':
        set({ consensus: data.consensus_context as Record<string, unknown> });
        break;

      case 'conflict_ready':
        set({ conflict: data.conflict_context as Record<string, unknown> });
        break;

      case 'error':
        console.error('[Backend Error]', data);
        break;

      case 'engine_status':
        console.log('[Engine] Status:', data);
        break;

      case 'ai_list':
        set({ aiList: data as unknown as AIProviderInfo[] });
        break;

      case 'task_created':
        set({ currentTaskId: data.task_id as string });
        break;

      case 'task_cancelled':
        set({ currentTaskId: null });
        break;

      case 'auth_status':
        // Login status update from backend
        console.log('[Auth]', data.ai_id, data.status, data.message);
        set((state) => ({
          authStatus: {
            ...state.authStatus,
            [data.ai_id as string]: {
              status: data.status as string,
              message: data.message as string,
            },
          },
        }));
        break;

      // ── Health / Runtime events ──
      case 'session_expired': {
        const seAiId = data.ai_id as string;
        console.warn('[Health] Session expired:', seAiId);
        set((state) => ({
          runtimeHealthMap: state.runtimeHealthMap[seAiId]
            ? {
                ...state.runtimeHealthMap,
                [seAiId]: { ...state.runtimeHealthMap[seAiId], state: 'login_required', session_valid: false },
              }
            : state.runtimeHealthMap,
        }));
        break;
      }

      case 'recovery_success': {
        const rsAiId = data.ai_id as string;
        console.log('[Health] Recovery success:', rsAiId);
        set((state) => ({
          runtimeHealthMap: state.runtimeHealthMap[rsAiId]
            ? {
                ...state.runtimeHealthMap,
                [rsAiId]: { ...state.runtimeHealthMap[rsAiId], state: 'ready', session_valid: true },
              }
            : state.runtimeHealthMap,
        }));
        break;
      }

      case 'ai_unavailable': {
        const uaAiId = data.ai_id as string;
        console.warn('[Health] AI unavailable:', uaAiId);
        set((state) => ({
          runtimeHealthMap: state.runtimeHealthMap[uaAiId]
            ? {
                ...state.runtimeHealthMap,
                [uaAiId]: { ...state.runtimeHealthMap[uaAiId], state: 'unavailable' },
              }
            : state.runtimeHealthMap,
        }));
        break;
      }

      case 'pong':
        break;

      default:
        console.warn('[WS] Unknown message type:', type);
    }
  },
}));
