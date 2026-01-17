import { Routes, Route } from 'react-router-dom';
import Layout from './components/common/Layout';
import Overview from './pages/Overview';
import ProjectDashboard from './pages/ProjectDashboard';
import SessionDetail from './pages/SessionDetail';

function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/project/:projectHash" element={<ProjectDashboard />} />
        <Route path="/session/:projectHash/:sessionId" element={<SessionDetail />} />
      </Routes>
    </Layout>
  );
}

export default App;
