import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useApp } from "./state/AppContext";
import { Layout } from "./components/Layout";
import { LoginPage } from "./pages/Login";
import { HomePage } from "./pages/Home";
import { SetsPage } from "./pages/Sets";
import { SetDetailPage } from "./pages/SetDetail";
import { ReviewPage } from "./pages/Review";
import { StatsPage } from "./pages/Stats";
import { SettingsPage } from "./pages/Settings";
import { DiscoverPage } from "./pages/Discover";
import { SharePage } from "./pages/Share";
import { FoldersPage } from "./pages/Folders";

const EditorPage = lazy(() => import("./pages/Editor").then((m) => ({ default: m.EditorPage })));
const StudyPage = lazy(() => import("./pages/study/StudyPage").then((m) => ({ default: m.StudyPage })));
const StudyConfigPage = lazy(() => import("./pages/study/StudyConfigPage").then((m) => ({ default: m.StudyConfigPage })));
const ResultPage = lazy(() => import("./pages/study/ResultPage").then((m) => ({ default: m.ResultPage })));
const AdminPage = lazy(() => import("./pages/Admin").then((m) => ({ default: m.AdminPage })));

export default function App() {
  const { user, loading } = useApp();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="skeleton h-10 w-40" aria-busy="true" />
      </div>
    );
  }

  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/share/*" element={<SharePage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <Layout>
      <Suspense fallback={<div className="skeleton h-40 w-full" aria-busy="true" />}>
        <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/sets" element={<SetsPage />} />
        <Route path="/sets/:setId" element={<SetDetailPage />} />
        <Route path="/sets/:setId/edit" element={<EditorPage />} />
        <Route path="/study/new" element={<StudyConfigPage />} />
        <Route path="/study/:sessionId" element={<StudyPage />} />
        <Route path="/study/:sessionId/result" element={<ResultPage />} />
        <Route path="/folders" element={<FoldersPage />} />
        <Route path="/review" element={<ReviewPage />} />
        <Route path="/stats" element={<StatsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/discover" element={<DiscoverPage />} />
        <Route path="/share/:token" element={<SharePage />} />
        <Route path="/share/*" element={<SharePage />} />
        {user.role === "admin" && <Route path="/admin" element={<AdminPage />} />}
        <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </Layout>
  );
}
