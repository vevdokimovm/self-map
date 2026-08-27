import { Routes, Route } from "react-router-dom";
import Nav from "./components/Nav";
import SectionsPage from "./pages/SectionsPage";
import SectionDetailPage from "./pages/SectionDetailPage";
import RegistryPage from "./pages/RegistryPage";
import SearchPage from "./pages/SearchPage";
import "./styles/app.css";

export default function App() {
  return (
    <div>
      <Nav />
      <Routes>
        <Route path="/" element={<SectionsPage />} />
        <Route path="/section/:dir" element={<SectionDetailPage />} />
        <Route path="/registry" element={<RegistryPage />} />
        <Route path="/search" element={<SearchPage />} />
      </Routes>
    </div>
  );
}
