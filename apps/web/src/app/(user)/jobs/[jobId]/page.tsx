import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { z } from "zod";

import { JobView } from "@/features/generation/components/job-view";
import { buildMetadata } from "@/lib/seo/metadata";

interface JobPageProps {
  params: Promise<{ jobId: string }>;
}

const DESCRIPTION =
  "Follow your Motionile video from planning to the finished render, review the storyboard, download the result or revise it.";

export async function generateMetadata({ params }: JobPageProps): Promise<Metadata> {
  const { jobId } = await params;
  return buildMetadata({
    title: "Your video",
    description: DESCRIPTION,
    path: `/jobs/${jobId}`,
    noIndex: true,
  });
}

export default async function JobPage({ params }: JobPageProps) {
  const { jobId } = await params;
  if (!z.uuid().safeParse(jobId).success) {
    notFound();
  }
  return <JobView jobId={jobId} />;
}
