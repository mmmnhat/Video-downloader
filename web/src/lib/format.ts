import type { AuthStatus, BatchDetail, BatchItem, BatchStats } from "@/lib/api";

export function statusLabel(status: string) {
  const labels: Record<string, string> = {
    queued: "Đang chờ",
    downloading: "Đang tải",
    completed: "Hoàn tất",
    completed_with_errors: "Hoàn tất kèm lỗi",
    failed: "Thất bại",
    unsupported: "Không hỗ trợ",
    running: "Đang chạy",
    cancelling: "Đang dừng",
    cancelled: "Đã dừng",
  };

  return labels[status] ?? status;
}

export function accessModeLabel(mode: string) {
  const labels: Record<string, string> = {
    browser_session: "Phiên trình duyệt",
    private_google_oauth: "Đăng nhập Google",
    public_link: "Liên kết công khai",
  };
  return labels[mode] ?? mode;
}

export function qualityLabel(quality: string) {
  if (quality === "auto") {
    return "Tự động";
  }
  return `Tối đa ${quality}p`;
}

export function formatDateTime(value: string | null) {
  if (!value) {
    return "Không có";
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
    return "Hãy xem trước sheet hoặc chọn một batch để theo dõi hàng đợi theo thời gian thực.";
  }

  if (batch.status === "completed_with_errors") {
    return "Một số dòng cần xử lý. Hãy xem các dòng lỗi và chỉ chạy lại những dòng cần thiết.";
  }

  if (batch.status === "completed") {
    return "Batch này đã hoàn tất. Mở thư mục hoặc kiểm tra từng dòng để xem đường dẫn đầu ra.";
  }

  if (batch.status === "running") {
    return "Quá trình tải đang diễn ra. Bảng này sẽ tự động cập nhật khi worker chạy.";
  }

  if (batch.status === "cancelled") {
    return "Batch đã bị dừng trước khi mọi mục được hỗ trợ hoàn thành.";
  }

  return "Batch đã sẵn sàng chạy. Hãy kiểm tra cài đặt và thông tin hàng đợi trước khi tiếp tục.";
}

export function authSummary(status: AuthStatus | null) {
  if (!status) {
    return "Đang kiểm tra phiên trình duyệt cục bộ…";
  }

  if (status.authenticated) {
    return `Đã kết nối qua phiên ${status.browser ?? "trình duyệt"}.`;
  }

  if (status.message) {
      return status.message;
  }

  if (!status.dependencies_ready) {
    return "Máy hiện tại chưa sẵn sàng để truy cập cookie trình duyệt.";
  }

  return "Phiên Google chưa sẵn sàng.";
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
