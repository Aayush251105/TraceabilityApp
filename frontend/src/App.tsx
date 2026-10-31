import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/layout/AppShell";
import { CodeView } from "./pages/CodeView";
import { NewRun } from "./pages/NewRun";
import { NotFound } from "./pages/NotFound";
import { Pipeline } from "./pages/Pipeline";
import { Requirement } from "./pages/Requirement";
import { Results } from "./pages/Results";
import { Review } from "./pages/Review";
import { Runs } from "./pages/Runs";
import { Search } from "./pages/Search";
import { Settings } from "./pages/Settings";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Runs />} />
        <Route path="new" element={<NewRun />} />
        <Route path="runs/:runId">
          <Route index element={<Navigate to="pipeline" replace />} />
          <Route path="pipeline" element={<Pipeline />} />
          <Route path="review" element={<Review />} />
          <Route path="results" element={<Results />} />
          <Route path="requirements/:requirementId" element={<Requirement />} />
          <Route path="search" element={<Search />} />
          <Route path="code" element={<CodeView />} />
        </Route>
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
