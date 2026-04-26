export type SequenceRangeMode = "all" | "range";

export type SequenceRangePayload = {
  sequenceStart?: number;
  sequenceEnd?: number;
};

function parsePositiveInteger(value: string, label: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }

  if (!/^\d+$/.test(trimmed)) {
    throw new Error(`${label} phải là số nguyên dương.`);
  }

  const parsed = Number(trimmed);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${label} phải lớn hơn 0.`);
  }

  return parsed;
}

export function resolveSequenceRangeInput(
  mode: SequenceRangeMode,
  startText: string,
  endText: string,
): SequenceRangePayload {
  if (mode !== "range") {
    return {};
  }

  const sequenceStart = parsePositiveInteger(startText, "STT bắt đầu");
  const sequenceEnd = parsePositiveInteger(endText, "STT kết thúc");

  if (sequenceStart === null && sequenceEnd === null) {
    throw new Error("Hãy nhập ít nhất một mốc STT để lọc theo khoảng.");
  }

  if (
    sequenceStart !== null &&
    sequenceEnd !== null &&
    sequenceStart > sequenceEnd
  ) {
    throw new Error("STT bắt đầu không được lớn hơn STT kết thúc.");
  }

  return {
    ...(sequenceStart !== null ? { sequenceStart } : {}),
    ...(sequenceEnd !== null ? { sequenceEnd } : {}),
  };
}
