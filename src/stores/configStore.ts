import { create } from 'zustand';
import { invoke } from '@tauri-apps/api/core';

export type EngineMode = 'cdp' | 'embedded';

export interface AIConfig {
  aiId: string;
  aiName: string;
  enabled: boolean;
  status: 'connected' | 'disconnected' | 'expired';
}

export interface ConfigState {
  // Setup
  isFirstLaunch: boolean;
  setupCompleted: boolean;
  engineMode: EngineMode;

  // AI configs
  ais: AIConfig[];

  // Actions
  setEngineMode: (mode: EngineMode) => void;
  completeSetup: (mode: EngineMode) => void;
  updateAIStatus: (aiId: string, status: AIConfig['status']) => void;
  toggleAI: (aiId: string) => void;
  loadConfig: () => Promise<void>;
  saveConfig: () => Promise<void>;
}

const DEFAULT_AIS: AIConfig[] = [
  { aiId: 'deepseek', aiName: 'DeepSeek', enabled: true, status: 'disconnected' },
  { aiId: 'gemini', aiName: 'Gemini', enabled: false, status: 'disconnected' },
  { aiId: 'qianwen', aiName: '千问', enabled: true, status: 'disconnected' },
];

export const useConfigStore = create<ConfigState>((set, get) => ({
  isFirstLaunch: true,
  setupCompleted: false,
  engineMode: 'embedded',
  ais: DEFAULT_AIS,

  setEngineMode: (mode) => set({ engineMode: mode }),

  completeSetup: (mode) => {
    set({
      engineMode: mode,
      setupCompleted: true,
      isFirstLaunch: false,
    });
    get().saveConfig();
  },

  updateAIStatus: (aiId, status) => {
    set((state) => ({
      ais: state.ais.map((ai) =>
        ai.aiId === aiId ? { ...ai, status } : ai
      ),
    }));
  },

  toggleAI: (aiId) => {
    set((state) => ({
      ais: state.ais.map((ai) =>
        ai.aiId === aiId ? { ...ai, enabled: !ai.enabled } : ai
      ),
    }));
    get().saveConfig();
  },

  loadConfig: async () => {
    try {
      // In Tauri, read config from filesystem
      const configStr = await invoke<string>('read_config');
      const config = JSON.parse(configStr);

      // Force wizard to show if no AI is authenticated
      const hasAuthenticatedAI = config.ais?.some((ai: { status: string }) => ai.status === 'authenticated') ?? false;

      set({
        isFirstLaunch: config.isFirstLaunch ?? true,
        setupCompleted: hasAuthenticatedAI ? (config.setupCompleted ?? false) : false,
        engineMode: config.engineMode ?? 'embedded',
        ais: config.ais ?? DEFAULT_AIS,
      });
    } catch {
      // Config doesn't exist yet, use defaults
      set({ isFirstLaunch: true });
    }
  },

  saveConfig: async () => {
    const state = get();
    const config = {
      isFirstLaunch: state.isFirstLaunch,
      setupCompleted: state.setupCompleted,
      engineMode: state.engineMode,
      ais: state.ais,
    };
    try {
      await invoke('write_config', { content: JSON.stringify(config, null, 2) });
    } catch (e) {
      console.error('Failed to save config:', e);
    }
  },
}));
