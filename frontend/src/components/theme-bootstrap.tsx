"use client";

import * as React from "react";

import { applyStoredTheme, getStoredTheme } from "@/lib/theme";

export function ThemeBootstrap() {
  React.useEffect(() => {
    applyStoredTheme(getStoredTheme());
  }, []);

  return null;
}
