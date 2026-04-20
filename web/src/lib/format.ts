import type { AuthStatus, BatchDetail, BatchItem, BatchStats } from "@/lib/api";

export function statusLabel(status: string) {
  const labels: Record<string, string> = {
    queued: "Queued",
    downloading: "Downloading",
    completed: "Completed",
    completed_with_errors: "Completed With Errors",
    failed: "Failed",
    unsupported: "Unsupported",
    running: "Running",
    cancelling: "Stopping",
    cancelled: "Cancelled",
  };

  return labels[status] ?? status;
}

export function accessModeLabel(mode: string) {
  const labels: Record<string, string> = {
    browser_session: "Browser Session",
    private_google_oauth: "Google Auth",
    public_link: "Public Link",
  };
  return labels[mode] ?? mode;
}

export function qualityLabel(quality: string) {
  if (quality === "auto") {
    return "Auto";
  }
  return `Up To ${quality}p`;
}

export function formatDateTime(value: string | null) {
  if (!value) {
    return "N/A";
  }

  const date = new Date(value);
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatCount(value: number) {
  return new Intl.NumberFormat().format(value);
}

export function progressRatio(stats: BatchStats) {
  if (stats.supported_total <= 0) {
    return 0;
  }

  const settled =
    stats.completed + stats.failed + stats.cancelled + stats.unsupported;
  return Math.min(100, Math.round((settled / stats.supported_total) * 100));
}

export function batchPrimaryMessage(batch: BatchDetail | null) {
  if (!batch) {
    return "Preview a sheet or pick a batch to inspect its live queue.";
  }

  if (batch.status === "completed_with_errors") {
    return "Some items need attention. Review the failed rows and retry only what matters.";
  }

  if (batch.status === "completed") {
    return "This batch is done. Open the folder or inspect any row for its final output path.";
  }

  if (batch.status === "running") {
    return "Downloads are in flight. This panel updates automatically while the worker runs.";
  }

  if (batch.status === "cancelled") {
    return "The batch was stopped before every supported item finished.";
  }

  return "This batch is ready to run. Review settings and queue details before continuing.";
}

export function authSummary(status: AuthStatus | null) {
  if (!status) {
    return "Checking local browser session…";
  }

  if (status.authenticated) {
    return `Connected via ${status.browser ?? "browser"} session.`;
  }

  if (status.message) {
      return status.message;
  }

  if (!status.dependencies_ready) {
    return "Browser cookie access is not ready on this machine.";
  }

  return "Google session not ready yet.";
}

export function itemStatusTone(item: BatchItem) {
  if (item.status === "completed") {
    return "success";
  }
  if (item.status === "failed" || item.status === "unsupported") {
    return "danger";
  }
  if (item.status === "downloading") {
    return "active";
  }
  return "neutral";
}
