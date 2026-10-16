import { SecuritySettings } from "@/features/auth/components/security-settings";
import { buildMetadata } from "@/lib/seo/metadata";
export const metadata = buildMetadata({
  title: "Security",
  description: "Manage your Motionile password, linked accounts and active sessions.",
  path: "/settings/security",
  noIndex: true,
});
export default function SecurityPage() {
  return <SecuritySettings />;
}
