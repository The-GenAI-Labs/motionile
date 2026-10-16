import { DashboardWelcome } from "@/features/auth/components/dashboard-welcome";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Dashboard",
  description: "Your Motionile workspace.",
  path: "/dashboard",
  noIndex: true,
});

export default function DashboardPage() {
  return <DashboardWelcome />;
}
