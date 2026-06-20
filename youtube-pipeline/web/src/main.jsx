import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import "antd/dist/reset.css";
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <HashRouter>
    <App />
  </HashRouter>
);
