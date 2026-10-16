export type AuthMessage = "signed-in" | "signed-out" | "expired" | "refreshed";

const messages = new Set<string>(["signed-in", "signed-out", "expired", "refreshed"]);
const listeners = new Set<(message: AuthMessage) => void>();
let channel: BroadcastChannel | undefined;

const getChannel = (): BroadcastChannel | undefined => {
  if (typeof window === "undefined" || typeof BroadcastChannel === "undefined") return undefined;
  if (!channel) {
    channel = new BroadcastChannel("mo-auth");
    channel.onmessage = (event: MessageEvent<unknown>) => {
      if (typeof event.data === "string" && messages.has(event.data)) {
        for (const listener of listeners) listener(event.data as AuthMessage);
      }
    };
  }
  return channel;
};

export const subscribeAuth = (listener: (message: AuthMessage) => void): (() => void) => {
  getChannel();
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

export const broadcastAuth = (message: AuthMessage): void => {
  getChannel()?.postMessage(message);
  if (message === "refreshed") {
    for (const listener of listeners) listener(message);
  }
};
