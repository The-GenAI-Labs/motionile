import { Buffer } from "node:buffer";

import type { UploadPart } from "./auth.js";

const SAMPLE_RATE = 16000;
const BYTES_PER_SAMPLE = 2;
const TONE_HZ = 220;
const AMPLITUDE = 8000;
const MPEG_FRAME_BYTES = 417;
const MPEG_FRAME_HEADER = [0xff, 0xfb, 0x90, 0x00];

export const WAV_TYPE = "audio/wav";

const PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==";

export const PNG_BYTES = Buffer.from(PNG_BASE64, "base64");
export const ZIP_BYTES = Buffer.concat([
  Buffer.from([0x50, 0x4b, 0x03, 0x04, 0x14, 0x00, 0x00, 0x00, 0x08, 0x00]),
  Buffer.alloc(64, 0x41),
]);
export const PE_BYTES = Buffer.concat([
  Buffer.from("MZ"),
  Buffer.alloc(62, 0),
  Buffer.from("PE\u0000\u0000"),
  Buffer.alloc(64, 0x90),
]);
export const HTML_BYTES = Buffer.from(
  "<!doctype html><html><body><script>alert(document.domain)</script></body></html>",
);
export const TEXT_BYTES = Buffer.from("this is plain text and not audio at all\n".repeat(40));

export function wavBytes(seconds: number): Buffer {
  const frames = Math.round(seconds * SAMPLE_RATE);
  const pcm = Buffer.alloc(frames * BYTES_PER_SAMPLE);
  for (let index = 0; index < frames; index += 1) {
    const value = Math.round(AMPLITUDE * Math.sin((2 * Math.PI * TONE_HZ * index) / SAMPLE_RATE));
    pcm.writeInt16LE(value, index * BYTES_PER_SAMPLE);
  }
  const format = Buffer.alloc(16);
  format.writeUInt16LE(1, 0);
  format.writeUInt16LE(1, 2);
  format.writeUInt32LE(SAMPLE_RATE, 4);
  format.writeUInt32LE(SAMPLE_RATE * BYTES_PER_SAMPLE, 8);
  format.writeUInt16LE(BYTES_PER_SAMPLE, 12);
  format.writeUInt16LE(16, 14);
  const body = Buffer.concat([Buffer.from("WAVE"), chunk("fmt ", format), chunk("data", pcm)]);
  const header = Buffer.alloc(8);
  header.write("RIFF", 0, "ascii");
  header.writeUInt32LE(body.length, 4);
  return Buffer.concat([header, body]);
}

function chunk(id: string, payload: Buffer): Buffer {
  const header = Buffer.alloc(8);
  header.write(id, 0, "ascii");
  header.writeUInt32LE(payload.length, 4);
  const padding = payload.length % 2 === 0 ? Buffer.alloc(0) : Buffer.alloc(1);
  return Buffer.concat([header, payload, padding]);
}

function synchsafe(value: number): Buffer {
  return Buffer.from([
    (value >> 21) & 0x7f,
    (value >> 14) & 0x7f,
    (value >> 7) & 0x7f,
    value & 0x7f,
  ]);
}

export function mp3WithCoverBytes(): Buffer {
  const picture = Buffer.concat([
    Buffer.from([0x00]),
    Buffer.from("image/png\u0000", "latin1"),
    Buffer.from([0x03, 0x00]),
    PNG_BYTES,
  ]);
  const frameHeader = Buffer.alloc(10);
  frameHeader.write("APIC", 0, "ascii");
  frameHeader.writeUInt32BE(picture.length, 4);
  const tag = Buffer.concat([frameHeader, picture]);
  const id3 = Buffer.concat([
    Buffer.from([0x49, 0x44, 0x33, 0x03, 0x00, 0x00]),
    synchsafe(tag.length),
    tag,
  ]);
  const frame = Buffer.concat([Buffer.from(MPEG_FRAME_HEADER), Buffer.alloc(MPEG_FRAME_BYTES - 4)]);
  return Buffer.concat([id3, ...Array.from({ length: 120 }, () => frame)]);
}

export function upload(buffer: Buffer, name = "recording.wav", mimeType = WAV_TYPE): UploadPart {
  return { name, mimeType, buffer };
}
