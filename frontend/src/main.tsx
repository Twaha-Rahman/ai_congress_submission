import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-500.css";
import "@fontsource/inter/latin-600.css";
import "@fontsource/cormorant-garamond/latin-500.css";
import Authentication from "./Authentication";
import "./styles.css";
import "./accounts.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Authentication />
  </React.StrictMode>,
);
