import { RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import { Field, FieldGroup } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  chooseBrowser,
  getBrowserConfig,
  probeBrowserProfiles,
  updateBrowserConfig,
  type BrowserConfigPayload,
  type BrowserProfileProbeResult,
  type FeatureBrowserConfig,
} from "@/lib/api";
import { TooltipFieldLabel } from "@/components/ui/tooltip-field-label";


type FeatureKey = "downloader" | "tts" | "story";

type ProbeState = {
  loading: boolean;
  result: BrowserProfileProbeResult | null;
  error: string;
};

const FEATURE_META: Array<{
  key: FeatureKey;
  title: string;
}> = [
  {
    key: "downloader",
    title: "Tải video",
  },
  {
    key: "tts",
    title: "TTS",
  },
  {
    key: "story",
    title: "Tạo ảnh AI",
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
  return error instanceof Error ? error.message : "Yêu cầu thất bại.";
}

export default function BrowserProfilesSettings() {
  const [loading, setLoading] = useState(true);
  const [pickingFeature, setPickingFeature] = useState<FeatureKey | null>(null);
  const [savedConfig, setSavedConfig] = useState<BrowserConfigPayload>(EMPTY_CONFIG);
  const [draftConfig, setDraftConfig] = useState<BrowserConfigPayload>(EMPTY_CONFIG);
  const [probes, setProbes] = useState<Record<FeatureKey, ProbeState>>({
    downloader: { loading: false, result: null, error: "" },
    tts: { loading: false, result: null, error: "" },
    story: { loading: false, result: null, error: "" },
  });
  const timersRef = useRef<Partial<Record<FeatureKey, number>>>({});
  const saveTimerRef = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
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
      for (const timer of Object.values(timersRef.current)) {
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
      if (!config.browser_path.trim() || probe.loading || probe.result || probe.error) {
        continue;
      }
      scheduleProbe(feature, config);
    }
  }, [draftConfig, loading, probes]);

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

  async function runProbe(feature: FeatureKey, config: FeatureBrowserConfig) {
    const browserPath = config.browser_path.trim();
    if (!browserPath) {
      setProbes((current) => ({
        ...current,
        [feature]: { loading: false, result: null, error: "" },
      }));
      return;
    }

    setProbes((current) => ({
      ...current,
      [feature]: { ...current[feature], loading: true, error: "" },
    }));

    try {
      const result = await probeBrowserProfiles(
        feature,
        browserPath,
        config.profile_name,
      );
      setProbes((current) => ({
        ...current,
        [feature]: { loading: false, result, error: "" },
      }));
      setDraftConfig((current) => {
        const next = cloneConfig(current);
        const currentProfile = next[feature].profile_name;
        const hasCurrent = result.profiles.some(
          (profile) => profile.name === currentProfile,
        );
        next[feature].profile_name = hasCurrent
          ? currentProfile
          : result.selectedProfileName;
        return next;
      });
    } catch (error) {
      setProbes((current) => ({
        ...current,
        [feature]: {
          loading: false,
          result: null,
          error: getErrorMessage(error),
        },
      }));
    }
  }

  function scheduleProbe(feature: FeatureKey, config: FeatureBrowserConfig) {
    const existing = timersRef.current[feature];
    if (existing) {
      window.clearTimeout(existing);
    }
    timersRef.current[feature] = window.setTimeout(() => {
      void runProbe(feature, config);
    }, 450);
  }

  function handleProfileChange(feature: FeatureKey, profileName: string) {
    setDraftConfig((current) => {
      const next = cloneConfig(current);
      next[feature].profile_name = profileName;
      return next;
    });
  }

  async function handlePickBrowser(feature: FeatureKey) {
    setPickingFeature(feature);
    try {
      const payload = await chooseBrowser();
      const browserPath = payload.path ?? "";
      setDraftConfig((current) => {
        const next = cloneConfig(current);
        next[feature].browser_path = browserPath;
        next[feature].profile_name = "";
        return next;
      });
      await runProbe(feature, {
        browser_path: browserPath,
        profile_name: "",
      });
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setPickingFeature(null);
    }
  }

  return (
    <div className="space-y-6">
      {FEATURE_META.map((featureMeta) => {
        const feature = featureMeta.key;
        const config = draftConfig[feature];
        const probe = probes[feature];
        const profileOptions = probe.result?.profiles ?? [];

        return (
          <Card
            key={feature}
            className="border-border/70 shadow-[0_24px_90px_rgba(15,23,42,0.08)]"
          >
            <CardContent className="space-y-4">
              <div className="text-sm font-medium leading-none">{featureMeta.title}</div>
              <FieldGroup>
                <Field>
                  <TooltipFieldLabel tooltip="Chọn ứng dụng trình duyệt sẽ dùng cho khu vực này. App sẽ tự quét danh sách profile từ đường dẫn đã chọn.">
                    Đường dẫn trình duyệt
                  </TooltipFieldLabel>
                  <div className="flex gap-2">
                    <Input
                      value={config.browser_path}
                      readOnly
                      placeholder={
                        navigator.platform.includes("Mac")
                          ? "Chọn tệp .app của trình duyệt"
                          : "Chọn tệp .exe của trình duyệt"
                      }
                      autoComplete="off"
                      spellCheck={false}
                    />
                    <Button
                      variant="outline"
                      onClick={() => void handlePickBrowser(feature)}
                      disabled={pickingFeature === feature}
                    >
                      {pickingFeature === feature ? "Đang chọn..." : "Chọn"}
                    </Button>
                  </div>
                </Field>

                <Field>
                  <TooltipFieldLabel tooltip="Chọn profile cookie sẽ dùng cho khu vực này sau khi app quét được từ trình duyệt.">
                    Profile
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
                            probe.loading
                              ? "Đang quét profile..."
                              : "Nhập browser path để hiện profile"
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
                    {config.browser_path && (
                      <Button
                        variant="outline"
                        size="icon"
                        className="shrink-0"
                        onClick={() => void runProbe(feature, config)}
                        disabled={probe.loading}
                        title="Quét lại profile"
                      >
                        <RefreshCw className={`h-4 w-4 ${probe.loading ? "animate-spin" : ""}`} />
                      </Button>
                    )}
                  </div>
                </Field>
              </FieldGroup>

              {probe.error ? (
                <Alert variant="destructive">
                  <AlertTitle>Không quét được profile</AlertTitle>
                  <AlertDescription>{probe.error}</AlertDescription>
                </Alert>
              ) : null}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
