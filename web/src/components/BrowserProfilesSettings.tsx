import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Field, FieldGroup } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { TooltipFieldLabel } from "@/components/ui/tooltip-field-label";
import {
  chooseBrowser,
  createBrowserProfile,
  deleteBrowserProfile,
  getBrowserConfig,
  probeBrowserProfiles,
  updateBrowserConfig,
  type BrowserConfigPayload,
  type BrowserProfileProbeResult,
  type FeatureBrowserConfig,
} from "@/lib/api";


type FeatureKey = "downloader" | "tts" | "story";

type ProbeState = {
  loading: boolean;
  result: BrowserProfileProbeResult | null;
  error: string;
  requestKey: string;
};

const FEATURE_META: Array<{
  key: FeatureKey;
  title: string;
  description: string;
}> = [
  {
    key: "downloader",
    title: "Tải video",
    description: "Profile Google riêng của app để đọc Google Sheets và lấy cookie tải video.",
  },
  {
    key: "tts",
    title: "Lồng tiếng (TTS)",
    description: "Profile ElevenLabs riêng của app để đăng nhập 1 lần và tái sử dụng.",
  },
  {
    key: "story",
    title: "Tạo ảnh AI",
    description: "Profile Gemini riêng của app để quét Gem và gen ảnh ổn định.",
  },
];

const EMPTY_CONFIG: BrowserConfigPayload = {
  downloader: { browser_path: "", profile_name: "" },
  tts: { browser_path: "", profile_name: "" },
  story: { browser_path: "", profile_name: "" },
};

function cloneConfig(config: BrowserConfigPayload): BrowserConfigPayload {
  return {
    downloader: { ...config.downloader },
    tts: { ...config.tts },
    story: { ...config.story },
  };
}

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Yeu cau that bai.";
}

function emptyProbeState(): ProbeState {
  return {
    loading: false,
    result: null,
    error: "",
    requestKey: "",
  };
}

