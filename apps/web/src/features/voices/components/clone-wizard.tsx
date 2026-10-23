"use client";

import { useEffect, useRef } from "react";

import { ConsentRecordingStep } from "@/features/voices/components/consent-recording-step";
import { ConsentStep } from "@/features/voices/components/consent-step";
import { DetailsStep } from "@/features/voices/components/details-step";
import { SamplesStep } from "@/features/voices/components/samples-step";
import { StatusStep } from "@/features/voices/components/status-step";
import {
  useCloneWizardStore,
  type WizardStep,
  wizardSteps,
} from "@/features/voices/store/clone-wizard.store";

const stepTitles = {
  consent: "Consent",
  recording: "Consent recording",
  samples: "Voice samples",
  details: "Name and language",
  status: "Status",
} as const satisfies Record<WizardStep, string>;

export function CloneWizard() {
  const step = useCloneWizardStore((state) => state.step);
  const start = useCloneWizardStore((state) => state.start);
  const submittedVoiceId = useCloneWizardStore((state) => state.submittedVoiceId);
  const reset = useCloneWizardStore((state) => state.reset);
  const heading = useRef<HTMLHeadingElement>(null);
  const previous = useRef<WizardStep>(step);
  const index = wizardSteps.indexOf(step);

  useEffect(() => {
    if (previous.current !== step) {
      previous.current = step;
      heading.current?.focus();
    }
  }, [step]);

  useEffect(
    () => () => {
      reset();
    },
    [reset],
  );

  return (
    <div className="space-y-8">
      <ol aria-label="Cloning steps" className="flex flex-wrap gap-2">
        {wizardSteps.map((name, position) => (
          <li
            key={name}
            aria-current={name === step ? "step" : undefined}
            className={
              name === step
                ? "rounded-full border border-ring bg-elevated px-3 py-1 text-xs font-medium"
                : "rounded-full border px-3 py-1 text-xs text-muted-foreground"
            }
          >
            {`${String(position + 1)}. ${stepTitles[name]}`}
            {position < index ? <span className="sr-only"> (done)</span> : null}
          </li>
        ))}
      </ol>
      <section aria-labelledby="wizard-step-heading" className="space-y-6">
        <h2
          id="wizard-step-heading"
          ref={heading}
          tabIndex={-1}
          className="text-2xl font-semibold tracking-tight outline-none focus-visible:ring-[3px] focus-visible:ring-ring"
        >
          {`Step ${String(index + 1)} of ${String(wizardSteps.length)}: ${stepTitles[step]}`}
        </h2>
        {step === "consent" || start === null ? <ConsentStep /> : null}
        {step === "recording" && start !== null ? <ConsentRecordingStep start={start} /> : null}
        {step === "samples" && start !== null ? <SamplesStep start={start} /> : null}
        {step === "details" && start !== null ? <DetailsStep start={start} /> : null}
        {step === "status" && submittedVoiceId !== null ? (
          <StatusStep voiceId={submittedVoiceId} />
        ) : null}
      </section>
    </div>
  );
}
