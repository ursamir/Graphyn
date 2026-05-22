import { useEffect, useRef } from "react";
import FlowCanvas from "./FlowCanvas";

interface FlowCanvasWrapperProps {
  schemas: Record<string, unknown>;
}

/**
 * Wrapper component to ensure proper sizing for React Flow
 * This component uses a ResizeObserver to trigger re-renders when container size changes
 */
export default function FlowCanvasWrapper({ schemas }: FlowCanvasWrapperProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    // Set up ResizeObserver to monitor size changes
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect.width > 0 && entry.contentRect.height > 0) {
          window.dispatchEvent(new Event("resize"));
        }
      }
    });

    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  // Force a window resize event to trigger React Flow to re-measure
  useEffect(() => {
    // Slight delay to ensure DOM is ready
    const timer = setTimeout(() => {
      window.dispatchEvent(new Event("resize"));
    }, 500);

    return () => clearTimeout(timer);
  }, []);

  return (
    <div
      ref={containerRef}
      className="flex-1 h-full w-full min-h-0"
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        width: "100%",
      }}
    >
      <div
        className="flex-1 min-h-0"
        style={{
          display: "flex",
          height: "100%",
          width: "100%",
          minHeight: 0,
        }}
      >
        <FlowCanvas schemas={schemas} />
      </div>
    </div>
  );
}
