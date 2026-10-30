import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useJobEvents } from "@/features/generation/hooks/use-job-events";
import { generationKeys } from "@/features/generation/query-keys";
import type { JobEvent } from "@/features/generation/schemas/generation.schema";
import { useJobUiStore } from "@/features/generation/store/job-ui.store";
import type { Job } from "@/features/generation/types/generation.types";

import { event, job, JOB_ID } from "./generation-fixtures";
import { makeTestQueryClient } from "./render-with-query";

interface StreamOptions {
  headers: Record<string, string>;
  credentials: string;
  fetch: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
  onopen: (response: Response) => Promise<void>;
  onmessage: (message: { id: string; event: string; data: string }) => void;
  onclose: () => void;
  onerror: (error: unknown) => number | undefined;
  signal: AbortSignal;
}

const sse = vi.hoisted(() => ({
  options: null as StreamOptions | null,
  settle: null as { resolve: () => void; reject: (error: unknown) => void } | null,
  fetchEventSource: vi.fn(),
}));
const refresh = vi.hoisted(() => ({ refreshSession: vi.fn() }));

vi.mock("@microsoft/fetch-event-source", () => ({ fetchEventSource: sse.fetchEventSource }));
vi.mock("@/lib/auth/refresh", () => refresh);

const streamResponse = () =>
  new Response(null, { status: 200, headers: { "content-type": "text/event-stream" } });

const problemResponse = (status: number) =>
  new Response(
    JSON.stringify({
      type: "urn:motionile:problem:x",
      title: "Problem",
      status,
      code: "problem",
    }),
    { status, headers: { "content-type": "application/problem+json" } },
  );

const options = (): StreamOptions => {
  if (sse.options === null) {
    throw new Error("The stream was not opened.");
  }
  return sse.options;
};

const frame = (kind: "snapshot" | "job_event", body: object, id = "") => ({
  id,
  event: kind,
  data: JSON.stringify(body),
});

const mount = (client = makeTestQueryClient()) => {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook(
    () => {
      useJobEvents(JOB_ID, { enabled: true });
    },
    { wrapper },
  );
  return { client, ...hook };
};

