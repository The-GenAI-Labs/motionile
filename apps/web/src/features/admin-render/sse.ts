export interface SseFrame {
  event: string;
  data: string;
}

export interface SseParser {
  push: (chunk: string) => void;
  flush: () => void;
}

const DEFAULT_EVENT = "message";

export const createSseParser = (onFrame: (frame: SseFrame) => void): SseParser => {
  let buffer = "";
  let event = DEFAULT_EVENT;
  let data: string[] = [];

  const dispatch = (): void => {
    if (data.length > 0) {
      onFrame({ event, data: data.join("\n") });
    }
    event = DEFAULT_EVENT;
    data = [];
  };

  const handleLine = (line: string): void => {
    if (line === "") {
      dispatch();
      return;
    }
    if (line.startsWith(":")) {
      return;
    }
    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    const raw = separator === -1 ? "" : line.slice(separator + 1);
    const value = raw.startsWith(" ") ? raw.slice(1) : raw;
    if (field === "event") {
      event = value === "" ? DEFAULT_EVENT : value;
    } else if (field === "data") {
      data.push(value);
    }
  };

  const drain = (final: boolean): void => {
    const lines = buffer.split(/\r\n|\n|\r/);
    buffer = final ? "" : (lines.pop() ?? "");
    for (const line of lines) {
      handleLine(line);
    }
  };

  return {
    push: (chunk) => {
      buffer += chunk;
      drain(false);
    },
    flush: () => {
      drain(true);
      dispatch();
    },
  };
};
