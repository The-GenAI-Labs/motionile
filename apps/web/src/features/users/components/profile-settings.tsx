"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { DownloadIcon, MailIcon, PhoneIcon, ShieldAlertIcon, Trash2Icon } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { OtpInput } from "@/features/auth/components/otp-input";
import { usePublicSettings } from "@/features/platform/hooks/use-flags";
import { AvatarUpload } from "@/features/users/components/avatar-upload";
import {
  useAddContact,
  useConfirmDeletion,
  useRemoveAvatar,
  useRemoveContact,
  useRequestDeletion,
  useRequestExport,
  useSetPrimaryContact,
  useUpdatePreferences,
  useUpdateProfile,
  useUploadAvatar,
  useUserPreferences,
  useUserProfile,
  useVerifyContact,
} from "@/features/users/hooks/use-user-settings";
import { profileFormSchema, type ProfileFormValues } from "@/features/users/schemas/profile.schema";
import { expireSession } from "@/lib/auth/session-expiry";

const stringOptions = (value: unknown, fallback: string[]) =>
  Array.isArray(value) && value.every((item) => typeof item === "string") ? value : fallback;

export function ProfileSettings() {
  const profile = useUserProfile();
  const preferences = useUserPreferences();
  const settings = usePublicSettings();
  const updateProfile = useUpdateProfile();
  const uploadAvatar = useUploadAvatar();
  const removeAvatar = useRemoveAvatar();
  const addContact = useAddContact();
  const verifyContact = useVerifyContact();
  const setPrimary = useSetPrimaryContact();
  const removeContact = useRemoveContact();
  const updatePreferences = useUpdatePreferences();
  const requestExport = useRequestExport();
  const requestDeletion = useRequestDeletion();
  const confirmDeletion = useConfirmDeletion();
  const [identifier, setIdentifier] = useState("");
  const [challenge, setChallenge] = useState<{ token: string; destination: string } | null>(null);
  const [contactCode, setContactCode] = useState("");
  const [deletionChallenge, setDeletionChallenge] = useState<{
    token: string;
    destination: string;
  } | null>(null);
  const [deletionCode, setDeletionCode] = useState("");
  const form = useForm<ProfileFormValues>({
    resolver: zodResolver(profileFormSchema),
    values: { name: profile.data?.name ?? "" },
  });
  if (profile.isPending || preferences.isPending) return <p role="status">Loading profile…</p>;
  if (profile.isError || preferences.isError)
    return (
      <p role="alert" className="text-destructive">
        Your profile could not be loaded.
      </p>
    );
  const settingValues = settings.data?.settings ?? {};
  const optionMap = {
    defaultStyle: stringOptions(settingValues["preferences.styles"], [
      "minimal",
      "cinematic",
      "playful",
    ]),
    pace: stringOptions(settingValues["preferences.paces"], ["slow", "normal", "fast"]),
    language: stringOptions(settingValues["preferences.languages"], ["en"]),
    depth: stringOptions(settingValues["preferences.depths"], ["overview", "standard", "deep"]),
    defaultAspect: stringOptions(settingValues["preferences.aspects"], ["16:9", "9:16", "1:1"]),
  };
  const savePreferences = (
    field: keyof typeof optionMap | "captionsEnabled",
    value: string | boolean,
  ) => {
    updatePreferences.mutate({
      defaultStyle: preferences.data.defaultStyle,
      pace: preferences.data.pace,
      language: preferences.data.language,
      depth: preferences.data.depth,
      defaultAspect: preferences.data.defaultAspect,
      captionsEnabled: preferences.data.captionsEnabled,
      defaultVoiceId: preferences.data.defaultVoiceId,
      [field]: value,
    });
  };
  return (
    <div className="space-y-8">
      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
          <CardDescription>Your name and profile image appear across Motionile.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <AvatarUpload
            name={profile.data.name}
            avatarUrl={profile.data.avatarUrl}
            uploading={uploadAvatar.isPending || removeAvatar.isPending}
            onUpload={(file) => uploadAvatar.mutateAsync(file).then(() => undefined)}
            onRemove={() => removeAvatar.mutateAsync()}
          />
          <Form {...form}>
            <form
              onSubmit={(event) => {
                void form.handleSubmit(async (values) => {
                  await updateProfile.mutateAsync(values);
                  toast.success("Profile updated");
                })(event);
              }}
              className="max-w-xl space-y-4"
            >
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Name</FormLabel>
                    <FormControl>
                      <Input autoComplete="name" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <Button type="submit" disabled={updateProfile.isPending}>
                Save profile
              </Button>
            </form>
          </Form>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Contacts</CardTitle>
          <CardDescription>
            Verified contacts can sign in and receive security notices.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <ul className="space-y-3">
            {profile.data.contacts.map((contact) => (
              <li
                key={contact.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-4"
              >
                <div className="flex items-center gap-3">
                  {contact.kind === "email" ? (
                    <MailIcon aria-hidden="true" />
                  ) : (
                    <PhoneIcon aria-hidden="true" />
                  )}
                  <div>
                    <p>{contact.value}</p>
                    <p className="text-xs text-muted-foreground">
                      {contact.verified ? "Verified" : "Unverified"}
                      {contact.primary ? " · Primary" : ""}
                    </p>
                  </div>
                </div>
                <div className="flex gap-2">
                  {contact.verified && !contact.primary ? (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setPrimary.mutate(contact.id);
                      }}
                    >
                      Make primary
                    </Button>
                  ) : null}
                  <ConfirmDialog
                    title="Remove contact?"
                    description="You must keep at least one verified contact."
                    destructive
                    confirmLabel="Remove"
                    trigger={
                      <Button variant="ghost" size="icon" aria-label={`Remove ${contact.value}`}>
                        <Trash2Icon aria-hidden="true" />
                      </Button>
                    }
                    onConfirm={() => removeContact.mutateAsync(contact.id)}
                  />
                </div>
              </li>
            ))}
          </ul>
          {challenge ? (
            <div className="space-y-3 rounded-lg border p-4">
              <p className="text-sm">Enter the code sent to {challenge.destination}.</p>
              <OtpInput
                value={contactCode}
                onChange={setContactCode}
                onComplete={(code) => {
                  void verifyContact
                    .mutateAsync({ challengeToken: challenge.token, code })
                    .then(() => {
                      setChallenge(null);
                      setContactCode("");
                      toast.success("Contact verified");
                    });
                }}
              />
            </div>
          ) : (
            <div className="flex max-w-xl gap-2">
              <Label htmlFor="contact-identifier" className="sr-only">
                Email address or phone number
              </Label>
              <Input
                id="contact-identifier"
                value={identifier}
                onChange={(event) => {
                  setIdentifier(event.target.value);
                }}
                placeholder="Email address or phone number"
              />
              <Button
                type="button"
                onClick={() => {
                  void addContact.mutateAsync({ identifier }).then((result) => {
                    setChallenge({ token: result.challengeToken, destination: result.destination });
                  });
                }}
              >
                Add contact
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Video preferences</CardTitle>
          <CardDescription>Defaults used when you create a new explainer.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5 md:grid-cols-2">
          {Object.entries(optionMap).map(([field, options]) => (
            <div key={field}>
              <Label htmlFor={`preference-${field}`}>
                {field
                  .replace(/([A-Z])/g, " $1")
                  .replace(/^./, (character) => character.toUpperCase())}
              </Label>
              <select
                id={`preference-${field}`}
                value={preferences.data[field as keyof typeof optionMap] ?? ""}
                onChange={(event) => {
                  savePreferences(field as keyof typeof optionMap, event.target.value);
                }}
                className="mt-1 h-9 w-full rounded-md border bg-surface px-3 text-sm focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
              >
                {options.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </div>
          ))}
          <div className="flex items-center gap-3">
            <Switch
              id="captions-enabled"
              checked={preferences.data.captionsEnabled}
              onCheckedChange={(checked) => {
                savePreferences("captionsEnabled", checked);
              }}
            />
            <Label htmlFor="captions-enabled">Captions enabled</Label>
          </div>
        </CardContent>
      </Card>
      <Card className="border-destructive/50">
        <CardHeader>
          <CardTitle>Danger zone</CardTitle>
          <CardDescription>Export your data or request permanent account deletion.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h3 className="font-medium">Export account data</h3>
              <p className="text-sm text-muted-foreground">
                We will email a download link valid for 24 hours.
              </p>
            </div>
            <Button
              variant="outline"
              onClick={() => {
                requestExport.mutate(undefined, {
                  onSuccess: () => toast.success("Export queued"),
                });
              }}
            >
              <DownloadIcon aria-hidden="true" /> Request export
            </Button>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-4 border-t pt-5">
            <div>
              <h3 className="font-medium text-destructive">Delete account</h3>
              <p className="max-w-xl text-sm text-muted-foreground">
                Deletion signs you out immediately. You can contact support to restore the account
                within 30 days; after that it is permanently purged.
              </p>
            </div>
            <Button
              variant="destructive"
              onClick={() => {
                void requestDeletion.mutateAsync().then((result) => {
                  setDeletionChallenge({
                    token: result.challengeToken,
                    destination: result.destination,
                  });
                });
              }}
            >
              <ShieldAlertIcon aria-hidden="true" /> Delete account
            </Button>
          </div>
          {deletionChallenge ? (
            <div className="space-y-3 rounded-lg border border-destructive/50 p-4">
              <p>Enter the code sent to {deletionChallenge.destination} to confirm deletion.</p>
              <OtpInput value={deletionCode} onChange={setDeletionCode} />
              <Button
                variant="destructive"
                disabled={deletionCode.length !== 6 || confirmDeletion.isPending}
                onClick={() => {
                  void confirmDeletion
                    .mutateAsync({ challengeToken: deletionChallenge.token, code: deletionCode })
                    .then(() => {
                      expireSession();
                    });
                }}
              >
                Permanently delete my account
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