beforeEach(() => {
  vi.clearAllMocks();
  sse.options = null;
  useJobUiStore.getState().reset();
  sse.fetchEventSource.mockImplementation((_url: string, opened: StreamOptions) => {
    sse.options = opened;
    return new Promise<void>((resolve, reject) => {
      sse.settle = { resolve, reject };
    });
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useJobEvents", () => {
  it("opens the stream with the session cookie and writes snapshot and events to the cache", async () => {
    const { client } = mount();
    expect(sse.fetchEventSource).toHaveBeenCalledWith(
      expect.stringContaining(`/v1/jobs/${JOB_ID}/events`),
      expect.objectContaining({ credentials: "include" }),
    );
    await options().onopen(streamResponse());
    expect(useJobUiStore.getState().connections[JOB_ID]).toBe("live");

    options().onmessage(frame("snapshot", job({ status: "planning" })));
    expect(client.getQueryData<Job>(generationKeys.job(JOB_ID))?.status).toBe("planning");

    const started = event("stage.started", { stage: "voice" }, 1, "voice");
    options().onmessage(frame("job_event", started, started.id ?? ""));
    options().onmessage(frame("job_event", started, started.id ?? ""));
    expect(client.getQueryData<JobEvent[]>(generationKeys.events(JOB_ID))).toHaveLength(1);
    expect(client.getQueryData<Job>(generationKeys.job(JOB_ID))?.status).toBe("voicing");
  });

  it("invalidates the job and stops reconnecting after the terminal event", async () => {
    const { client } = mount();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    await options().onopen(streamResponse());
    options().onmessage(frame("snapshot", job()));
    const done = event("job.completed", { creditsCharged: 100, fallbackSceneIds: [] }, 2);
    options().onmessage(frame("job_event", done, done.id ?? ""));
    expect(client.getQueryData<Job>(generationKeys.job(JOB_ID))?.status).toBe("completed");
    expect(invalidate).toHaveBeenCalledWith({ queryKey: generationKeys.job(JOB_ID) });
    expect(() => {
      options().onclose();
    }).not.toThrow();
  });

  it("treats a close before the terminal event as a failure to retry", async () => {
    mount();
    await options().onopen(streamResponse());
    expect(() => {
      options().onclose();
    }).toThrow();
  });

  it("backs off exponentially, then falls back to polling", async () => {
    mount();
    await options().onopen(streamResponse());
    expect(options().onerror(new TypeError("offline"))).toBe(1000);
    expect(useJobUiStore.getState().connections[JOB_ID]).toBe("reconnecting");
    expect(options().onerror(new TypeError("offline"))).toBe(2000);
    expect(options().onerror(new TypeError("offline"))).toBe(4000);
    expect(() => options().onerror(new TypeError("offline"))).toThrow();
    sse.settle?.reject(new TypeError("offline"));
    await waitFor(() => {
      expect(useJobUiStore.getState().connections[JOB_ID]).toBe("polling");
    });
  });

  it("resets the failure count once a connection opens", async () => {
    mount();
    expect(options().onerror(new TypeError("offline"))).toBe(1000);
    expect(options().onerror(new TypeError("offline"))).toBe(2000);
    await options().onopen(streamResponse());
    expect(options().onerror(new TypeError("offline"))).toBe(1000);
  });

  it("does not retry when the job is gone or the response is not a stream", async () => {
    mount();
    await expect(options().onopen(problemResponse(404))).rejects.toMatchObject({ status: 404 });
    const missing = await options()
      .onopen(problemResponse(404))
      .catch((error: unknown) => error);
    expect(() => options().onerror(missing)).toThrow();
    await expect(options().onopen(new Response("x", { status: 200 }))).rejects.toBeDefined();
  });

  it("sends Last-Event-ID from the last stored event when it reconnects", async () => {
    const fetchMock = vi.fn().mockResolvedValue(streamResponse());
    vi.stubGlobal("fetch", fetchMock);
    const client = makeTestQueryClient();
    const known = event("stage.started", { stage: "plan" }, 5);
    client.setQueryData(generationKeys.events(JOB_ID), [known]);
    mount(client);
    await options().fetch("http://api.test/events", { headers: {} });
    expect(
      new Headers((fetchMock.mock.calls[0] as [string, RequestInit])[1].headers).get(
        "last-event-id",
      ),
    ).toBe(known.id);

    const next = event("scene.voiced", { sceneId: "s1" }, 6);
    options().onmessage(frame("job_event", next, next.id ?? ""));
    await options().fetch("http://api.test/events", { headers: {} });
    expect(
      new Headers((fetchMock.mock.calls[1] as [string, RequestInit])[1].headers).get(
        "last-event-id",
      ),
    ).toBe(next.id);
  });

  it("refreshes the session once on a 401 and retries the request", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(problemResponse(401))
      .mockResolvedValueOnce(streamResponse());
    vi.stubGlobal("fetch", fetchMock);
    refresh.refreshSession.mockResolvedValue(undefined);
    mount();
    const response = await options().fetch("http://api.test/events", { headers: {} });
    expect(response.status).toBe(200);
    expect(refresh.refreshSession).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not open a stream when it is disabled or already finished", () => {
    const client = makeTestQueryClient();
    client.setQueryData(generationKeys.events(JOB_ID), [event("job.failed", {}, 9)]);
    mount(client);
    expect(sse.fetchEventSource).not.toHaveBeenCalled();
  });

  it("aborts the stream and clears the connection on unmount", async () => {
    const { unmount } = mount();
    await options().onopen(streamResponse());
    const { signal } = options();
    unmount();
    expect(signal.aborted).toBe(true);
    expect(useJobUiStore.getState().connections[JOB_ID]).toBeUndefined();
  });
});
