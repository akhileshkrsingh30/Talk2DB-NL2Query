import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ChatPage } from "./pages/ChatPage";
import { SchemaPage } from "./pages/SchemaPage";
import { HistoryPage } from "./pages/HistoryPage";
import { SharingPage } from "./pages/SharingPage";
import { SharedResultPage } from "./pages/SharedResultPage";
import { ConnectionsPage } from "./pages/ConnectionsPage";

function App() {
  return (
    <Routes>
      <Route path="/share/:shareId" element={<SharedResultPage />} />
      <Route element={<Layout />}>
        <Route path="/" element={<ChatPage />} />
        <Route path="/schema" element={<SchemaPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/sharing" element={<SharingPage />} />
        <Route path="/connections" element={<ConnectionsPage />} />
      </Route>
    </Routes>
  );
}

export default App;