export default function BrowserProfilesSettings() {
  const [loading, setLoading] = useState(true);
  const [pickingFeature, setPickingFeature] = useState<FeatureKey | null>(null);
  const [creatingFeature, setCreatingFeature] = useState<FeatureKey | null>(null);
  const [deletingFeature, setDeletingFeature] = useState<FeatureKey | null>(null);
  const [savedConfig, setSavedConfig] = useState<BrowserConfigPayload>(EMPTY_CONFIG);
  const [draftConfig, setDraftConfig] = useState<BrowserConfigPayload>(EMPTY_CONFIG);
  const [newProfileNames, setNewProfileNames] = useState<Record<FeatureKey, string>>({
    downloader: "",
    tts: "",
    story: "",
  });
  const [probes, setProbes] = useState<Record<FeatureKey, ProbeState>>({
    downloader: emptyProbeState(),
    tts: emptyProbeState(),
    story: emptyProbeState(),
  });
  const timersRef = useRef<Partial<Record<FeatureKey, number>>>({});
  const saveTimerRef = useRef<number | null>(null);

  const runProbe = useCallback(async (feature: FeatureKey, config: FeatureBrowserConfig) => {
    const requestKey = `${config.browser_path}\n${config.profile_name}`;
    setProbes((current) => ({
      ...current,
      [feature]: { ...current[feature], loading: true, error: "", requestKey },
    }));

    try {
      const result = await probeBrowserProfiles(
        feature,
        config.browser_path.trim(),
        config.profile_name,
      );
      setProbes((current) => ({
        ...current,
        [feature]: { loading: false, result, error: "", requestKey },
      }));
      setDraftConfig((current) => {
        const next = cloneConfig(current);
        const currentProfile = next[feature].profile_name;
        const hasCurrent = result.profiles.some((profile) => profile.name === currentProfile);
        next[feature].profile_name = hasCurrent
          ? currentProfile
          : result.selectedProfileName;
        if (!next[feature].browser_path && result.executablePath) {
          next[feature].browser_path = result.executablePath;
        }
        return next;
      });
    } catch (error) {
      setProbes((current) => ({
        ...current,
        [feature]: {
          loading: false,
          result: null,
          error: getErrorMessage(error),
          requestKey,
        },
      }));
    }
  }, []);

  const scheduleProbe = useCallback((feature: FeatureKey, config: FeatureBrowserConfig) => {
    const existing = timersRef.current[feature];
    if (existing) {
      window.clearTimeout(existing);
    }
    timersRef.current[feature] = window.setTimeout(() => {
      void runProbe(feature, config);
    }, 250);
  }, [runProbe]);

  useEffect(() => {
    let cancelled = false;
    const timers = timersRef.current;
    void (async () => {
      setLoading(true);
      try {
        const config = await getBrowserConfig();
        if (cancelled) {
          return;
        }
        setSavedConfig(cloneConfig(config));
        setDraftConfig(cloneConfig(config));
      } catch (error) {
        toast.error(getErrorMessage(error));
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
      if (saveTimerRef.current) {
        window.clearTimeout(saveTimerRef.current);
      }
      for (const timer of Object.values(timers)) {
        if (timer) {
          window.clearTimeout(timer);
        }
      }
    };
  }, []);

  useEffect(() => {
    if (loading) {
      return;
    }
    for (const feature of FEATURE_META.map((item) => item.key)) {
      const config = draftConfig[feature];
      const probe = probes[feature];
      const requestKey = `${config.browser_path}\n${config.profile_name}`;
      if (probe.loading || probe.requestKey === requestKey) {
        continue;
      }
      scheduleProbe(feature, config);
    }
  }, [draftConfig, loading, probes, scheduleProbe]);

  useEffect(() => {
    if (loading) {
      return;
    }

    const draftSignature = JSON.stringify(draftConfig);
    const savedSignature = JSON.stringify(savedConfig);
    if (draftSignature === savedSignature) {
      return;
    }

    if (saveTimerRef.current) {
      window.clearTimeout(saveTimerRef.current);
    }

    saveTimerRef.current = window.setTimeout(() => {
      const payload = cloneConfig(draftConfig);
      void updateBrowserConfig(payload)
        .then((saved) => {
          setSavedConfig(cloneConfig(saved));
          setDraftConfig((current) =>
            JSON.stringify(current) === JSON.stringify(payload)
              ? cloneConfig(saved)
              : current,
          );
        })
        .catch((error) => {
          toast.error(getErrorMessage(error));
        });
    }, 500);

    return () => {
      if (saveTimerRef.current) {
        window.clearTimeout(saveTimerRef.current);
      }
    };
  }, [draftConfig, loading, savedConfig]);

  function handleProfileChange(feature: FeatureKey, profileName: string) {
    setDraftConfig((current) => {
      const next = cloneConfig(current);
      next[feature].profile_name = profileName;
      return next;
    });
  }

  function handleNewProfileNameChange(feature: FeatureKey, value: string) {
    setNewProfileNames((current) => ({
      ...current,
      [feature]: value,
    }));
  }

  async function handlePickBrowser(feature: FeatureKey) {
    setPickingFeature(feature);
    try {
      const payload = await chooseBrowser();
      const browserPath = payload.path ?? "";
      setDraftConfig((current) => {
        const next = cloneConfig(current);
        next[feature].browser_path = browserPath;
        return next;
      });
      await runProbe(feature, {
        browser_path: browserPath,
        profile_name: draftConfig[feature].profile_name,
      });
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setPickingFeature(null);
    }
  }

  async function handleCreateProfile(feature: FeatureKey) {
    setCreatingFeature(feature);
    try {
      const created = await createBrowserProfile(feature, newProfileNames[feature].trim());
      const nextProfileName = created.profileName?.trim() || draftConfig[feature].profile_name;
      setDraftConfig((current) => {
        const next = cloneConfig(current);
        next[feature].profile_name = nextProfileName;
        return next;
      });
      setNewProfileNames((current) => ({ ...current, [feature]: "" }));
      await runProbe(feature, {
        browser_path: draftConfig[feature].browser_path,
        profile_name: nextProfileName,
      });
      toast.success(`Da tao profile ${nextProfileName}.`);
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setCreatingFeature(null);
    }
  }

  async function handleDeleteProfile(feature: FeatureKey) {
    const profileName = draftConfig[feature].profile_name.trim();
    if (!profileName) {
      return;
    }
    if (!confirm(`Xoa profile ${profileName}? Cookie va session trong profile nay se bi mat.`)) {
      return;
    }

    setDeletingFeature(feature);
    try {
      const result = await deleteBrowserProfile(feature, profileName);
      if (result.config) {
        setSavedConfig(cloneConfig(result.config));
        setDraftConfig(cloneConfig(result.config));
      }
      await runProbe(feature, {
        browser_path: result.config?.[feature].browser_path ?? draftConfig[feature].browser_path,
        profile_name: result.config?.[feature].profile_name ?? "",
      });
      toast.success(`Da xoa profile ${profileName}.`);
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setDeletingFeature(null);
    }
  }

  return (
    <div className="space-y-6">
      {FEATURE_META.map((featureMeta) => {
        const feature = featureMeta.key;
        const config = draftConfig[feature];
        const probe = probes[feature];
        const profileOptions = probe.result?.profiles ?? [];
        const profileCount = profileOptions.length;

        return (
          <Card
            key={feature}
            className="border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)]"
          >
            <CardContent className="space-y-4">
              <div className="space-y-1">
                <TooltipFieldLabel tooltip={featureMeta.description} className="text-sm font-bold uppercase tracking-wider text-muted-foreground">
                  {featureMeta.title}
                </TooltipFieldLabel>
              </div>

              <FieldGroup>
                <Field>
                  <TooltipFieldLabel tooltip="Đường dẫn đến tệp thực thi của trình duyệt (Chrome/Edge/Cốc Cốc). Profile sẽ được lưu riêng biệt trong thư mục dữ liệu của ứng dụng.">
                    Đường dẫn trình duyệt
                  </TooltipFieldLabel>
                  <div className="flex gap-2">
                    <Input
                      value={config.browser_path}
                      readOnly
                      placeholder={
                        navigator.platform.includes("Mac")
                          ? "Chọn file .app của browser"
                          : "Chọn file .exe của browser"
                      }
                      autoComplete="off"
                      spellCheck={false}
                    />
                    <Button
                      variant="outline"
                      onClick={() => void handlePickBrowser(feature)}
                      disabled={pickingFeature === feature}
                      className="h-9 px-4"
                    >
                      {pickingFeature === feature ? "Đang chọn..." : "Chọn"}
                    </Button>
                  </div>
                </Field>

                <Field>
                  <TooltipFieldLabel tooltip="Mỗi tính năng sử dụng một thư mục dữ liệu người dùng (user-data-dir) riêng biệt. Bạn chỉ cần đăng nhập một lần cho mỗi profile.">
                    Profile của ứng dụng
                  </TooltipFieldLabel>
                  <div className="flex gap-2 items-center">
                    <Select
                      value={config.profile_name}
                      onValueChange={(value) => handleProfileChange(feature, value)}
                      disabled={!profileOptions.length}
                    >
                      <SelectTrigger>
                        <SelectValue
                          placeholder={
                            probe.loading ? "Đang tải profile..." : "Chưa có profile"
                          }
                        />
                      </SelectTrigger>
                      <SelectContent>
                        {profileOptions.map((profile) => (
                          <SelectItem key={profile.path} value={profile.name}>
                            {profile.display_name} ({profile.cookie_count})
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      variant="outline"
                      size="icon"
                      className="shrink-0"
                      onClick={() => void runProbe(feature, config)}
                      disabled={probe.loading}
                      title="Làm mới profile"
                    >
                      <RefreshCw className={`h-3.5 w-3.5 ${probe.loading ? "animate-spin" : ""}`} />
                    </Button>
                    <Button
                      variant="outline"
                      size="icon"
                      className="shrink-0"
                      onClick={() => void handleDeleteProfile(feature)}
                      disabled={!config.profile_name || deletingFeature === feature || profileCount <= 1}
                      title={profileCount <= 1 ? "Cần giữ lại ít nhất 1 profile" : "Xóa profile đang chọn"}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </Field>

                <Field>
                  <TooltipFieldLabel tooltip="Tạo thêm profile mới để sử dụng nhiều tài khoản khác nhau. Nếu để trống, hệ thống sẽ tự đặt tên mặc định.">
                    Tạo profile mới
                  </TooltipFieldLabel>
                  <div className="flex gap-2">
                    <Input
                      value={newProfileNames[feature]}
                      onChange={(event) => handleNewProfileNameChange(feature, event.target.value)}
                      placeholder="Ví dụ: Tài khoản chính, Backup 1..."
                      autoComplete="off"
                      spellCheck={false}
                    />
                    <Button
                      variant="outline"
                      onClick={() => void handleCreateProfile(feature)}
                      disabled={creatingFeature === feature}
                      className="h-9 px-4"
                    >
                      <Plus className="mr-2 h-3.5 w-3.5" />
                      {creatingFeature === feature ? "Đang tạo..." : "Tạo"}
                    </Button>
                  </div>
                </Field>
              </FieldGroup>

                <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
                  Profile đang dùng: <span className="text-foreground">{config.profile_name}</span>
                  {probe.result?.selectedProfileDir ? ` · ${probe.result.selectedProfileDir}` : ""}
                </div>

              {probe.error ? (
                <Alert variant="destructive" className="py-2">
                  <AlertTitle className="text-xs">Không tải được profile</AlertTitle>
                  <AlertDescription className="text-[11px] opacity-90">{probe.error}</AlertDescription>
                </Alert>
              ) : null}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
