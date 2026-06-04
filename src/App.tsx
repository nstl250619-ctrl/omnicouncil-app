import { useWebSocket } from './hooks/useWebSocket';
import { useAppStore } from './stores/appStore';
import { Header } from './components/Header';
import { QueryInput } from './components/QueryInput';
import { TabBar } from './components/TabBar';
import { ResponsesTab } from './components/ResponsesTab';
import { ComparisonTab } from './components/ComparisonTab';
import { ConsensusTab } from './components/ConsensusTab';
import { ConflictTab } from './components/ConflictTab';
import { StatusBar } from './components/StatusBar';

function App() {
  useWebSocket();

  const activeTab = useAppStore((s) => s.activeTab);

  return (
    <div className="app">
      <Header />
      <QueryInput />
      <TabBar />
      <div className="tab-content">
        {activeTab === 'responses' && <ResponsesTab />}
        {activeTab === 'comparison' && <ComparisonTab />}
        {activeTab === 'consensus' && <ConsensusTab />}
        {activeTab === 'conflict' && <ConflictTab />}
      </div>
      <StatusBar />
    </div>
  );
}

export default App;
