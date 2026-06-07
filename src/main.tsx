import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/globals.css';
import { useConfigStore } from './stores/configStore';

// Expose store for E2E tests
if (import.meta.env.DEV) {
  (window as unknown as Record<string, unknown>).__configStore = useConfigStore;
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
