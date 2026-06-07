import { create } from 'zustand';

// ========== Types ==========

export type ConnectionStatus = 'connected' | 'disconnected' | 'reconnecting';
export type AIStatus = 'idle' | 'waiting' | 'streaming' | 'completed' | 'error';
export type TabId = 'responses' | 'comparison' | 'consensus' | 'conflict' | 'judge' | 'review' | 'debate' | 'history';

export interface RuntimeHealth {
  state: 'healthy' | 'degraded' | 'unavailable' | 'login_required';
  browser_alive: boolean;
  page_alive: boolean;
  session_valid: boolean;
  last_heartbeat: number;
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

export interface AppState {
  // Connection
  connectionStatus: ConnectionStatus;

  // Available providers from backend
  aiList: AIProviderInfo[];

  // Auth status per AI
  authStatus: Record<string, { status: string; message: string }>;

  // Runtime health per AI (from /api/runtime/health)
  runtimeHealthMap: Record<string, RuntimeHealth>;

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

  submitQuery: (query, aiIds) => {
    // Guard: don't re-submit while a task is in progress
    const state = get();
    const hasRunning = Object.values(state.responses).some(
      (r) => r.status === 'waiting' || r.status === 'streaming'
    );
    if (hasRunning) return;

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

      case 'ai_failed':
        set((state) => ({
          responses: {
            ...state.responses,
            [data.ai_id as string]: {
              ...state.responses[data.ai_id as string],
              status: 'error',
              error: data.error as string,
            },
          },
        }));
        break;

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
                [rsAiId]: { ...state.runtimeHealthMap[rsAiId], state: 'healthy', session_valid: true },
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
