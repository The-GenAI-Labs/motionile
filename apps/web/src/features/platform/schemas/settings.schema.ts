import { z } from "zod";

export const jsonSchemaDefinitionSchema = z.object({
  type: z.enum(["string", "number", "integer", "boolean", "array"]),
  enum: z.array(z.union([z.string(), z.number(), z.boolean()])).optional(),
  minimum: z.number().optional(),
  maximum: z.number().optional(),
});

export const validateSettingValue = (
  schema: z.infer<typeof jsonSchemaDefinitionSchema>,
  value: unknown,
): boolean => {
  if (schema.enum?.includes(value as never) === false) {
    return false;
  }
  if (schema.type === "boolean") {
    return typeof value === "boolean";
  }
  if (schema.type === "number" || schema.type === "integer") {
    if (typeof value !== "number" || (schema.type === "integer" && !Number.isInteger(value))) {
      return false;
    }
    return (
      (schema.minimum === undefined || value >= schema.minimum) &&
      (schema.maximum === undefined || value <= schema.maximum)
    );
  }
  if (schema.type === "array") {
    return Array.isArray(value);
  }
  return typeof value === "string";
};
