import { describe, expect, it } from "vitest";

import { passwordStrength } from "../components/PasswordFields";
import { describeUserAgent, formatPartialDate, timeAgo } from "./format";

describe("formatting helpers", () => {
  it("describes user agents", () => {
    const mac = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36";
    expect(describeUserAgent(mac)).toBe("Chrome on macOS");
    expect(describeUserAgent(null)).toBe("Unknown device");
  });

  it("formats partial dates", () => {
    expect(formatPartialDate(null)).toBe("Present");
    expect(formatPartialDate("2016")).toBe("2016");
    expect(formatPartialDate("2021-03")).toMatch(/2021/);
  });

  it("formats relative times", () => {
    const now = Date.parse("2026-10-06T12:00:00Z");
    expect(timeAgo("2026-10-06T11:59:50Z", now)).toBe("just now");
    expect(timeAgo("2026-10-06T10:00:00Z", now)).toMatch(/2 hours ago/);
  });

  it("scores passwords", () => {
    expect(passwordStrength("")).toBe(0);
    expect(passwordStrength("short")).toBe(1);
    expect(passwordStrength("twelve-chars")).toBe(2);
    expect(passwordStrength("correct horse battery staple")).toBe(4);
  });
});
