import { apiUrl, encodePath } from "../../utils/api";
import type {
  AudioRow,
  GeneratedSplitGroup,
  GroupedLabel,
} from "./types";

const SPLIT_ORDER = ["train", "val", "test", "input"];

function sortSplit(a: string, b: string) {
  const ai = SPLIT_ORDER.indexOf(a);
  const bi = SPLIT_ORDER.indexOf(b);

  if (ai !== -1 || bi !== -1) {
    if (ai === -1) return 1;
    if (bi === -1) return -1;
    if (ai !== bi) return ai - bi;
  }

  return a.localeCompare(b);
}

export function groupGeneratedRows(rows: AudioRow[]): GeneratedSplitGroup[] {
  const splitMap = new Map<string, Map<string, AudioRow[]>>();

  rows.forEach((row) => {
    const split = row.split ?? "input";
    const label = row.label || "Unlabeled";

    if (!splitMap.has(split)) {
      splitMap.set(split, new Map());
    }

    const labelMap = splitMap.get(split)!;
    if (!labelMap.has(label)) {
      labelMap.set(label, []);
    }

    labelMap.get(label)!.push(row);
  });

  return [...splitMap.entries()]
    .sort(([a], [b]) => sortSplit(a, b))
    .map(([split, labelMap]) => ({
      split,
      total: [...labelMap.values()].reduce((sum, items) => sum + items.length, 0),
      labels: [...labelMap.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([label, items]) => ({
          key: `${split}:${label}`,
          title: label,
          path: `workspace/datasets/output/*/${split}/${label}`,
          count: items.length,
          items,
        })),
    }));
}

export function groupInputRows(rows: AudioRow[]): GroupedLabel[] {
  const labelMap = new Map<string, AudioRow[]>();

  rows.forEach((row) => {
    const label = row.label || "Unlabeled";
    if (!labelMap.has(label)) {
      labelMap.set(label, []);
    }
    labelMap.get(label)!.push(row);
  });

  return [...labelMap.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([label, items]) => ({
      key: label,
      title: label,
      path: `workspace/datasets/input/${label}`,
      count: items.length,
      items,
    }));
}

export function buildAudioSourceUrl(
  path: string,
  source: "generated" | "input",
) {
  return source === "generated"
    ? apiUrl(`/files/${encodePath(path)}`)
    : apiUrl(`/input-files/${encodePath(path)}`);
}
