import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/layout/AppShell";
import { ComponentSheet } from "./pages/ComponentSheet";
import { NewRun } from "./pages/NewRun";
import { Pipeline } from "./pages/Pipeline";
import { Placeholder } from "./pages/Placeholder";
import { Review } from "./pages/Review";
import { Runs } from "./pages/Runs";

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
          <Route path="results" element={<Placeholder title="Results" step="Step 11" />} />
          <Route path="requirements/:requirementId" element={<Placeholder title="Requirement" step="Step 12" />} />
          <Route path="code" element={<Placeholder title="Code view" step="Step 13" />} />
        </Route>
        <Route path="settings" element={<Placeholder title="Settings" step="Step 13" />} />
        <Route path="components" element={<ComponentSheet />} />
        <Route path="*" element={<Placeholder title="Not found" step="no step: this page does not exist" />} />
      </Route>
    </Routes>
  );
}
