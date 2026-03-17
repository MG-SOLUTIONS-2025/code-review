import { Routes, Route } from "react-router-dom";
import Navbar from "./components/Navbar";
import Overview from "./pages/Overview";
import ScanResults from "./pages/ScanResults";
import Reviews from "./pages/Reviews";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <div className="flex min-h-screen">
      <Navbar />
      <main className="flex-1 p-6 ml-56 overflow-auto">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/scans" element={<ScanResults />} />
          <Route path="/reviews" element={<Reviews />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}
