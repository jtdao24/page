import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("App", () => {
  it("renders a browser-unavailable workspace with the Page heading", () => {
    expect(renderToStaticMarkup(<App />)).toContain(">Page</h1>");
    expect(renderToStaticMarkup(<App />)).toContain("Desktop runtime unavailable");
  });
});
