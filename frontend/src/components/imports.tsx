import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Import, ImportStatus } from "../api/types";
import { Badge } from "./ui";

export const importsKey = ["imports"] as const;

export function useImports() {
  return useQuery({ queryKey: importsKey, queryFn: () => api<Import[]>("GET", "/api/imports") });
}

export function ImportStatusBadge({ status }: { status: ImportStatus }) {
  if (status === "ready") return <Badge tone="amber">Ready to review</Badge>;
  if (status === "accepted") return <Badge tone="green">Saved</Badge>;
  if (status === "failed") return <Badge tone="red">Failed</Badge>;
  return <Badge tone="brand">Importing…</Badge>;
}
