import { PageHeader } from "@/components/shared/page-header";
import { CreateVideoForm } from "@/features/generation/components/create-video-form";
import { QUERY_MAX_CHARS } from "@/features/generation/schemas/generation.schema";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Create a video",
  description:
    "Turn a topic or a question into a narrated, animated Motionile explainer video. Choose the length, style, voice and aspect ratios, and see the credit cost first.",
  path: "/create",
  noIndex: true,
});

interface CreatePageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

const firstValue = (value: string | string[] | undefined): string | null => {
  const single = Array.isArray(value) ? value[0] : value;
  return single === undefined || single.trim() === "" ? null : single.trim();
};

export default async function CreatePage({ searchParams }: CreatePageProps) {
  const params = await searchParams;
  const topic = firstValue(params["topic"]);
  const query = firstValue(params["query"])?.slice(0, QUERY_MAX_CHARS) ?? "";
  return (
    <div className="space-y-8">
      <PageHeader
        title="Create a video"
        description="Pick a topic or ask your own question. You see the credit cost before anything is spent."
      />
      <CreateVideoForm topicReference={topic} initialQuery={query} />
    </div>
  );
}
