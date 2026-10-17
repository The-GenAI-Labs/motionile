"use client";

import { SchemaSettingForm } from "@/features/platform/components/schema-setting-form";
import { useAdminSettings, useUpdateSetting } from "@/features/platform/hooks/use-admin-platform";
import { ApiError } from "@/lib/api/api-error";

export function SettingsManager() {
  const settings = useAdminSettings();
  const update = useUpdateSetting();
  if (settings.isPending) return <p role="status">Loading settings…</p>;
  if (settings.isError)
    return (
      <p role="alert" className="text-destructive">
        Settings could not be loaded.
      </p>
    );
  return (
    <div className="space-y-4">
      {settings.data.map((setting) => (
        <SchemaSettingForm
          key={setting.key}
          setting={{
            key: setting.key,
            description: setting.description,
            value: setting.value,
            schema: setting.schema,
            version: setting.version,
          }}
          conflict={update.error instanceof ApiError && update.error.status === 409}
          onSave={(value, version) =>
            update.mutateAsync({ key: setting.key, value, version }).then(() => undefined)
          }
        />
      ))}
    </div>
  );
}
