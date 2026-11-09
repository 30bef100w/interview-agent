import { notFound } from "next/navigation";
import PreviousOverview from "@/components/admin/PreviousOverview";

export default function BeforeMetricsPage() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <PreviousOverview />;
}
