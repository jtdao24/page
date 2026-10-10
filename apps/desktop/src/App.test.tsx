import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import App from "./App";
import BacklinksPanel from "./components/BacklinksPanel";

describe("App", () => {
  it("renders a connecting state before the API is ready", () => {
    expect(renderToStaticMarkup(<App />)).toContain("Connecting to Page Core");
  });
});

describe("BacklinksPanel", () => {
  it("shows an empty state when the note has no backlinks", () => {
    expect(renderToStaticMarkup(<BacklinksPanel backlinks={[]} onOpen={() => undefined} />)).toContain(
      "No notes link here yet.",
    );
  });
});
