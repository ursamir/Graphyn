import { Handle, Position } from "reactflow";
import { Zap, AlertCircle, Mic, Upload, Trash2, Radio, CheckCircle, HelpCircle } from "lucide-react";
import React from "react";
import { apiUrl } from "../utils/api";

type NodeStatus = "idle" | "running" | "success" | "error";
type CompatState = "idle" | "compatible" | "incompatible";

interface FieldDef {
  type: string;
  default?: unknown;
  description?: string;
  item_type?: string;
}

interface NodeData {
  label: string;
  title?: string;
  kind?: string;
  description?: string;
  preview?: string;
  config?: Record<string, unknown>;
  schema?: Record<string, FieldDef>;
  onConfigChange?: (field: string, value: unknown) => void;
  onMicUpload?: (inputPath: string) => void;
  onDelete?: () => void;
  hasError?: boolean;
  status?: NodeStatus;
  statusError?: string;
  compatState?: CompatState;
  input_type?: string | null;
  output_type?: string | null;
}

async function uploadMicFile(file: File): Promise<string> {
  const fd = new FormData();
  fd.append("file", file);
  const response = await fetch(apiUrl("/mic-upload"), {
    method: "POST",
    body: fd,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Upload failed: ${response.status}`);
  }
  const json = (await response.json()) as { input_path?: string };
  return json.input_path || "workspace/datasets/input/mic";
}

async function uploadMicBlob(blob: Blob): Promise<string> {
  const fd = new FormData();
  fd.append(
    "file",
    new File([blob], "mic-recording.webm", { type: blob.type || "audio/webm" }),
  );
  const response = await fetch(apiUrl("/mic-upload"), {
    method: "POST",
    body: fd,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Upload failed: ${response.status}`);
  }
  const json = (await response.json()) as { input_path?: string };
  return json.input_path || "workspace/datasets/input/mic";
}

function HelpTooltip({ text }: { text: string }) {
  const [visible, setVisible] = React.useState(false);
  const hideTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const show = () => {
    if (hideTimer.current) clearTimeout(hideTimer.current);
    setVisible(true);
  };
  const hide = () => {
    hideTimer.current = setTimeout(() => setVisible(false), 200);
  };

  return (
    <span className="relative inline-block ml-1">
      <HelpCircle
        className="w-3 h-3 text-secondary-400 cursor-help inline"
        onMouseEnter={show}
        onMouseLeave={hide}
      />
      {visible && (
        <span
          className="absolute z-50 left-4 top-0 w-48 bg-secondary-900 text-white text-[10px] rounded-lg px-2 py-1.5 shadow-xl pointer-events-auto"
          onMouseEnter={show}
          onMouseLeave={hide}
        >
          {text}
        </span>
      )}
    </span>
  );
}

interface BaseNodeProps {
  data: NodeData;
  selected?: boolean;
  isConnectable?: boolean;
}

