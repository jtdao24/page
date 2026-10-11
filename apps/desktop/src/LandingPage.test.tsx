// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import LandingPage from "./LandingPage";

afterEach(cleanup);

describe("Page download landing page", () => {
  it("keeps unavailable downloads honest and keeps the local workspace accessible", () => {
    render(<LandingPage appHref="/app/" />);
    expect(screen.getByRole("button", { name: /Download being prepared/ }).hasAttribute("disabled")).toBe(true);
    expect(screen.queryByRole("link", { name: "Download for macOS" })).toBeNull();
    expect(screen.getByRole("link", { name: /Just looking\? Open the workspace preview/ }).getAttribute("href")).toBe("/app/");
    expect(screen.getByRole("link", { name: "Download" }).getAttribute("href")).toBe("#download");
    expect(screen.getByRole("link", { name: "get on the same Page" }).getAttribute("href")).toBe("#download");
  });

  it("offers the DMG installer with bundled core and model", () => {
    render(<LandingPage macDownloadUrl="/downloads/Page-0.1.0-macos-arm64.dmg" />);
    const download = screen.getByRole("link", { name: "Download for macOS" });
    expect(download.getAttribute("href")).toBe("/downloads/Page-0.1.0-macos-arm64.dmg");
    expect(download.hasAttribute("download")).toBe(true);
    expect(screen.queryByRole("button", { name: /Download being prepared/ })).toBeNull();
    expect(screen.getByText(/No Python setup required/)).toBeTruthy();
    expect(screen.getByText(/Locally signed; not Apple-notarized/)).toBeTruthy();
    expect(screen.queryByText(/development build/i)).toBeNull();
  });

  it("keeps the removed sample graph out of the landing page", () => {
    render(<LandingPage />);
    expect(document.querySelector(".landing-library")).toBeNull();
    expect(screen.queryByRole("button", { name: /Read sample:/ })).toBeNull();
  });

  it("replaces questions with measured performance without the removed target panel", () => {
    render(<LandingPage />);
    expect(screen.queryByText("03 / A FEW GOOD QUESTIONS")).toBeNull();
    expect(screen.getByText("03 / PERFORMANCE, MEASURED")).toBeTruthy();
    expect(screen.getByText("89.7%")).toBeTruthy();
    expect(screen.queryByText("target token reduction")).toBeNull();
    expect(screen.getByText(/not Gemini’s billing tokenizer/)).toBeTruthy();
    expect(screen.getByRole("link", { name: /Download the benchmark results/ }).hasAttribute("download")).toBe(true);
  });
});
