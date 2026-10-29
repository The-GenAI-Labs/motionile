"use client";

import { useState } from "react";

import { ReseedControl, ReseedReportView } from "@/features/admin-skills/components/reseed-control";
import { SkillsTable } from "@/features/admin-skills/components/skills-table";
import type { ReseedReport } from "@/features/admin-skills/types/admin-skills.types";

export function SkillsOverview() {
  const [report, setReport] = useState<ReseedReport | null>(null);
  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <ReseedControl onReseeded={setReport} />
      </div>
      {report === null ? null : <ReseedReportView report={report} />}
      <SkillsTable />
    </div>
  );
}