export default function BaseNode({
  data,
  selected,
  isConnectable,
}: BaseNodeProps) {
  const {
    label,
    title,
    kind,
    description,
    preview,
    hasError,
    config,
    schema,
    onConfigChange,
    onMicUpload,
    onDelete,
  } = data as NodeData;
  const { status, statusError, compatState } = data as NodeData;
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});
  const validationTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const [uploading, setUploading] = React.useState(false);
  const [recording, setRecording] = React.useState(false);
  const [micError, setMicError] = React.useState<string | null>(null);
  const mediaRecorderRef = React.useRef<MediaRecorder | null>(null);
  const mediaStreamRef = React.useRef<MediaStream | null>(null);
  const chunksRef = React.useRef<BlobPart[]>([]);

  const fields = Object.entries(schema ?? {});

  React.useEffect(() => {
    return () => {
      mediaRecorderRef.current?.stop?.();
      mediaStreamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const scheduleValidation = (nextConfig: Record<string, unknown>) => {
    if (validationTimerRef.current) clearTimeout(validationTimerRef.current);
    validationTimerRef.current = setTimeout(async () => {
      try {
        const res = await fetch(apiUrl("/validate-node"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ node_type: label, config: nextConfig }),
        });
        if (res.ok) {
          const result = await res.json() as { errors: Record<string, string> };
          setFieldErrors(result.errors ?? {});
        }
      } catch (err) {
        console.warn("Node validation request failed:", err);
      }
    }, 300);
  };

  const handleFieldChange = (field: string, type: string, raw: string, itemType?: string) => {
    if (!onConfigChange) return;
    let parsed: unknown;
    if (type === "number") {
      parsed = raw === "" ? "" : Number(raw);
    } else if (type === "array") {
      const parts = raw.split(",").map((v) => v.trim()).filter(Boolean);
      // Parse items as numbers when the schema declares item_type: "number"
      parsed = itemType === "number"
        ? parts.map((v) => (v === "" ? v : Number(v)))
        : parts;
    } else {
      parsed = raw;
    }
    onConfigChange(field, parsed);
    const nextConfig = { ...(config ?? {}), [field]: parsed };
    scheduleValidation(nextConfig);
  };

  const handleMicFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !onMicUpload) return;
    try {
      setMicError(null);
      setUploading(true);
      const inputPath = await uploadMicFile(file);
      onMicUpload(inputPath);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Unable to upload audio.";
      setMicError(message);
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  const startRecording = async () => {
    if (
      !navigator.mediaDevices?.getUserMedia ||
      !window.MediaRecorder ||
      !onMicUpload
    ) {
      setMicError("Microphone recording is not supported in this browser.");
      return;
    }
    setMicError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (evt) => {
        if (evt.data.size > 0) chunksRef.current.push(evt.data);
      };
      recorder.onerror = () => {
        setMicError("Recording failed. Try again or use Upload Audio.");
      };
      recorder.onstop = async () => {
        try {
          setUploading(true);
          if (chunksRef.current.length === 0) {
            throw new Error("Recording did not capture any audio.");
          }
          const blob = new Blob(chunksRef.current, {
            type: recorder.mimeType || "audio/webm",
          });
          const inputPath = await uploadMicBlob(blob);
          onMicUpload(inputPath);
          setMicError(null);
        } catch (err) {
          const message =
            err instanceof Error
              ? err.message
              : "Unable to save recording. Use Upload Audio instead.";
          setMicError(message);
        } finally {
          setUploading(false);
          setRecording(false);
          mediaStreamRef.current?.getTracks().forEach((t) => t.stop());
          mediaStreamRef.current = null;
        }
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setRecording(true);
    } catch (err) {
      const e = err as DOMException;
      if (e?.name === "NotFoundError") {
        setMicError(
          "No microphone device found. Connect a mic or use Upload Audio.",
        );
      } else if (e?.name === "NotAllowedError") {
        setMicError(
          "Microphone permission denied. Allow mic access or use Upload Audio.",
        );
      } else {
        setMicError("Unable to start recording. Use Upload Audio instead.");
      }
      setRecording(false);
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current?.state === "recording") {
      mediaRecorderRef.current.stop();
    }
  };

  return (
    <div
      className={`
        relative px-4 py-3 rounded-2xl transition-all duration-200 cursor-pointer
        min-w-[250px] max-w-[320px] text-left group backdrop-blur-sm
        ${compatState === "incompatible" ? "opacity-40" : ""}
        ${
          status === "running"
            ? "bg-primary-50/95 dark:bg-primary-900/20 border border-primary-400 dark:border-primary-400 shadow-lg ring-2 ring-primary-200/60"
            : status === "success"
              ? "bg-green-50/95 dark:bg-green-900/20 border border-green-400 dark:border-green-500 shadow-lg"
              : status === "error"
                ? "bg-red-50/95 dark:bg-red-900/20 border border-red-400 dark:border-red-500 shadow-lg"
                : compatState === "compatible"
                  ? "bg-white/95 dark:bg-secondary-800/95 border border-green-400 ring-2 ring-green-200 shadow-green-100 shadow-lg"
                  : hasError || Object.keys(fieldErrors).length > 0
                    ? "bg-red-50/95 dark:bg-red-900/20 border border-red-300 dark:border-red-600 shadow-lg"
                    : selected
                      ? "bg-white/95 dark:bg-secondary-800/95 border border-primary-400 dark:border-primary-400 shadow-2xl ring-2 ring-primary-200/60 dark:ring-primary-500/20"
                      : "bg-white/90 dark:bg-secondary-800/90 border border-secondary-200 dark:border-secondary-700 shadow-md hover:shadow-xl hover:border-secondary-300 dark:hover:border-secondary-600"
        }
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        isConnectable={isConnectable}
        className="!w-3 !h-3 !bg-primary-500 !border-2 !border-white dark:!border-secondary-800"
      />

      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-start gap-3 min-w-0">
          <div className="mt-0.5 p-2 rounded-xl bg-primary-100 text-primary-700 dark:bg-primary-900/30 dark:text-primary-300">
            {label === "mic_input" ? (
              <Radio className="w-4 h-4" />
            ) : (
              <Zap className="w-4 h-4" />
            )}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="font-semibold text-sm text-secondary-900 dark:text-secondary-100 truncate">
                {title || label}
              </div>
              {kind === "plugin" && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-primary-100 text-primary-700 dark:bg-primary-900/30 dark:text-primary-300">
                  plugin
                </span>
              )}
            </div>
            {description && (
              <div className="text-[11px] text-secondary-500 dark:text-secondary-400 mt-0.5 line-clamp-2">
                {description}
              </div>
            )}
          </div>
        </div>
        {/* Status icon */}
        {status === "running" && (
          <div className="mt-0.5 w-4 h-4 rounded-full border-2 border-primary-400 border-t-transparent animate-spin flex-shrink-0" />
        )}
        {status === "success" && (
          <CheckCircle className="w-4 h-4 text-green-500 flex-shrink-0 mt-0.5" />
        )}
        {status === "error" && (
          <div title={statusError} className="flex-shrink-0 mt-0.5">
            <AlertCircle className="w-4 h-4 text-red-500" />
          </div>
        )}
        {onDelete && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            className="nodrag p-1.5 rounded-lg text-secondary-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20"
            title="Delete node"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        )}
      </div>

      <div className="text-xs text-secondary-600 dark:text-secondary-400 mb-3 min-h-[20px] line-clamp-2 bg-secondary-50 dark:bg-secondary-900/40 rounded-xl px-3 py-2 border border-secondary-200/70 dark:border-secondary-700/70">
        {preview || "No config"}
      </div>

      {selected && fields.length > 0 && (
        <div className="mt-2 mb-3 space-y-2 text-left border-t border-secondary-200/80 dark:border-secondary-700/80 pt-3 nodrag">
          {fields.map(([field, def]) => (
            <div key={field} className="text-[10px]">
              <label className="block text-secondary-600 dark:text-secondary-300 mb-1 uppercase tracking-wide">
                {field}
                {def.description && <HelpTooltip text={def.description} />}
              </label>
              <input
                className={`w-full px-2.5 py-2 rounded-xl border bg-white dark:bg-secondary-700 text-secondary-900 dark:text-secondary-100 focus:outline-none focus:ring-2 focus:ring-primary-500/40 ${
                  fieldErrors[field]
                    ? "border-red-400 ring-1 ring-red-200"
                    : "border-secondary-300 dark:border-secondary-600"
                }`}
                type={def.type === "number" ? "number" : "text"}
                value={
                  def.type === "array"
                    ? Array.isArray(config?.[field])
                      ? (config?.[field] as unknown[]).join(",")
                      : ""
                    : String(config?.[field] ?? "")
                }
                onChange={(e) =>
                  handleFieldChange(field, def.type, e.target.value, def.item_type)
                }
              />
              {fieldErrors[field] && (
                <span className="text-red-500 text-[9px] mt-0.5 block">{fieldErrors[field]}</span>
              )}
            </div>
          ))}

          {label === "mic_input" && (
            <div className="flex flex-wrap gap-2 pt-1">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  if (recording) {
                    stopRecording();
                  } else {
                    void startRecording();
                  }
                }}
                className={`nodrag inline-flex items-center gap-1 text-[11px] px-3 py-1.5 rounded-xl border ${recording ? "bg-red-50 border-red-300 text-red-600 dark:bg-red-900/20 dark:border-red-700" : "border-secondary-300 dark:border-secondary-600 hover:bg-secondary-100 dark:hover:bg-secondary-700 text-secondary-700 dark:text-secondary-200"}`}
              >
                <Mic className="w-3 h-3" />
                {recording ? "Stop Recording" : "Record Mic"}
              </button>

              <label className="nodrag inline-flex items-center gap-1 text-[11px] px-3 py-1.5 rounded-xl border border-secondary-300 dark:border-secondary-600 cursor-pointer hover:bg-secondary-100 dark:hover:bg-secondary-700 text-secondary-700 dark:text-secondary-200">
                {uploading ? (
                  <Upload className="w-3 h-3 animate-pulse" />
                ) : (
                  <Mic className="w-3 h-3" />
                )}
                {uploading ? "Uploading..." : "Upload Audio"}
                <input
                  type="file"
                  accept="audio/*"
                  capture="user"
                  className="hidden"
                  onChange={handleMicFile}
                />
              </label>
            </div>
          )}

          {label === "mic_input" && micError && (
            <div className="text-[11px] text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg px-2 py-1">
              {micError}
            </div>
          )}
        </div>
      )}

      {(hasError || Object.keys(fieldErrors).length > 0) && (
        <div className="flex items-center justify-center gap-1 text-xs text-red-600 dark:text-red-400 mb-2">
          <AlertCircle className="w-3 h-3" />
          {Object.keys(fieldErrors).length > 0 ? "Config error" : "Error"}
        </div>
      )}

      <div className="opacity-0 group-hover:opacity-100 transition-opacity text-[11px] text-primary-600 dark:text-primary-400 font-medium">
        Click node to edit • drag handle to connect
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        isConnectable={isConnectable}
        className="!w-3 !h-3 !bg-primary-500 !border-2 !border-white dark:!border-secondary-800"
      />
    </div>
  );
}
