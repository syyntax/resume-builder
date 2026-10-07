import { FileQuestion } from "lucide-react";
import { Link } from "react-router";

import { Card, EmptyState, linkButtonClass } from "../components/ui";

export function NotFoundPage() {
  return (
    <Card className="mx-auto mt-10 max-w-lg">
      <EmptyState icon={<FileQuestion className="size-6" aria-hidden />} title="Page not found">
        <p>That page doesn't exist, or you don't have access to it.</p>
        <Link to="/" className={`${linkButtonClass("secondary", "sm")} mt-4`}>
          Go home
        </Link>
      </EmptyState>
    </Card>
  );
}
