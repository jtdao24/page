// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import LandingPage from "./LandingPage";

afterEach(cleanup);

describe("Page download landing page", () => {
  it("keeps unavailable downloads honest and keeps the local workspace accessible", () => {
    render(<LandingPage appHref="/app/" />);
    expect(screen.getByRole("button", { name: /Download being prepared/ }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", { name: "Windows coming soon" }).hasAttribute("disabled")).toBe(true);
    expect(screen.queryByRole("link", { name: "Download for macOS" })).toBeNull();
    expect(screen.getByRole("link", { name: "Open App" }).getAttribute("href")).toBe("/app/");
    expect(screen.getByRole("link", { name: "Download" }).getAttribute("href")).toBe("#download");
    expect(screen.getByRole("link", { name: "get on the same Page" }).getAttribute("href")).toBe("#download");
  });

  it("offers the supplied real build URL as a download and describes the separate core", () => {
    render(<LandingPage macDownloadUrl="/downloads/Page-macos-arm64.zip" />);
    const download = screen.getByRole("link", { name: "Download for macOS" });
    expect(download.getAttribute("href")).toBe("/downloads/Page-macos-arm64.zip");
    expect(download.hasAttribute("download")).toBe(true);
    expect(screen.queryByRole("button", { name: /Download being prepared/ })).toBeNull();
    expect(screen.getByText(/Native desktop app. The local core is installed separately/)).toBeTruthy();
  });

  it("opens a sample node with keyboard input and updates the illustrated note", async () => {
    const user = userEvent.setup();
    render(<LandingPage />);
    const node = screen.getByRole("button", { name: "Read sample: Things I want to build" });
    node.focus();
    await user.keyboard("{Enter}");
    expect(node.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Read sample: The art of noticing" }).getAttribute("aria-pressed")).toBe("false");
    const reading = document.querySelector<HTMLElement>(".demo-reading")!;
    expect(within(reading).getByRole("heading", { name: "Things I want to build" })).toBeTruthy();
    expect(within(reading).getByText("Projects/things-i-want-to-build.md")).toBeTruthy();
  });
});
