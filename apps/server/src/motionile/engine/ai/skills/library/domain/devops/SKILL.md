---
name: devops
description: Explaining how software is built, shipped and operated - CI/CD pipelines, containers and Docker images, Kubernetes pods and deployments, infrastructure as code, deployment strategies (rolling, blue-green, canary), monitoring with metrics, logs and traces, SLOs and error budgets, incident response and rollbacks. Use for the path from a commit to running production software and keeping it healthy, not for application code design or large-scale data architecture.
metadata:
  layer: domain
---

# DevOps and operations

## When to use

Topics about pipelines, packaging, runtime platforms, environments, releases, observability and reliability practice. Audience: developers new to operations, students, and engineers moving into platform or SRE roles. Tooling changes fast: teach the problem and the mechanism, give tool names only as examples, and state versions when behavior depends on them.

## Structure

1. Start with the pain: "it works on my machine", a manual release at midnight, a deploy that took the site down.
2. Show the manual process as a line of steps, then which steps get automated and what each step guards against.
3. Introduce the artifact that moves through the pipeline (an image, a build) and stress that the same artifact is promoted from environment to environment.
4. Show a failure and the safety net: failed test stops the release, failing health check stops the rollout, a rollback restores the previous version.
5. Close on what is measured: deployment frequency, lead time, change failure rate, time to restore.

## Analogies and where they break

- Container as a shipping container: same box runs anywhere. Breaks: containers share the host kernel, so a Linux image does not run unchanged on a different kernel family.
- Image versus container as recipe versus cooked meal, or class versus instance. Breaks: many containers can start from one image and the image is read-only layers.
- Kubernetes as an airport control tower keeping the desired schedule. Breaks: it works by repeated reconciliation of desired versus actual state, not by issuing one-time commands.
- Pipeline as an assembly line with quality gates. Breaks: stages can run in parallel and a failed gate can be retried.
- Infrastructure as code as a blueprint plus a builder. Breaks: real infrastructure can drift from the blueprint when someone edits it by hand.
- Canary release as the canary in a coal mine. Breaks: the canary is a small share of real traffic, not a test environment.

## Misconceptions to preempt

- "A container is a lightweight virtual machine." A container is an isolated process using kernel namespaces and cgroups; a VM runs its own kernel.
- "Docker and Kubernetes are alternatives." Docker builds and runs containers; Kubernetes orchestrates containers across machines.
- "DevOps is a tool or a job title." It is a practice of shared ownership between building and running software.
- "CI/CD is one thing." Continuous integration merges and tests often; continuous delivery keeps every change releasable; continuous deployment releases every passing change automatically.
- "Monitoring and observability are the same." Monitoring watches known signals; observability is being able to ask new questions from metrics, logs and traces.
- "Aim for 100 percent uptime." Each extra nine costs more; an SLO sets the target and an error budget allows change.
- "Rollback is always safe." Database migrations and external side effects may not be reversible.

## Terminology

Say pipeline, stage, job, runner, artifact, registry, image, layer, tag versus digest, container, pod, node, cluster, deployment, service, ingress, namespace, manifest, replica, health check (liveness versus readiness), rollout, rollback, environment (dev, staging, production), secret, state file, drift. Metrics, logs and traces are the three telemetry signals. SLI is the measurement, SLO the target, SLA the contract with consequences. Avoid "server" for a container and "deploy" for "commit".

## Visual pairings

- flow-diagram: the pipeline from commit to production, a rollout with a health check.
- architecture-build-up: cluster layers, control plane and nodes, registry plus runner.
- timeline-sequence: a release across environments, an incident from alert to resolution.
- comparison-split: rolling versus blue-green versus canary, VM versus container.
- code-walkthrough: a short Dockerfile or pipeline file, a declarative manifest.
- data-chart-story: error budget burn, deployment frequency before and after.

## Accuracy checks

- Availability arithmetic: 99.9 percent allows about 8.8 hours a year (about 43 minutes a month); 99.99 percent about 53 minutes a year. A budget of 0.1 percent errors is not the same as 0.1 percent downtime.
- Image layers are cached by instruction order; changing an early instruction invalidates later layers.
- A tag can move; a digest is immutable.
- Kubernetes restarts a failed container and reschedules pods, but does not fix a crash loop caused by a bug.
- Secrets belong in a secret store or injected at runtime, never baked into an image or committed. Show only obviously fake values.
- Mark any version, default or flag as version-specific rather than universal.

## Do

- Show the artifact and the environment it is in at every step.
- Show what stops a bad change, not only the happy path.
- Use plain commands or a few lines of configuration, never a wall of YAML.

## Don't

- Don't claim one cloud or tool is the standard.
- Don't imply automation removes the need for review or monitoring.
- Don't show real hostnames, tokens or account identifiers.
