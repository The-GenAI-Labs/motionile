import { readFileSync } from "node:fs";
import { request } from "node:http";
import { createServer } from "node:https";

const certificateDirectory = process.argv[2];
if (!certificateDirectory) throw new Error("A certificate directory is required");

createServer(
  {
    key: readFileSync(`${certificateDirectory}/key.pem`),
    cert: readFileSync(`${certificateDirectory}/cert.pem`),
  },
  (incoming, outgoing) => {
    const port = incoming.url?.startsWith("/v1/") ? 8000 : 3000;
    const upstream = request(
      {
        hostname: "127.0.0.1",
        port,
        path: incoming.url,
        method: incoming.method,
        headers: { ...incoming.headers, "x-forwarded-proto": "https" },
      },
      (response) => {
        outgoing.writeHead(response.statusCode ?? 502, response.headers);
        response.pipe(outgoing);
      },
    );
    upstream.on("error", () => {
      outgoing.writeHead(502);
      outgoing.end();
    });
    incoming.pipe(upstream);
  },
).listen(3443, "127.0.0.1");
