import { Routes, Route } from 'react-router-dom';
import Layout from './components/common/Layout';
import Overview from './pages/Overview';
import ProjectDashboard from './pages/ProjectDashboard';
import SessionDetail from './pages/SessionDetail';
import SubagentDetail from './pages/SubagentDetail';

function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/project/:projectHash" element={<ProjectDashboard />} />
        <Route path="/session/:projectHash/:sessionId" element={<SessionDetail />} />
        <Route path="/subagent/:projectHash/:sessionId/:agentId" element={<SubagentDetail />} />
      </Routes>
    </Layout>
  );
}

export default App;
