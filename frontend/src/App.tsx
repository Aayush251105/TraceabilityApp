import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/layout/AppShell";
import { ComponentSheet } from "./pages/ComponentSheet";
import { Placeholder } from "./pages/Placeholder";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Placeholder title="Runs" step="Step 8" />} />
        <Route path="new" element={<Placeholder title="New run" step="Step 8" />} />
        <Route path="runs/:runId">
          <Route index element={<Navigate to="pipeline" replace />} />
          <Route path="pipeline" element={<Placeholder title="Live pipeline" step="Step 9" />} />
          <Route path="review" element={<Placeholder title="Review" step="Step 10" />} />
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
