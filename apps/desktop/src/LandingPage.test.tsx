// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import LandingPage from "./LandingPage";

afterEach(cleanup);

describe("Page download landing page", () => {
  it("says the download is coming soon until a release exists, and points to GitHub", () => {
    render(<LandingPage />);
    expect(screen.getByRole("button", { name: "Coming soon" }).hasAttribute("disabled")).toBe(true);
    expect(screen.queryByRole("link", { name: "Download for macOS" })).toBeNull();
    expect(screen.queryByText(/workspace preview/)).toBeNull();
    expect(screen.getByRole("link", { name: /Follow Page on GitHub/ }).getAttribute("href")).toBe("https://github.com/jtdao24/page");
    expect(screen.getByText(/signed, Apple-notarized release/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Coming soon" }).getAttribute("href")).toBe("#download");
    expect(screen.getByRole("link", { name: "get on the same Page" }).getAttribute("href")).toBe("#download");
  });

  it("offers the DMG installer with bundled core and model", () => {
    render(<LandingPage macDownloadUrl="/downloads/Page-0.1.0-macos-arm64.dmg" />);
    const download = screen.getByRole("link", { name: "Download for macOS" });
    expect(download.getAttribute("href")).toBe("/downloads/Page-0.1.0-macos-arm64.dmg");
    expect(download.hasAttribute("download")).toBe(true);
    expect(screen.queryByRole("button", { name: "Coming soon" })).toBeNull();
    expect(screen.getByText(/No Python setup required/)).toBeTruthy();
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
    expect(screen.getByText("PERFORMANCE, MEASURED")).toBeTruthy();
    expect(screen.getByText("89.7%")).toBeTruthy();
    expect(screen.queryByText("target token reduction")).toBeNull();
    expect(screen.getByText("How we measured").closest("details")?.textContent).toMatch(/not Gemini’s billing tokenizer/);
    expect(screen.getByRole("link", { name: /Download the benchmark results/ }).hasAttribute("download")).toBe(true);
  });

  it("walks through four steps, each with a real screenshot", () => {
    render(<LandingPage />);
    for (const title of ["plain notes you own.", "see how ideas link up.", "find things by meaning.", "answers with sources."]) {
      expect(screen.getByRole("heading", { name: title })).toBeTruthy();
    }
    expect(screen.getByRole("img", { name: /PDF passage ranked first/ })).toBeTruthy();
    expect(screen.getByRole("img", { name: /cited answer/ })).toBeTruthy();
    expect(screen.queryByText(/WHY WE MADE PAGE/)).toBeNull();
    expect(document.querySelector("canvas")).toBeNull();
  });
});
