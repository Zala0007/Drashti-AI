import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";
import "./styles.css";
import "./visual-intelligence.css";
import "./design-system.css";
import App from "./App";

try {
  const savedTheme = window.localStorage.getItem("drishti-theme");
  document.documentElement.dataset.theme = savedTheme === "light" || savedTheme === "dark"
    ? savedTheme
    : window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
} catch {
  document.documentElement.dataset.theme = window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
