export type ProfileAccess = {
  enabled: boolean;
  current: boolean;
  elsewhere: boolean;
};

export type Bootstrap = {
  ok: true;
  version: string;
  commit: string;
  boot_id: string;
  lang: "zh" | "en" | string;
  html_lang: string;
  current_profile: string;
  profiles: string[];
  profile_access: Record<string, ProfileAccess>;
  has_machine_profile: boolean;
  paths: { csv: string; screenshots: string; iap: string };
  is_editable: boolean;
};

export function mapRetryPath(path: string | null | undefined): string {
  if (!path) return "/";
  const map: Record<string, string> = {
    "/metadata": "/listing",
    "/profiles": "/system/profiles",
    "/guard": "/system/guard",
    "/settings": "/system/settings",
    "/update": "/system/update",
  };
  return map[path] ?? path;
}
